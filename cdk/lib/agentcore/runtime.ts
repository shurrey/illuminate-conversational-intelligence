import { Construct } from 'constructs';
import * as bedrockagentcore from 'aws-cdk-lib/aws-bedrockagentcore';
import * as ecr_assets from 'aws-cdk-lib/aws-ecr-assets';
import * as path from 'path';

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
 * Builds a Docker image from the agent source and deploys as a container runtime.
 *
 * Uses a shared Dockerfile at agents/Dockerfile. Each agent directory is the
 * build context, so COPY . . picks up that agent's source code.
 *
 * Instantiated 5 times: sql, analyst, writer, validator, orchestrator.
 */
export class AgentRuntime extends Construct {
  public readonly runtimeArn: string;
  public readonly runtimeId: string;

  constructor(scope: Construct, id: string, props: AgentRuntimeProps) {
    super(scope, id);

    // Build Docker image from agent source directory.
    // Each agent dir has a symlink to the shared agents/Dockerfile.
    // CDK handles ECR repo creation, image build, and push automatically.
    const image = new ecr_assets.DockerImageAsset(this, 'Image', {
      directory: props.sourcePath,
      platform: ecr_assets.Platform.LINUX_ARM64,
      exclude: [
        '.bedrock_agentcore',
        '.bedrock_agentcore.yaml',
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
        containerConfiguration: {
          containerUri: image.imageUri,
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
