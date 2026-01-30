# Security, Compliance & Privacy

## Overview

Illuminate Conversational Intelligence handles sensitive educational data and must comply with FERPA regulations.

## Data Classification

| Data Type | Classification | Handling |
|-----------|---------------|----------|
| Aggregate statistics | Public | Can display freely |
| Course information | Internal | Display with context |
| Student grades | Confidential | Aggregated only, min 5 students |
| Student PII | Restricted | Never expose |

## FERPA Compliance

### What We Protect

FERPA (Family Educational Rights and Privacy Act) protects:
- Student names and contact information
- Social Security Numbers
- Student IDs (internal identifiers)
- Individual grades and academic records
- Enrollment and attendance records

### How We Protect It

#### 1. Query-Time Validation

The Validator Agent checks all responses before returning:
- Blocks queries that would expose individual student data
- Requires minimum aggregation of 5 students per group
- Scans for PII patterns in response text

#### 2. SQL Generation Safeguards

The SQL Agent follows these rules:
- PERSON_ID never returned in final results
- Student names, emails, SSNs blocked from SELECT
- Automatic GROUP BY enforcement for student data
- Query complexity limits to prevent data mining

#### 3. Response Filtering

Post-processing ensures:
- LLM responses scanned for PII patterns
- Numerical precision limited to prevent re-identification
- Individual identifiers redacted

### Example: Compliant vs Non-Compliant

**Non-Compliant Query (Blocked):**
```
User: "Show me John Smith's grades"
System: I cannot display individual student grades. This would violate FERPA.
        Try asking for aggregate data like "What is the average GPA by course?"
```

**Compliant Query (Allowed):**
```
User: "Show average grades by department"
System: Here are the average grades by department:
        - Computer Science: 3.5
        - Mathematics: 3.2
        - English: 3.7
```

## Authentication & Authorization

### Current Implementation (Development)

- API key authentication (`dev-key-123`)
- Suitable for development/demo only

### Production Requirements

#### 1. SSO Integration

Integrate with institutional identity providers:
- SAML 2.0 or OIDC
- AWS Cognito as identity broker
- Support for MFA

#### 2. Role-Based Access Control

```
Roles:
- admin: Full access, system configuration
- analyst: Query access, data export
- viewer: Query access only, no export
```

#### 3. Audit Logging

All queries logged with:
- User identity
- Timestamp
- Query text
- Response (redacted)
- Execution metadata

Retention: 7 years (FERPA requirement)

## Infrastructure Security

### Network Security

```
┌─────────────────────────────────────────────┐
│              Public Internet                 │
└─────────────────────┬───────────────────────┘
                      │ HTTPS only
                      ▼
┌─────────────────────────────────────────────┐
│              CloudFront (WAF)               │
│         - Rate limiting                      │
│         - DDoS protection                    │
│         - Geographic restrictions            │
└─────────────────────┬───────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────┐
│              VPC (Private)                   │
│  ┌─────────────┐    ┌─────────────┐        │
│  │   Lambda    │◀──▶│  Bedrock    │        │
│  └─────────────┘    └─────────────┘        │
│         │                                    │
│         ▼                                    │
│  ┌─────────────────────────────────┐        │
│  │    VPC Endpoint (Snowflake)     │        │
│  └─────────────────────────────────┘        │
└─────────────────────────────────────────────┘
```

### Secrets Management

- All credentials stored in AWS Secrets Manager
- Automatic rotation enabled (90-day cycle)
- Lambda accesses secrets at runtime only
- Never stored in code or environment variables
- Least privilege IAM policies

### Data Encryption

| Data State | Encryption |
|------------|------------|
| In Transit | TLS 1.3 |
| At Rest (S3) | AES-256 (SSE-S3) |
| At Rest (Snowflake) | AES-256 |
| In Memory | Not applicable |

## Incident Response

### Data Breach Procedure

1. **Identify**: Detect unauthorized access via CloudWatch alerts
2. **Contain**: Revoke access, isolate affected systems
3. **Assess**: Determine scope and affected data
4. **Notify**: Inform affected parties within 72 hours
5. **Remediate**: Fix vulnerabilities, update credentials
6. **Document**: Complete post-incident report

### Security Contact

Report security issues to: security@anthology.com

## Compliance Checklist

### Pre-Production

- [ ] FERPA training for all developers
- [ ] Penetration testing completed
- [ ] Security review by InfoSec team
- [ ] Data handling agreement with institution
- [ ] Audit logging configured and tested
- [ ] Incident response plan documented

### Ongoing

- [ ] Quarterly access reviews
- [ ] Annual penetration testing
- [ ] FERPA compliance audit (annual)
- [ ] Security patch management (monthly)
- [ ] Credential rotation verification (quarterly)

## Privacy Considerations

### Data Minimization

- Only query data necessary for the question
- Don't store conversation history beyond session
- No persistent storage of query results
- Automatic session expiry after 24 hours

### User Consent

- Users must accept terms of service
- Clear explanation of data usage
- Opt-out available for analytics

### Data Retention

| Data Type | Retention |
|-----------|-----------|
| Query logs | 7 years (FERPA audit) |
| Session data | 24 hours |
| Exported data | User responsibility |
| Error logs | 90 days |

## Security Best Practices for Developers

1. **Never log sensitive data** - Use structured logging without PII
2. **Validate all inputs** - SQL injection, XSS prevention
3. **Use parameterized queries** - Never concatenate SQL
4. **Follow least privilege** - Request minimal permissions
5. **Keep dependencies updated** - Regular security patches
6. **Review before merge** - Security-focused code review
