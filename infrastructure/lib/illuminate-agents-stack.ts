/**
 * AWS CDK Stack for Illuminate Conversational Intelligence
 *
 * Deploys the multi-agent system using AWS Bedrock AgentCore
 */

import * as cdk from 'aws-cdk-lib';
import * as agentcore from 'aws-cdk-lib/aws-bedrockagentcore';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as apigateway from 'aws-cdk-lib/aws-apigateway';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as wafv2 from 'aws-cdk-lib/aws-wafv2';
import * as cognito from 'aws-cdk-lib/aws-cognito';
import * as certificatemanager from 'aws-cdk-lib/aws-certificatemanager';
import * as route53 from 'aws-cdk-lib/aws-route53';
import * as targets from 'aws-cdk-lib/aws-route53-targets';
import { Construct } from 'constructs';

export interface IlluminateAgentsStackProps extends cdk.StackProps {
  snowflakeAccount?: string;
  environment?: 'dev' | 'staging' | 'prod';
  domainName?: string;
  certificateArn?: string;
  allowedOrigins?: string[];
  institutionIdpUrl?: string;
}

export class IlluminateAgentsStack extends cdk.Stack {
  public readonly apiUrl: cdk.CfnOutput;
  public readonly gatewayId: cdk.CfnOutput;

