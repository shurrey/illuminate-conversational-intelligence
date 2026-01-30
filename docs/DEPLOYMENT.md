# AWS Deployment Guide

## Prerequisites

- AWS CLI v2 configured
- AWS CDK v2 installed (`npm install -g aws-cdk`)
- AWS account with Bedrock access enabled
- Snowflake account with Illuminate data

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    AWS Cloud                             │
│  ┌─────────────────┐    ┌─────────────────┐            │
│  │   CloudFront    │───▶│    S3 Bucket    │            │
│  │   (Frontend)    │    │   (React App)   │            │
│  └─────────────────┘    └─────────────────┘            │
│           │                                              │
│           ▼                                              │
│  ┌─────────────────┐    ┌─────────────────┐            │
│  │   API Gateway   │───▶│     Lambda      │            │
│  │   (REST API)    │    │   (FastAPI)     │            │
│  └─────────────────┘    └─────────────────┘            │
│                                │                        │
│                                ▼                        │
│  ┌─────────────────┐    ┌─────────────────┐            │
│  │ Secrets Manager │───▶│ Bedrock Agents  │            │
│  │  (Credentials)  │    │  (Claude LLM)   │            │
│  └─────────────────┘    └─────────────────┘            │
│                                │                        │
└────────────────────────────────│────────────────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │       Snowflake         │
                    │   (Illuminate Data)     │
                    └─────────────────────────┘
```

## Deployment Steps

### 1. Configure AWS Credentials

```bash
aws configure
# Enter AWS Access Key, Secret Key, Region (us-east-1)
```

### 2. Create Secrets in AWS Secrets Manager

**Snowflake credentials:**
```bash
aws secretsmanager create-secret \
  --name illuminate/snowflake \
  --secret-string '{
    "account": "xxx.snowflakecomputing.com",
    "user": "illuminate_service",
    "password": "xxx",
    "warehouse": "ILLUMINATE_WH",
    "database": "ILLUMINATE",
    "role": "ILLUMINATE_ANALYST_ROLE"
  }'
```

**Anthropic API key:**
```bash
aws secretsmanager create-secret \
  --name illuminate/anthropic \
  --secret-string '{"api_key": "sk-ant-xxx"}'
```

### 3. Deploy Infrastructure

```bash
cd infrastructure
npm install
cdk bootstrap  # First time only
cdk deploy
```

### 4. Build and Deploy Frontend

```bash
cd frontend
npm run build

# Upload to S3
aws s3 sync dist/ s3://illuminate-frontend-bucket/

# Invalidate CloudFront cache
aws cloudfront create-invalidation \
  --distribution-id XXXXX \
  --paths "/*"
```

### 5. Configure DNS (Optional)

Point your domain to the CloudFront distribution in Route 53.

## Environment Variables

### Production .env

```bash
# Application
ILLUMINATE_MOCK_MODE=false
LOG_LEVEL=INFO

# AWS
AWS_REGION=us-east-1
USE_BEDROCK=true
BEDROCK_MODEL_ORCHESTRATOR=anthropic.claude-sonnet-4-20250514-v1:0
BEDROCK_MODEL_VALIDATOR=anthropic.claude-sonnet-4-20250514-v1:0
BEDROCK_MODEL_WORKER=anthropic.claude-opus-4-20250514-v1:0

# Secrets (retrieved from Secrets Manager at runtime)
SNOWFLAKE_SECRET_ARN=arn:aws:secretsmanager:...
ANTHROPIC_SECRET_ARN=arn:aws:secretsmanager:...
```

## Monitoring

### CloudWatch Dashboards

Create dashboards for:
- API latency (P50, P90, P99)
- Lambda invocations and errors
- Bedrock token usage
- Error rates by endpoint

### CloudWatch Alarms

Configure alerts for:
- Error rate > 5%
- P99 latency > 30s
- Lambda throttling
- Daily cost threshold

### Example Alarm

```bash
aws cloudwatch put-metric-alarm \
  --alarm-name "ICI-HighErrorRate" \
  --metric-name "5XXError" \
  --namespace "AWS/ApiGateway" \
  --statistic Sum \
  --period 300 \
  --threshold 10 \
  --comparison-operator GreaterThanThreshold \
  --evaluation-periods 2 \
  --alarm-actions arn:aws:sns:us-east-1:xxx:alerts
```

## Cost Estimation

| Component | Estimated Monthly Cost |
|-----------|----------------------|
| Lambda | $50-200 (usage dependent) |
| Bedrock (Claude) | $200-1000 (query volume) |
| CloudFront | $10-50 |
| S3 | <$5 |
| Secrets Manager | <$5 |
| API Gateway | $10-50 |
| **Total** | **$300-1500** |

## Scaling Considerations

### Lambda Concurrency

Default: 1000 concurrent executions
Increase if needed:

```bash
aws lambda put-function-concurrency \
  --function-name illuminate-api \
  --reserved-concurrent-executions 2000
```

### API Gateway Throttling

Default: 10,000 requests/second
Configure per-stage throttling as needed.

### Bedrock Quotas

Check and request increases for:
- Tokens per minute
- Requests per minute

## Troubleshooting

### Lambda Timeout

Increase timeout in CDK or console (max 15 minutes).

### Cold Starts

Use provisioned concurrency for critical endpoints:

```bash
aws lambda put-provisioned-concurrency-config \
  --function-name illuminate-api \
  --qualifier prod \
  --provisioned-concurrent-executions 5
```

### Snowflake Connection Issues

1. Verify VPC endpoint configuration
2. Check security group rules
3. Validate credentials in Secrets Manager

## Rollback

To rollback a deployment:

```bash
cdk deploy --previous-stack
```

Or redeploy a specific version:

```bash
git checkout v1.0.0
cdk deploy
```
