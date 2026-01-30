# Illuminate Security Deployment Guide

## Production Security Implementation

This guide covers the security enhancements added to protect the Illuminate multi-agent system from malicious parties.

## Security Architecture

```
┌─────────────────────────────────────────────────────────┐
│                        Internet                          │
└─────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│                    WAF + CloudFront                      │
│  • Rate limiting (1000 req/min)                         │
│  • AWS Managed Rules (OWASP Top 10)                     │
│  • Known bad inputs protection                          │
└─────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│                  API Gateway + Cognito                   │
│  • JWT token validation                                  │
│  • CORS restricted to allowed origins                   │
│  • Request/response logging                             │
└─────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│                        VPC                               │
│  ┌─────────────────────────────────────────────────┐    │
│  │              Private Subnet                      │    │
│  │   Learning Agent ←→ Student Agent ←→ Telemetry  │    │
│  │              (internal only)                     │    │
│  └─────────────────────────────────────────────────┘    │
│                         ↑                                │
│  ┌─────────────────────────────────────────────────┐    │
│  │    Public Subnet                                 │    │
│  │         Orchestrator Agent                       │    │
│  └─────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│            Snowflake (via MCP + mTLS)                    │
└─────────────────────────────────────────────────────────┘
```

## Security Controls Implemented

### 1. Network Security

- **VPC Isolation**: All agents run in private subnets
- **Security Groups**: Restrict traffic to necessary ports only
- **NAT Gateways**: Controlled outbound internet access
- **Private Endpoints**: Direct AWS service access without internet

### 2. Authentication & Authorization

- **Cognito User Pool**: Centralized user management
- **JWT Tokens**: Stateless authentication
- **IAM Roles**: Least privilege access
- **Cedar Policies**: Fine-grained data access control

### 3. API Security

- **WAF Protection**: Rate limiting and OWASP rules
- **CORS Restrictions**: Limited to approved origins
- **Request Validation**: Input sanitization
- **Security Headers**: HSTS, CSP, X-Frame-Options

### 4. Agent Security

- **A2A Authentication**: Mutual TLS between agents
- **Signed Agent Cards**: Cryptographic verification
- **Network Isolation**: Private subnet deployment
- **Resource Policies**: Restricted AgentCore access

## Deployment Steps

### Prerequisites

1. **AWS Account Setup**
   ```bash
   # Configure AWS CLI
   aws configure
   
   # Verify permissions
   aws sts get-caller-identity
   ```

2. **Environment Variables**
   ```bash
   # Required for production
   export SNOWFLAKE_ACCOUNT="your-account"
   export DOMAIN_NAME="illuminate.anthology.com"
   export CERTIFICATE_ARN="arn:aws:acm:us-east-1:123456789012:certificate/..."
   export ALLOWED_ORIGINS="https://illuminate.anthology.com"
   export INSTITUTION_IDP_URL="https://idp.institution.edu"
   ```

### Development Deployment

```bash
cd infrastructure
npm install
npx cdk bootstrap
npx cdk deploy IlluminateDev
```

### Production Deployment

```bash
# Deploy production stack
npx cdk deploy IlluminateProd

# Configure Cognito users
aws cognito-idp admin-create-user \
  --user-pool-id us-east-1_XXXXXXXXX \
  --username analyst@institution.edu \
  --user-attributes Name=email,Value=analyst@institution.edu \
  --temporary-password TempPass123! \
  --message-action SUPPRESS
```

## Security Configuration

### 1. Cognito User Pool Setup

```bash
# Create user groups
aws cognito-idp create-group \
  --group-name Analyst \
  --user-pool-id us-east-1_XXXXXXXXX \
  --description "Data analysts with read-only access"

aws cognito-idp create-group \
  --group-name Administrator \
  --user-pool-id us-east-1_XXXXXXXXX \
  --description "System administrators with full access"

# Add user to group
aws cognito-idp admin-add-user-to-group \
  --user-pool-id us-east-1_XXXXXXXXX \
  --username analyst@institution.edu \
  --group-name Analyst
```

### 2. Cedar Policy Configuration

The system includes Cedar policies for data access control:

```cedar
// Allow analysts to query educational data
permit(
  principal in Role::"Analyst",
  action in [Action::"query", Action::"read"],
  resource in [Schema::"CDM_LMS", Schema::"CDM_SIS", Schema::"CDM_TLM"]
);

// Block access to PII columns
forbid(
  principal,
  action,
  resource in [Column::"SSN", Column::"STUDENT_SSN", Column::"CREDIT_CARD"]
);

// Allow administrators full access
permit(
  principal in Role::"Administrator",
  action,
  resource
);
```

### 3. WAF Rules Configuration

- **Rate Limiting**: 1000 requests per 5 minutes per IP
- **AWS Managed Rules**: Common Rule Set, Known Bad Inputs
- **Custom Rules**: Block requests without proper User-Agent
- **Geo Blocking**: Optional restriction to specific countries

### 4. Monitoring & Alerting

```bash
# CloudWatch alarms for security events
aws cloudwatch put-metric-alarm \
  --alarm-name "Illuminate-HighErrorRate" \
  --alarm-description "High error rate detected" \
  --metric-name 4XXError \
  --namespace AWS/ApiGateway \
  --statistic Sum \
  --period 300 \
  --threshold 50 \
  --comparison-operator GreaterThanThreshold
```

## Security Checklist

### Pre-Deployment

- [ ] AWS account has appropriate security policies
- [ ] IAM roles follow least privilege principle
- [ ] Secrets are stored in AWS Secrets Manager
- [ ] VPC and security groups are properly configured
- [ ] WAF rules are tested and validated

### Post-Deployment

- [ ] Cognito User Pool is configured with strong password policy
- [ ] Users are created with temporary passwords
- [ ] Agent cards are signed and verified
- [ ] API endpoints require authentication
- [ ] CORS is restricted to approved origins
- [ ] CloudWatch monitoring is active
- [ ] Security headers are present in responses

### Ongoing Security

- [ ] Regular security assessments
- [ ] User access reviews
- [ ] Log monitoring and analysis
- [ ] Dependency vulnerability scanning
- [ ] Incident response procedures

## Troubleshooting

### Authentication Issues

```bash
# Test Cognito authentication
aws cognito-idp admin-initiate-auth \
  --user-pool-id us-east-1_XXXXXXXXX \
  --client-id XXXXXXXXXXXXXXXXXXXXXXXXXX \
  --auth-flow ADMIN_NO_SRP_AUTH \
  --auth-parameters USERNAME=user@example.com,PASSWORD=password
```

### Network Connectivity

```bash
# Test VPC connectivity
aws ec2 describe-vpc-endpoints --filters Name=service-name,Values=com.amazonaws.us-east-1.bedrock

# Check security group rules
aws ec2 describe-security-groups --group-ids sg-xxxxxxxxx
```

### Agent Communication

```bash
# Test A2A connectivity
curl -H "Authorization: Bearer $JWT_TOKEN" \
  https://api.illuminate.anthology.com/.well-known/agent.json
```

## Security Contacts

- **Security Team**: security@anthology.com
- **DevOps Team**: devops@anthology.com
- **Emergency**: +1-800-XXX-XXXX

## Compliance

This deployment meets the following compliance requirements:

- **FERPA**: Educational data protection
- **SOC 2 Type II**: Security controls
- **GDPR**: Data privacy (where applicable)
- **CCPA**: California privacy requirements