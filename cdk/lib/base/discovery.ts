import { Construct } from 'constructs';
import * as ssm from 'aws-cdk-lib/aws-ssm';

export interface DiscoveryProps {
  environment: string;
  /** Map of parameter names to values. Keys are suffixed to /illuminate/{env}/{key}. */
  parameters: Record<string, string>;
}

/**
 * Publishes values to SSM Parameter Store for cross-service discovery.
 *
 * Other services read these at deploy-time or runtime (if SSM_DISCOVERY=true)
 * to discover Cognito pool IDs, API URLs, agent ARNs, etc. without hardcoding.
 *
 * When infrastructure is recreated (e.g., new Cognito pool), the SSM values
 * update automatically — downstream services pick up new values on next deploy
 * or restart.
 */
export class Discovery extends Construct {
  constructor(scope: Construct, id: string, props: DiscoveryProps) {
    super(scope, id);

    for (const [key, value] of Object.entries(props.parameters)) {
      new ssm.StringParameter(this, `Param-${key}`, {
        parameterName: `/illuminate/${props.environment}/${key}`,
        stringValue: value,
        description: `Illuminate ${props.environment} - ${key}`,
        tier: ssm.ParameterTier.STANDARD,
      });
    }
  }
}
