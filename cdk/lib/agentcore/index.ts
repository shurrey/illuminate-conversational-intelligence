import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as path from 'path';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import { AgentRole } from './roles';
import { AgentMemory } from './memory';
import { AgentRuntime } from './runtime';
import { FerpaGuardrail } from './guardrails';
import { KeepWarm } from './keepwarm';
import { Discovery } from '../base/discovery';

export interface AgentCoreStackProps extends cdk.StackProps {
  environment: string;
  snowflakeSecret: secretsmanager.Secret;
}

export class AgentCoreStack extends cdk.Stack {
  public readonly orchestratorArn: string;
  public readonly sqlArn: string;
  public readonly analystArn: string;
  public readonly writerArn: string;
  public readonly validatorArn: string;
  public readonly plannerArn: string;
  public readonly schemaExpertArn: string;
  public readonly dataQualityArn: string;
  public readonly agentRoleArn: string;
  public readonly memoryId: string;
  public readonly guardrailId: string;
  public readonly guardrailVersion: string;

  constructor(scope: Construct, id: string, props: AgentCoreStackProps) {
    super(scope, id, props);

    const agentsDir = path.resolve(__dirname, '..', '..', '..', 'agents');

    // IAM role shared by all agent runtimes
    const agentRole = new AgentRole(this, 'AgentRole', {
      environment: props.environment,
      snowflakeSecretArn: props.snowflakeSecret.secretArn,
    });
    this.agentRoleArn = agentRole.role.roleArn;

    // STM memory for orchestrator conversation context
    const memory = new AgentMemory(this, 'Memory', {
      memoryName: `illuminate_memory_${props.environment}`,
      description: 'Conversation memory for Illuminate multi-agent system',
      roleArn: agentRole.role.roleArn,
      eventExpiryDays: 30,
    });
    this.memoryId = memory.memoryId;

    // Bedrock Guardrail for FERPA compliance (runs before/after LLM, not bypassable)
    const guardrail = new FerpaGuardrail(this, 'FerpaGuardrail', {
      environment: props.environment,
    });
    this.guardrailId = guardrail.guardrailId;
    this.guardrailVersion = guardrail.guardrailVersion;

    // Note: Gateway is not used for A2A agents — agents are invoked directly
    // via invoke_agent_runtime. Gateway is for MCP tool hosting only.
    // The gateway construct is kept in lib/agentcore/gateway.ts for future use.

    // Ensure all runtimes wait for the IAM policy to be fully attached.
    // Without this, AgentCore validates ECR access before the policy exists.
    const runtimes: AgentRuntime[] = [];
    const addRuntime = (runtime: AgentRuntime) => {
      runtime.node.addDependency(agentRole.role);
      // Also depend on the DefaultPolicy node if it exists
      const defaultPolicy = agentRole.role.node.tryFindChild('DefaultPolicy');
      if (defaultPolicy) {
        runtime.node.addDependency(defaultPolicy);
      }
      runtimes.push(runtime);
      return runtime;
    };

    // Specialist agent runtimes (deployed before orchestrator)
    const snowflakeSecretName = `illuminate/${props.environment}/snowflake`;

    // Guardrail env vars shared by all agents
    const guardrailEnv = {
      BEDROCK_GUARDRAIL_ID: guardrail.guardrailId,
      BEDROCK_GUARDRAIL_VERSION: guardrail.guardrailVersion,
    };

    const sql = addRuntime(new AgentRuntime(this, 'SqlAgent', {
      runtimeName: `illuminate_sql_${props.environment}`,
      description: 'SQL agent - generates and executes Snowflake queries',
      roleArn: agentRole.role.roleArn,
      sourcePath: path.join(agentsDir, 'sql'),
      environmentVariables: {
        SNOWFLAKE_SECRET_NAME: snowflakeSecretName,
        ...guardrailEnv,
      },
    }));
    this.sqlArn = sql.runtimeArn;

    const analyst = addRuntime(new AgentRuntime(this, 'AnalystAgent', {
      runtimeName: `illuminate_analyst_${props.environment}`,
      description: 'Analyst agent - interprets data and identifies patterns',
      roleArn: agentRole.role.roleArn,
      sourcePath: path.join(agentsDir, 'analyst'),
      environmentVariables: { ...guardrailEnv },
    }));
    this.analystArn = analyst.runtimeArn;

    const writer = addRuntime(new AgentRuntime(this, 'WriterAgent', {
      runtimeName: `illuminate_writer_${props.environment}`,
      description: 'Writer agent - crafts natural language responses',
      roleArn: agentRole.role.roleArn,
      sourcePath: path.join(agentsDir, 'writer'),
      environmentVariables: { ...guardrailEnv },
    }));
    this.writerArn = writer.runtimeArn;

    const validator = addRuntime(new AgentRuntime(this, 'ValidatorAgent', {
      runtimeName: `illuminate_validator_${props.environment}`,
      description: 'Validator agent - ensures FERPA compliance',
      roleArn: agentRole.role.roleArn,
      sourcePath: path.join(agentsDir, 'validator'),
      environmentVariables: { ...guardrailEnv },
    }));
    this.validatorArn = validator.runtimeArn;

    const planner = addRuntime(new AgentRuntime(this, 'PlannerAgent', {
      runtimeName: `illuminate_planner_${props.environment}`,
      description: 'Planner agent - decomposes complex questions into execution plans',
      roleArn: agentRole.role.roleArn,
      sourcePath: path.join(agentsDir, 'planner'),
      environmentVariables: { ...guardrailEnv },
    }));
    this.plannerArn = planner.runtimeArn;

    const schemaExpert = addRuntime(new AgentRuntime(this, 'SchemaExpertAgent', {
      runtimeName: `illuminate_schema_expert_${props.environment}`,
      description: 'Schema expert agent - identifies relevant CDM tables, columns, and joins',
      roleArn: agentRole.role.roleArn,
      sourcePath: path.join(agentsDir, 'schema_expert'),
      environmentVariables: { ...guardrailEnv },
    }));
    this.schemaExpertArn = schemaExpert.runtimeArn;

    const dataQuality = addRuntime(new AgentRuntime(this, 'DataQualityAgent', {
      runtimeName: `illuminate_data_quality_${props.environment}`,
      description: 'Data quality agent - validates query result sanity before analysis',
      roleArn: agentRole.role.roleArn,
      sourcePath: path.join(agentsDir, 'data_quality'),
      environmentVariables: { ...guardrailEnv },
    }));
    this.dataQualityArn = dataQuality.runtimeArn;

    // Orchestrator runtime — deployed last with all specialist ARNs
    const orchestrator = addRuntime(new AgentRuntime(this, 'OrchestratorAgent', {
      runtimeName: `illuminate_orchestrator_${props.environment}`,
      description: 'Orchestrator agent - coordinates specialist agents',
      roleArn: agentRole.role.roleArn,
      sourcePath: path.join(agentsDir, 'orchestrator'),
      memoryId: memory.memoryId,
      environmentVariables: {
        ILLUMINATE_USE_A2A: 'true',
        SQL_AGENT_ARN: sql.runtimeArn,
        ANALYST_AGENT_ARN: analyst.runtimeArn,
        WRITER_AGENT_ARN: writer.runtimeArn,
        VALIDATOR_AGENT_ARN: validator.runtimeArn,
        PLANNER_AGENT_ARN: planner.runtimeArn,
        SCHEMA_EXPERT_AGENT_ARN: schemaExpert.runtimeArn,
        DATA_QUALITY_AGENT_ARN: dataQuality.runtimeArn,
        SNOWFLAKE_SECRET_NAME: snowflakeSecretName,
        ...guardrailEnv,
      },
    }));
    this.orchestratorArn = orchestrator.runtimeArn;

    // Keep-warm: ping all agents every 5 minutes to prevent cold starts
    new KeepWarm(this, 'KeepWarm', {
      environment: props.environment,
      runtimeArns: [
        sql.runtimeArn,
        analyst.runtimeArn,
        writer.runtimeArn,
        validator.runtimeArn,
        planner.runtimeArn,
        schemaExpert.runtimeArn,
        dataQuality.runtimeArn,
        orchestrator.runtimeArn,
      ],
      intervalMinutes: 5,
    });

    // Publish discovery parameters to SSM
    new Discovery(this, 'Discovery', {
      environment: props.environment,
      parameters: {
        'orchestrator-arn': orchestrator.runtimeArn,
        'sql-arn': sql.runtimeArn,
        'analyst-arn': analyst.runtimeArn,
        'writer-arn': writer.runtimeArn,
        'validator-arn': validator.runtimeArn,
        'planner-arn': planner.runtimeArn,
        'schema-expert-arn': schemaExpert.runtimeArn,
        'data-quality-arn': dataQuality.runtimeArn,
        'memory-id': memory.memoryId,
        'guardrail-id': guardrail.guardrailId,
        'guardrail-version': guardrail.guardrailVersion,
      },
    });
  }
}
