import { Construct } from 'constructs';
import * as bedrockagentcore from 'aws-cdk-lib/aws-bedrockagentcore';
import * as s3assets from 'aws-cdk-lib/aws-s3-assets';

export interface AgentRuntimeProps {
  /** Runtime name (e.g., "illuminate_sql_dev") */
  runtimeName: string;
  description: string;
  /** IAM role ARN for the runtime */
  roleArn: string;
  /** Path to the agent source directory (contains a2a_server.py, requirements.txt, etc.) */
  sourcePath: string;
  /** Environment variables for the runtime */
  environmentVariables?: Record<string, string>;
  /** Memory ID to attach (set as BEDROCK_AGENTCORE_MEMORY_ID env var) */
  memoryId?: string;
}

/**
 * Reusable construct for a single AgentCore runtime.
 * Packages the agent source as an S3 asset and creates the runtime.
 *
 * Instantiated 5 times: sql, analyst, writer, validator, orchestrator.
 */
export class AgentRuntime extends Construct {
  public readonly runtimeArn: string;
  public readonly runtimeId: string;

  constructor(scope: Construct, id: string, props: AgentRuntimeProps) {
    super(scope, id);

    // Package the agent source directory as an S3 asset (zip)
    const sourceAsset = new s3assets.Asset(this, 'Source', {
      path: props.sourcePath,
      exclude: [
        '*.pyc',
        '__pycache__',
        '.venv',
        'venv',
        '.git',
        '.bedrock_agentcore',
        '.bedrock_agentcore.yaml',
        '.dockerignore',
        '.env.agentcore',
      ],
    });

    // Build environment variables, including memory ID if provided
    const envVars: Record<string, string> = {
      ...props.environmentVariables,
    };
    if (props.memoryId) {
      envVars['BEDROCK_AGENTCORE_MEMORY_ID'] = props.memoryId;
    }

    const runtime = new bedrockagentcore.CfnRuntime(this, 'Runtime', {
      agentRuntimeName: props.runtimeName,
      description: props.description,
      roleArn: props.roleArn,
      agentRuntimeArtifact: {
        codeConfiguration: {
          code: {
            s3: {
              bucket: sourceAsset.s3BucketName,
              prefix: sourceAsset.s3ObjectKey,
            },
          },
          entryPoint: ['a2a_server.py'],
          runtime: 'PYTHON_3_13',
        },
      },
      protocolConfiguration: 'A2A',
      networkConfiguration: {
        networkMode: 'PUBLIC',
      },
      ...(Object.keys(envVars).length > 0 ? { environmentVariables: envVars } : {}),
    });

    this.runtimeId = runtime.ref;
    this.runtimeArn = runtime.attrAgentRuntimeArn;
  }
}
