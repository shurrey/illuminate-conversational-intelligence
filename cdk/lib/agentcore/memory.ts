import { Construct } from 'constructs';
import * as bedrockagentcore from 'aws-cdk-lib/aws-bedrockagentcore';

export interface AgentMemoryProps {
  memoryName: string;
  description: string;
  roleArn: string;
  /** Event expiry in days (3-365). Default: 30 */
  eventExpiryDays?: number;
}

export class AgentMemory extends Construct {
  public readonly memoryId: string;
  public readonly memoryArn: string;

  constructor(scope: Construct, id: string, props: AgentMemoryProps) {
    super(scope, id);

    const memory = new bedrockagentcore.CfnMemory(this, 'Memory', {
      name: props.memoryName,
      description: props.description,
      memoryExecutionRoleArn: props.roleArn,
      eventExpiryDuration: props.eventExpiryDays ?? 30,
    });

    this.memoryId = memory.attrMemoryId;
    this.memoryArn = memory.attrMemoryArn;
  }
}
