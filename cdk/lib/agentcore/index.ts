import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as path from 'path';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import { AgentRole } from './roles';
import { AgentMemory } from './memory';
import { AgentGateway } from './gateway';
import { AgentRuntime } from './runtime';

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
  public readonly agentRoleArn: string;
  public readonly memoryId: string;

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

    // Gateway for A2A agent communication
    new AgentGateway(this, 'Gateway', {
      gatewayName: `illuminate-gateway-${props.environment}`,
      description: 'Gateway for Illuminate A2A agent communication',
      roleArn: agentRole.role.roleArn,
    });

    // Specialist agent runtimes (deployed before orchestrator)
    const snowflakeSecretName = `illuminate/${props.environment}/snowflake`;

    const sql = new AgentRuntime(this, 'SqlAgent', {
      runtimeName: `illuminate_sql_${props.environment}`,
      description: 'SQL agent - generates and executes Snowflake queries',
      roleArn: agentRole.role.roleArn,
      sourcePath: path.join(agentsDir, 'sql'),
      environmentVariables: {
        SNOWFLAKE_SECRET_NAME: snowflakeSecretName,
      },
    });
    this.sqlArn = sql.runtimeArn;

    const analyst = new AgentRuntime(this, 'AnalystAgent', {
      runtimeName: `illuminate_analyst_${props.environment}`,
      description: 'Analyst agent - interprets data and identifies patterns',
      roleArn: agentRole.role.roleArn,
      sourcePath: path.join(agentsDir, 'analyst'),
    });
    this.analystArn = analyst.runtimeArn;

    const writer = new AgentRuntime(this, 'WriterAgent', {
      runtimeName: `illuminate_writer_${props.environment}`,
      description: 'Writer agent - crafts natural language responses',
      roleArn: agentRole.role.roleArn,
      sourcePath: path.join(agentsDir, 'writer'),
    });
    this.writerArn = writer.runtimeArn;

    const validator = new AgentRuntime(this, 'ValidatorAgent', {
      runtimeName: `illuminate_validator_${props.environment}`,
      description: 'Validator agent - ensures FERPA compliance',
      roleArn: agentRole.role.roleArn,
      sourcePath: path.join(agentsDir, 'validator'),
    });
    this.validatorArn = validator.runtimeArn;

    // Orchestrator runtime — deployed last with all specialist ARNs
    const orchestrator = new AgentRuntime(this, 'OrchestratorAgent', {
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
        SNOWFLAKE_SECRET_NAME: snowflakeSecretName,
      },
    });
    this.orchestratorArn = orchestrator.runtimeArn;
  }
}
