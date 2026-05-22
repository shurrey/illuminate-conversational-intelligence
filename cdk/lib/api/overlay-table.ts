import { Construct } from 'constructs';
import * as cdk from 'aws-cdk-lib';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';

export interface OverlayTableProps {
  environment: string;
}

/**
 * Per-tenant metric overlays. Each item is one tenant's override of one
 * canonical metric:
 *
 *   tenant_id   (HASH)    — string, e.g. "blackboard-dev"
 *   metric_id   (RANGE)   — string, e.g. "metric.dashboard.retention_rate.v1"
 *   measure_sql           — the override SQL
 *   diff_description      — human-readable explanation of what changed
 *   owner                 — institutional owner ("Lone Star Registrar's Office")
 *   last_reviewed         — ISO date string
 *   updated_at            — ISO timestamp set on every write
 *   updated_by            — Cognito sub of the editor
 */
export class OverlayTable extends Construct {
  public readonly table: dynamodb.Table;
  public readonly tableName: string;

  constructor(scope: Construct, id: string, props: OverlayTableProps) {
    super(scope, id);

    this.table = new dynamodb.Table(this, 'Table', {
      tableName: `illuminate-overlays-${props.environment}`,
      partitionKey: { name: 'tenant_id', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'metric_id', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    this.tableName = this.table.tableName;
  }
}
