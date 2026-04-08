import { Construct } from 'constructs';
import * as bedrockagentcore from 'aws-cdk-lib/aws-bedrockagentcore';

export interface AgentGatewayProps {
  gatewayName: string;
  description: string;
  roleArn: string;
}

export class AgentGateway extends Construct {
  public readonly gatewayId: string;

  constructor(scope: Construct, id: string, props: AgentGatewayProps) {
    super(scope, id);

    const gateway = new bedrockagentcore.CfnGateway(this, 'Gateway', {
      name: props.gatewayName,
      description: props.description,
      protocolType: 'A2A',
      roleArn: props.roleArn,
      authorizerType: 'NONE',
    });

    this.gatewayId = gateway.ref;
  }
}
