import { Construct } from 'constructs';
import * as cdk from 'aws-cdk-lib';
import * as events from 'aws-cdk-lib/aws-events';
import * as targets from 'aws-cdk-lib/aws-events-targets';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as logs from 'aws-cdk-lib/aws-logs';

export interface KeepWarmProps {
  environment: string;
  /** ARNs of all agent runtimes to keep warm */
  runtimeArns: string[];
  /** Ping interval in minutes (default: 5) */
  intervalMinutes?: number;
}

/**
 * EventBridge rule + Lambda that pings all agent runtimes periodically
 * to prevent cold starts. Sends a lightweight /ping request to each agent.
 */
export class KeepWarm extends Construct {
  constructor(scope: Construct, id: string, props: KeepWarmProps) {
    super(scope, id);

    const interval = props.intervalMinutes ?? 5;

    // Lambda that pings each agent runtime
    const pinger = new lambda.Function(this, 'Pinger', {
      functionName: `illuminate-keepwarm-${props.environment}`,
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: 'index.handler',
      timeout: cdk.Duration.seconds(120),
      memorySize: 128,
      code: lambda.Code.fromInline(`
import json
import os
import uuid
import boto3
from botocore.config import Config

client = boto3.client(
    'bedrock-agentcore',
    region_name=os.environ.get('AWS_REGION', 'us-east-1'),
    config=Config(read_timeout=60, connect_timeout=10, retries={'max_attempts': 1}),
)

ARNS = json.loads(os.environ.get('RUNTIME_ARNS', '[]'))

def handler(event, context):
    results = []
    for arn in ARNS:
        name = arn.split('/')[-1]
        try:
            payload = {
                'jsonrpc': '2.0',
                'method': 'message/send',
                'params': {
                    'message': {
                        'messageId': str(uuid.uuid4()),
                        'role': 'user',
                        'parts': [{'kind': 'text', 'text': 'ping'}],
                    }
                },
                'id': str(uuid.uuid4()),
            }
            resp = client.invoke_agent_runtime(
                agentRuntimeArn=arn,
                contentType='application/json',
                accept='application/json',
                payload=json.dumps(payload).encode(),
            )
            # Read response to complete the request
            resp['response'].read()
            results.append({'agent': name, 'status': 'warm'})
            print(f'  OK: {name}')
        except Exception as e:
            results.append({'agent': name, 'status': 'error', 'error': str(e)[:100]})
            print(f'  FAIL: {name}: {e}')
    print(f'Keep-warm complete: {len([r for r in results if r["status"] == "warm"])}/{len(ARNS)} agents warmed')
    return results
`),
      environment: {
        RUNTIME_ARNS: JSON.stringify(props.runtimeArns),
      },
    });

    // Grant the Lambda permission to invoke all agent runtimes
    pinger.addToRolePolicy(new iam.PolicyStatement({
      actions: ['bedrock-agentcore:InvokeAgentRuntime'],
      resources: [
        `arn:aws:bedrock-agentcore:${cdk.Aws.REGION}:${cdk.Aws.ACCOUNT_ID}:runtime/illuminate_*`,
      ],
    }));

    // Log group
    new logs.LogGroup(this, 'LogGroup', {
      logGroupName: `/aws/lambda/${pinger.functionName}`,
      retention: logs.RetentionDays.ONE_WEEK,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // EventBridge rule — ping every N minutes
    new events.Rule(this, 'Rule', {
      ruleName: `illuminate-keepwarm-${props.environment}`,
      description: `Ping Illuminate agents every ${interval} minutes to prevent cold starts`,
      schedule: events.Schedule.rate(cdk.Duration.minutes(interval)),
      targets: [new targets.LambdaFunction(pinger)],
    });
  }
}
