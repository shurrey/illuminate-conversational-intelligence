import { Construct } from 'constructs';
import * as wafv2 from 'aws-cdk-lib/aws-wafv2';

export interface WafProps {
  environment: string;
  isProd: boolean;
  /** 'REGIONAL' for ALB/API Gateway, 'CLOUDFRONT' for CloudFront distributions */
  scope: 'REGIONAL' | 'CLOUDFRONT';
  /** Rule names to exclude from AWSManagedRulesCommonRuleSet */
  commonRuleExclusions?: string[];
}

/**
 * Reusable WAF WebACL construct. Used by both BaseStack (REGIONAL) and
 * FrontendStack (CLOUDFRONT) with the same rule set.
 */
export class Waf extends Construct {
  public readonly webAclArn: string;

  constructor(scope: Construct, id: string, props: WafProps) {
    super(scope, id);

    const suffix = props.scope === 'CLOUDFRONT' ? 'cf-waf' : 'waf';

    const commonRuleConfig: wafv2.CfnWebACL.RuleProperty = {
      name: 'AWSManagedRulesCommonRuleSet',
      priority: 2,
      statement: {
        managedRuleGroupStatement: {
          vendorName: 'AWS',
          name: 'AWSManagedRulesCommonRuleSet',
          ...(props.commonRuleExclusions?.length ? {
            excludedRules: props.commonRuleExclusions.map(name => ({ name })),
          } : {}),
        },
      },
      overrideAction: { none: {} },
      visibilityConfig: {
        sampledRequestsEnabled: true,
        cloudWatchMetricsEnabled: true,
        metricName: 'AWSManagedRulesCommonRuleSet',
      },
    };

    const webAcl = new wafv2.CfnWebACL(this, 'WebACL', {
      name: `illuminate-${suffix}-${props.environment}`,
      scope: props.scope,
      defaultAction: { allow: {} },
      rules: [
        {
          name: 'RateLimitRule',
          priority: 1,
          statement: {
            rateBasedStatement: {
              limit: props.isProd ? 1000 : 2000,
              aggregateKeyType: 'IP',
            },
          },
          action: { block: {} },
          visibilityConfig: {
            sampledRequestsEnabled: true,
            cloudWatchMetricsEnabled: true,
            metricName: 'RateLimitRule',
          },
        },
        commonRuleConfig,
        {
          name: 'AWSManagedRulesSQLiRuleSet',
          priority: 3,
          statement: {
            managedRuleGroupStatement: {
              vendorName: 'AWS',
              name: 'AWSManagedRulesSQLiRuleSet',
            },
          },
          overrideAction: { none: {} },
          visibilityConfig: {
            sampledRequestsEnabled: true,
            cloudWatchMetricsEnabled: true,
            metricName: 'AWSManagedRulesSQLiRuleSet',
          },
        },
        {
          name: 'AWSManagedRulesKnownBadInputsRuleSet',
          priority: 4,
          statement: {
            managedRuleGroupStatement: {
              vendorName: 'AWS',
              name: 'AWSManagedRulesKnownBadInputsRuleSet',
            },
          },
          overrideAction: { none: {} },
          visibilityConfig: {
            sampledRequestsEnabled: true,
            cloudWatchMetricsEnabled: true,
            metricName: 'AWSManagedRulesKnownBadInputsRuleSet',
          },
        },
      ],
      visibilityConfig: {
        sampledRequestsEnabled: true,
        cloudWatchMetricsEnabled: true,
        metricName: `illuminate-${suffix}-${props.environment}`,
      },
    });

    this.webAclArn = webAcl.attrArn;
  }
}