  constructor(scope: Construct, id: string, props?: IlluminateAgentsStackProps) {
    super(scope, id, props);

    const env = props?.environment || 'dev';
    const isProd = env === 'prod';

    // ===========================================
    // Network Security (VPC)
    // ===========================================

    // VPC for agent isolation
    const vpc = new ec2.Vpc(this, 'IlluminateVpc', {
      maxAzs: 2,
      natGateways: isProd ? 2 : 1,
      subnetConfiguration: [
        {
          cidrMask: 24,
          name: 'Public',
          subnetType: ec2.SubnetType.PUBLIC
        },
        {
          cidrMask: 24,
          name: 'Private',
          subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS
        }
      ]
    });

    // Security group for agent communication
    const agentSecurityGroup = new ec2.SecurityGroup(this, 'AgentSecurityGroup', {
      vpc,
      description: 'Security group for Illuminate agents',
      allowAllOutbound: true
    });

    // Allow internal A2A communication
    agentSecurityGroup.addIngressRule(
      agentSecurityGroup,
      ec2.Port.tcp(443),
      'Internal A2A communication'
    );

    // ===========================================
    // Authentication & Authorization
    // ===========================================

    // Cognito User Pool for API authentication
    const userPool = new cognito.UserPool(this, 'IlluminateUserPool', {
      userPoolName: `illuminate-users-${env}`,
      selfSignUpEnabled: false, // Admin-managed users only
      signInAliases: {
        email: true,
        username: true
      },
      passwordPolicy: {
        minLength: 12,
        requireLowercase: true,
        requireUppercase: true,
        requireDigits: true,
        requireSymbols: true
      },
      accountRecovery: cognito.AccountRecovery.EMAIL_ONLY,
      removalPolicy: isProd ? cdk.RemovalPolicy.RETAIN : cdk.RemovalPolicy.DESTROY
    });

    // User Pool Client for API access
    const userPoolClient = new cognito.UserPoolClient(this, 'IlluminateApiClient', {
      userPool,
      userPoolClientName: `illuminate-api-${env}`,
      generateSecret: true,
      authFlows: {
        userPassword: true,
        userSrp: true
      },
      oAuth: {
        flows: {
          authorizationCodeGrant: true
        },
        scopes: [cognito.OAuthScope.OPENID, cognito.OAuthScope.EMAIL, cognito.OAuthScope.PROFILE],
        callbackUrls: props?.allowedOrigins || ['http://localhost:3000']
      }
    });

    // Identity Pool for AWS resource access
    const identityPool = new cognito.CfnIdentityPool(this, 'IlluminateIdentityPool', {
      identityPoolName: `illuminate_identity_${env}`,
      allowUnauthenticatedIdentities: false,
      cognitoIdentityProviders: [{
        clientId: userPoolClient.userPoolClientId,
        providerName: userPool.userPoolProviderName
      }]
    });

    // ===========================================
    // WAF for API Protection
    // ===========================================

    const webAcl = new wafv2.CfnWebACL(this, 'IlluminateWebAcl', {
      scope: 'REGIONAL',
      defaultAction: { allow: {} },
      rules: [
        {
          name: 'RateLimitRule',
          priority: 1,
          statement: {
            rateBasedStatement: {
              limit: isProd ? 1000 : 2000,
              aggregateKeyType: 'IP'
            }
          },
          action: { block: {} },
          visibilityConfig: {
            sampledRequestsEnabled: true,
            cloudWatchMetricsEnabled: true,
            metricName: 'RateLimitRule'
          }
        },
        {
          name: 'AWSManagedRulesCommonRuleSet',
          priority: 2,
          overrideAction: { none: {} },
          statement: {
            managedRuleGroupStatement: {
              vendorName: 'AWS',
              name: 'AWSManagedRulesCommonRuleSet'
            }
          },
          visibilityConfig: {
            sampledRequestsEnabled: true,
            cloudWatchMetricsEnabled: true,
            metricName: 'CommonRuleSetMetric'
          }
        },
        {
          name: 'AWSManagedRulesKnownBadInputsRuleSet',
          priority: 3,
          overrideAction: { none: {} },
          statement: {
            managedRuleGroupStatement: {
              vendorName: 'AWS',
              name: 'AWSManagedRulesKnownBadInputsRuleSet'
            }
          },
          visibilityConfig: {
            sampledRequestsEnabled: true,
            cloudWatchMetricsEnabled: true,
            metricName: 'KnownBadInputsMetric'
          }
        }
      ],
      visibilityConfig: {
        sampledRequestsEnabled: true,
        cloudWatchMetricsEnabled: true,
        metricName: 'IlluminateWebAcl'
      }
    });

    // ===========================================
    // Secrets & Storage
    // ===========================================

    // Secrets for Snowflake connection
    const snowflakeSecret = new secretsmanager.Secret(this, 'SnowflakeCredentials', {
      secretName: `illuminate/${env}/snowflake`,
      description: 'Snowflake connection credentials for Illuminate',
      generateSecretString: {
        secretStringTemplate: JSON.stringify({
          account: props?.snowflakeAccount || '',
          database: '',  // BLACKBOARD_DATA_<GUID> - institution-specific
          warehouse: 'BLACKBOARD_DATA_WH',
          role: 'BBDATA_USER_ROLE',
          user: 'SVC_BLACKBOARD_DATA'
        }),
        generateStringKey: 'password'
      }
    });

    // S3 bucket for agent artifacts and exports
    const artifactsBucket = new s3.Bucket(this, 'ArtifactsBucket', {
      bucketName: `illuminate-artifacts-${env}-${this.account}`,
      removalPolicy: env === 'prod' ? cdk.RemovalPolicy.RETAIN : cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: env !== 'prod',
      encryption: s3.BucketEncryption.S3_MANAGED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL
    });

    // ===========================================
    // IAM Roles for AgentCore
    // ===========================================

    // Role for AgentCore Runtime with least privilege
    const agentRuntimeRole = new iam.Role(this, 'AgentRuntimeRole', {
      assumedBy: new iam.ServicePrincipal('bedrock.amazonaws.com'),
      description: 'Role for Illuminate AgentCore Runtime',
    });

    // Authenticated user role for API access
    const authenticatedRole = new iam.Role(this, 'AuthenticatedRole', {
      assumedBy: new iam.FederatedPrincipal(
        'cognito-identity.amazonaws.com',
        {
          StringEquals: {
            'cognito-identity.amazonaws.com:aud': identityPool.ref
          },
          'ForAnyValue:StringLike': {
            'cognito-identity.amazonaws.com:amr': 'authenticated'
          }
        },
        'sts:AssumeRoleWithWebIdentity'
      )
    });

    // Attach roles to identity pool
    new cognito.CfnIdentityPoolRoleAttachment(this, 'IdentityPoolRoleAttachment', {
      identityPoolId: identityPool.ref,
      roles: {
        authenticated: authenticatedRole.roleArn
      }
    });

    // Bedrock model invocation permissions
    agentRuntimeRole.addToPolicy(new iam.PolicyStatement({
      actions: [
        'bedrock:InvokeModel',
        'bedrock:InvokeModelWithResponseStream'
      ],
      resources: ['*']
    }));

    // Secrets Manager access
    snowflakeSecret.grantRead(agentRuntimeRole);

    // S3 access for artifacts
    artifactsBucket.grantReadWrite(agentRuntimeRole);

    // CloudWatch Logs permissions
    agentRuntimeRole.addToPolicy(new iam.PolicyStatement({
      actions: [
        'logs:CreateLogGroup',
        'logs:CreateLogStream',
        'logs:PutLogEvents'
      ],
      resources: ['*']
    }));

    // ===========================================
    // BedrockAgentCore - Memory
    // ===========================================

    // Memory store for conversation persistence
    const conversationMemory = new agentcore.CfnMemory(this, 'ConversationMemory', {
      name: `illuminate-memory-${env}`,
      description: 'Conversation memory for Illuminate multi-agent system',
      // Memory configuration for session and semantic storage
      memoryConfiguration: {
        type: 'SESSION_SUMMARY',
        sessionSummaryConfiguration: {
          maxRecentSessions: 10
        }
      },
      // Optional: encryption configuration
      encryptionConfiguration: {
        kmsKeyId: 'alias/aws/bedrock'
      }
    });

    // ===========================================
    // BedrockAgentCore - Gateway
    // ===========================================

    // Gateway for agent access with enhanced security
    const agentGateway = new agentcore.CfnGateway(this, 'IlluminateGateway', {
      name: `illuminate-gateway-${env}`,
      description: 'Gateway for Illuminate Conversational Intelligence agents',
      // Protocol configuration for A2A support
      protocolConfiguration: {
        type: 'MCP'  // Model Context Protocol for Snowflake connectivity
      },
      // Authorization configuration with IAM + mTLS
      authorizationConfiguration: {
        type: 'IAM',
        // Additional security for production
        ...(isProd && {
          mutualTlsConfiguration: {
            certificateArn: props?.certificateArn
          }
        })
      },
      // Network configuration for VPC isolation
      networkConfiguration: {
        type: 'VPC',
        vpcConfiguration: {
          subnetIds: vpc.privateSubnets.map(subnet => subnet.subnetId),
          securityGroupIds: [agentSecurityGroup.securityGroupId]
        }
      }
    });

    // ===========================================
    // AgentCore Policies (Cedar Rules)
    // ===========================================

    // Policy for data access control
    const dataAccessPolicy = new agentcore.CfnPolicy(this, 'DataAccessPolicy', {
      name: `illuminate-data-policy-${env}`,
      description: 'Cedar policy for Illuminate data access control',
      policyDocument: JSON.stringify({
        policies: [
          {
            effect: 'permit',
            principal: {
              op: 'in',
              entity: { type: 'Role', id: 'Analyst' }
            },
            action: {
              op: 'in',
              entities: [
                { type: 'Action', id: 'query' },
                { type: 'Action', id: 'read' }
              ]
            },
            resource: {
              op: 'in',
              entities: [
                { type: 'Schema', id: 'CDM_LMS' },
                { type: 'Schema', id: 'CDM_SIS' },
                { type: 'Schema', id: 'CDM_TLM' }
              ]
            }
          },
          {
            effect: 'forbid',
            principal: { op: 'all' },
            action: { op: 'all' },
            resource: {
              op: 'in',
              entities: [
                { type: 'Column', id: 'SSN' },
                { type: 'Column', id: 'STUDENT_SSN' },
                { type: 'Column', id: 'CREDIT_CARD' },
                { type: 'Column', id: 'PHONE_NUMBER' }
              ]
            }
          },
          {
            effect: 'permit',
            principal: {
              op: 'in',
              entity: { type: 'Role', id: 'Administrator' }
            },
            action: { op: 'all' },
            resource: { op: 'all' }
          }
        ]
      })
    });

    // ===========================================
    // BedrockAgentCore - Runtime
    // ===========================================

    // Runtime for Orchestrator Agent (public subnet for API access)
    const orchestratorRuntime = new agentcore.CfnRuntime(this, 'OrchestratorRuntime', {
      name: `illuminate-orchestrator-${env}`,
      description: 'Orchestrator agent runtime - routes queries to specialist agents',
      roleArn: agentRuntimeRole.roleArn,
      // Network configuration for API Gateway access
      networkConfiguration: {
        type: 'VPC',
        vpcConfiguration: {
          subnetIds: vpc.publicSubnets.map(subnet => subnet.subnetId),
          securityGroupIds: [agentSecurityGroup.securityGroupId]
        }
      },
      // Attach data access policy
      policyArns: [dataAccessPolicy.attrPolicyArn]
    });

    // Runtime Endpoint for Orchestrator (Sonnet 4 - fast coordination)
    const orchestratorEndpoint = new agentcore.CfnRuntimeEndpoint(this, 'OrchestratorEndpoint', {
      name: `illuminate-orchestrator-endpoint-${env}`,
      description: 'Endpoint for orchestrator agent invocation',
      runtimeArn: orchestratorRuntime.attrRuntimeArn,
      // Model configuration - Sonnet 4 for orchestration
      modelConfiguration: {
        modelId: 'anthropic.claude-sonnet-4-20250514-v1:0',
        // Inference configuration - lower temperature for consistent routing
        inferenceConfiguration: {
          maximumLength: 4096,
          temperature: 0.3,
          topP: 0.9
        }
      }
    });

    // Runtime for Validator Agent (private subnet - internal only)
    const validatorRuntime = new agentcore.CfnRuntime(this, 'ValidatorAgentRuntime', {
      name: `illuminate-validator-agent-${env}`,
      description: 'Validator agent runtime - LLM-as-judge for response validation',
      roleArn: agentRuntimeRole.roleArn,
      networkConfiguration: {
        type: 'VPC',
        vpcConfiguration: {
          subnetIds: vpc.privateSubnets.map(subnet => subnet.subnetId),
          securityGroupIds: [agentSecurityGroup.securityGroupId]
        }
      },
      policyArns: [dataAccessPolicy.attrPolicyArn]
    });

    // Runtime Endpoint for Validator (Sonnet 4 - very low temperature)
    const validatorEndpoint = new agentcore.CfnRuntimeEndpoint(this, 'ValidatorEndpoint', {
      name: `illuminate-validator-endpoint-${env}`,
      description: 'Endpoint for validator agent invocation',
      runtimeArn: validatorRuntime.attrRuntimeArn,
      modelConfiguration: {
        modelId: 'anthropic.claude-sonnet-4-20250514-v1:0',
        inferenceConfiguration: {
          maximumLength: 4096,
          temperature: 0.1,  // Very low for strict validation
          topP: 0.9
        }
      }
    });

    // Runtime for Learning Agent (CDM_LMS specialist) - Private subnet
    const learningRuntime = new agentcore.CfnRuntime(this, 'LearningAgentRuntime', {
      name: `illuminate-learning-agent-${env}`,
      description: 'Learning agent runtime - CDM_LMS data specialist (Opus 4)',
      roleArn: agentRuntimeRole.roleArn,
      networkConfiguration: {
        type: 'VPC',
        vpcConfiguration: {
          subnetIds: vpc.privateSubnets.map(subnet => subnet.subnetId),
          securityGroupIds: [agentSecurityGroup.securityGroupId]
        }
      },
      policyArns: [dataAccessPolicy.attrPolicyArn]
    });

    // Learning Agent Endpoint (Opus 4 - deep analysis)
    new agentcore.CfnRuntimeEndpoint(this, 'LearningEndpoint', {
      name: `illuminate-learning-endpoint-${env}`,
      description: 'Endpoint for learning agent',
      runtimeArn: learningRuntime.attrRuntimeArn,
      modelConfiguration: {
        modelId: 'anthropic.claude-opus-4-20250514-v1:0',
        inferenceConfiguration: {
          maximumLength: 4096,
          temperature: 0.7,
          topP: 0.9
        }
      }
    });

    // Runtime for Student Agent (CDM_SIS specialist) - Private subnet
    const studentRuntime = new agentcore.CfnRuntime(this, 'StudentAgentRuntime', {
      name: `illuminate-student-agent-${env}`,
      description: 'Student agent runtime - CDM_SIS data specialist (Opus 4)',
      roleArn: agentRuntimeRole.roleArn,
      networkConfiguration: {
        type: 'VPC',
        vpcConfiguration: {
          subnetIds: vpc.privateSubnets.map(subnet => subnet.subnetId),
          securityGroupIds: [agentSecurityGroup.securityGroupId]
        }
      },
      policyArns: [dataAccessPolicy.attrPolicyArn]
    });

    // Student Agent Endpoint (Opus 4 - deep analysis)
    new agentcore.CfnRuntimeEndpoint(this, 'StudentEndpoint', {
      name: `illuminate-student-endpoint-${env}`,
      description: 'Endpoint for student agent',
      runtimeArn: studentRuntime.attrRuntimeArn,
      modelConfiguration: {
        modelId: 'anthropic.claude-opus-4-20250514-v1:0',
        inferenceConfiguration: {
          maximumLength: 4096,
          temperature: 0.7,
          topP: 0.9
        }
      }
    });

    // Runtime for Telemetry Agent (CDM_TLM specialist) - Private subnet
    const telemetryRuntime = new agentcore.CfnRuntime(this, 'TelemetryAgentRuntime', {
      name: `illuminate-telemetry-agent-${env}`,
      description: 'Telemetry agent runtime - CDM_TLM data specialist (Opus 4)',
      roleArn: agentRuntimeRole.roleArn,
      networkConfiguration: {
        type: 'VPC',
        vpcConfiguration: {
          subnetIds: vpc.privateSubnets.map(subnet => subnet.subnetId),
          securityGroupIds: [agentSecurityGroup.securityGroupId]
        }
      },
      policyArns: [dataAccessPolicy.attrPolicyArn]
    });

    // Telemetry Agent Endpoint (Opus 4 - deep analysis)
    new agentcore.CfnRuntimeEndpoint(this, 'TelemetryEndpoint', {
      name: `illuminate-telemetry-endpoint-${env}`,
      description: 'Endpoint for telemetry agent',
      runtimeArn: telemetryRuntime.attrRuntimeArn,
      modelConfiguration: {
        modelId: 'anthropic.claude-opus-4-20250514-v1:0',
        inferenceConfiguration: {
          maximumLength: 4096,
          temperature: 0.7,
          topP: 0.9
        }
      }
    });

    // Runtime for Visualization Agent - Private subnet
    const visualizationRuntime = new agentcore.CfnRuntime(this, 'VisualizationAgentRuntime', {
      name: `illuminate-visualization-agent-${env}`,
      description: 'Visualization agent runtime - charts and data export (Opus 4)',
      roleArn: agentRuntimeRole.roleArn,
      networkConfiguration: {
        type: 'VPC',
        vpcConfiguration: {
          subnetIds: vpc.privateSubnets.map(subnet => subnet.subnetId),
          securityGroupIds: [agentSecurityGroup.securityGroupId]
        }
      },
      policyArns: [dataAccessPolicy.attrPolicyArn]
    });

    // Visualization Agent Endpoint (Opus 4)
    new agentcore.CfnRuntimeEndpoint(this, 'VisualizationEndpoint', {
      name: `illuminate-visualization-endpoint-${env}`,
      description: 'Endpoint for visualization agent',
      runtimeArn: visualizationRuntime.attrRuntimeArn,
      modelConfiguration: {
        modelId: 'anthropic.claude-opus-4-20250514-v1:0',
        inferenceConfiguration: {
          maximumLength: 4096,
          temperature: 0.7,
          topP: 0.9
        }
      }
    });

    // ===========================================
    // Gateway Targets - Connect agents to gateway
    // ===========================================

    // Gateway target for Orchestrator
    new agentcore.CfnGatewayTarget(this, 'OrchestratorGatewayTarget', {
      name: `illuminate-orchestrator-target-${env}`,
      gatewayArn: agentGateway.attrGatewayArn,
      targetConfiguration: {
        type: 'RUNTIME',
        runtimeConfiguration: {
          runtimeArn: orchestratorRuntime.attrRuntimeArn
        }
      }
    });

    // ===========================================
    // Lambda for API Layer (bridges HTTP to AgentCore)
    // ===========================================

    // Lambda layer for shared dependencies
    const dependenciesLayer = new lambda.LayerVersion(this, 'DependenciesLayer', {
      code: lambda.Code.fromAsset('../agents', {
        bundling: {
          image: lambda.Runtime.PYTHON_3_11.bundlingImage,
          command: [
            'bash', '-c',
            'pip install -r requirements.txt -t /asset-output/python && cp -r . /asset-output/python/agents'
          ]
        }
      }),
      compatibleRuntimes: [lambda.Runtime.PYTHON_3_11],
      description: 'Illuminate agent dependencies'
    });

    // Lambda function to bridge API Gateway to AgentCore with VPC access
    const apiHandlerFunction = new lambda.Function(this, 'ApiHandlerFunction', {
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: 'api_handler.lambda_handler',
      code: lambda.Code.fromAsset('../agents/orchestrator'),
      layers: [dependenciesLayer],
      timeout: cdk.Duration.seconds(60),
      memorySize: 1024,
      vpc: vpc,
      vpcSubnets: {
        subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS
      },
      securityGroups: [agentSecurityGroup],
      environment: {
        ILLUMINATE_MOCK_MODE: env === 'dev' ? 'true' : 'false',
        SNOWFLAKE_SECRET_ARN: snowflakeSecret.secretArn,
        AGENTCORE_GATEWAY_ARN: agentGateway.attrGatewayArn,
        AGENTCORE_MEMORY_ARN: conversationMemory.attrMemoryArn,
        ORCHESTRATOR_RUNTIME_ARN: orchestratorRuntime.attrRuntimeArn,
        ARTIFACTS_BUCKET: artifactsBucket.bucketName,
        USER_POOL_ID: userPool.userPoolId,
        USER_POOL_CLIENT_ID: userPoolClient.userPoolClientId,
        LOG_LEVEL: isProd ? 'WARN' : 'INFO'
      },
      logRetention: isProd ? logs.RetentionDays.ONE_MONTH : logs.RetentionDays.ONE_WEEK
    });

    // Grant permissions
    snowflakeSecret.grantRead(apiHandlerFunction);
    artifactsBucket.grantReadWrite(apiHandlerFunction);

    // AgentCore invocation permissions (least privilege)
    apiHandlerFunction.addToRolePolicy(new iam.PolicyStatement({
      actions: [
        'bedrock:InvokeAgent',
        'bedrock:InvokeAgentWithResponseStream'
      ],
      resources: [
        orchestratorRuntime.attrRuntimeArn,
        agentGateway.attrGatewayArn
      ]
    }));

    // Cognito permissions for token validation
    apiHandlerFunction.addToRolePolicy(new iam.PolicyStatement({
      actions: [
        'cognito-idp:GetUser',
        'cognito-idp:AdminGetUser'
      ],
      resources: [userPool.userPoolArn]
    }));

    // ===========================================
    // API Gateway
    // ===========================================

    // API Gateway with Cognito authorizer
    const authorizer = new apigateway.CognitoUserPoolsAuthorizer(this, 'IlluminateAuthorizer', {
      cognitoUserPools: [userPool],
      authorizerName: 'IlluminateAuth'
    });

    const api = new apigateway.RestApi(this, 'IlluminateApi', {
      restApiName: 'Illuminate Conversational Intelligence',
      description: 'API for natural language queries against Illuminate data',
      deployOptions: {
        stageName: env,
        throttlingRateLimit: isProd ? 100 : 1000,
        throttlingBurstLimit: isProd ? 200 : 2000,
        loggingLevel: apigateway.MethodLoggingLevel.INFO,
        dataTraceEnabled: !isProd,
        metricsEnabled: true
      },
      defaultCorsPreflightOptions: {
        allowOrigins: props?.allowedOrigins || (isProd ? [] : ['http://localhost:3000']),
        allowMethods: ['GET', 'POST', 'DELETE', 'OPTIONS'],
        allowHeaders: ['Content-Type', 'Authorization'],
        allowCredentials: true
      },
      policy: new iam.PolicyDocument({
        statements: [
          new iam.PolicyStatement({
            effect: iam.Effect.ALLOW,
            principals: [new iam.AnyPrincipal()],
            actions: ['execute-api:Invoke'],
            resources: ['*'],
            conditions: {
              StringEquals: {
                'aws:SourceVpc': vpc.vpcId
              }
            }
          })
        ]
      })
    });

    // Associate WAF with API Gateway
    new wafv2.CfnWebACLAssociation(this, 'ApiGatewayWafAssociation', {
      resourceArn: `arn:aws:apigateway:${this.region}::/restapis/${api.restApiId}/stages/${env}`,
      webAclArn: webAcl.attrArn
    });

    // API endpoints with authentication
    const apiResource = api.root.addResource('api');
    
    // Chat endpoint (requires authentication)
    const chatResource = apiResource.addResource('chat');
    chatResource.addMethod('POST', new apigateway.LambdaIntegration(apiHandlerFunction, {
      proxy: true
    }), {
      authorizer,
      authorizationType: apigateway.AuthorizationType.COGNITO
    });

    // Streaming endpoint (requires authentication)
    const streamResource = chatResource.addResource('stream');
    streamResource.addMethod('POST', new apigateway.LambdaIntegration(apiHandlerFunction, {
      proxy: true
    }), {
      authorizer,
      authorizationType: apigateway.AuthorizationType.COGNITO
    });

    // Conversations endpoint (requires authentication)
    const conversationsResource = apiResource.addResource('conversations');
    const conversationIdResource = conversationsResource.addResource('{contextId}');
    conversationIdResource.addMethod('GET', new apigateway.LambdaIntegration(apiHandlerFunction, {
      proxy: true
    }), {
      authorizer,
      authorizationType: apigateway.AuthorizationType.COGNITO
    });
    conversationIdResource.addMethod('DELETE', new apigateway.LambdaIntegration(apiHandlerFunction, {
      proxy: true
    }), {
      authorizer,
      authorizationType: apigateway.AuthorizationType.COGNITO
    });

    // Health endpoint (public - no auth required)
    const healthResource = api.root.addResource('health');
    healthResource.addMethod('GET', new apigateway.LambdaIntegration(apiHandlerFunction, {
      proxy: true
    }));

    // Agent discovery endpoint (protected)
    const wellKnownResource = api.root.addResource('.well-known');
    const agentResource = wellKnownResource.addResource('agent.json');
    agentResource.addMethod('GET', new apigateway.LambdaIntegration(apiHandlerFunction, {
      proxy: true
    }), {
      authorizer,
      authorizationType: apigateway.AuthorizationType.COGNITO
    });

    // ===========================================
    // Outputs
    // ===========================================

    this.apiUrl = new cdk.CfnOutput(this, 'ApiUrl', {
      value: api.url,
      description: 'API Gateway URL'
    });

    this.gatewayId = new cdk.CfnOutput(this, 'GatewayArn', {
      value: agentGateway.attrGatewayArn,
      description: 'AgentCore Gateway ARN'
    });

    new cdk.CfnOutput(this, 'MemoryArn', {
      value: conversationMemory.attrMemoryArn,
      description: 'AgentCore Memory ARN'
    });

    new cdk.CfnOutput(this, 'OrchestratorRuntimeArn', {
      value: orchestratorRuntime.attrRuntimeArn,
      description: 'Orchestrator Runtime ARN (Sonnet 4)'
    });

    new cdk.CfnOutput(this, 'ValidatorRuntimeArn', {
      value: validatorRuntime.attrRuntimeArn,
      description: 'Validator Runtime ARN (Sonnet 4)'
    });

    new cdk.CfnOutput(this, 'SecretArn', {
      value: snowflakeSecret.secretArn,
      description: 'Snowflake credentials secret ARN'
    });

    new cdk.CfnOutput(this, 'ArtifactsBucketName', {
      value: artifactsBucket.bucketName,
      description: 'S3 bucket for artifacts and exports'
    });

    new cdk.CfnOutput(this, 'UserPoolId', {
      value: userPool.userPoolId,
      description: 'Cognito User Pool ID for authentication'
    });

    new cdk.CfnOutput(this, 'UserPoolClientId', {
      value: userPoolClient.userPoolClientId,
      description: 'Cognito User Pool Client ID'
    });

    new cdk.CfnOutput(this, 'VpcId', {
      value: vpc.vpcId,
      description: 'VPC ID for network isolation'
    });

    new cdk.CfnOutput(this, 'WebAclArn', {
      value: webAcl.attrArn,
      description: 'WAF Web ACL ARN for API protection'
    });
  }
}
