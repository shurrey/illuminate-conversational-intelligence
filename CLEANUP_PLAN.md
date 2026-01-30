# Illuminate Conversational Intelligence - Cleanup & Documentation Plan

## Status: COMPLETE

All phases have been implemented:

- Phase 1: Security Fixes - DONE
  - Created .gitignore
  - Updated .env.example
- Phase 2: Code Cleanup - DONE
  - Simplified UI to single CDM_LMS
  - Removed student/telemetry agents
  - Removed dead code files
  - Cleaned up mock data
- Phase 3: Testing - DONE
  - Created test structure
  - Added unit tests for all agents
  - Added integration tests
  - Created pytest configuration
- Phase 4: Documentation - DONE
  - Updated README.md
  - Created QUICKSTART.md
  - Updated ARCHITECTURE.md
  - Created API.md
  - Created DEPLOYMENT.md
  - Created SECURITY.md
  - Updated SETUP.md
- Phase 5: Final Cleanup - DONE
  - Created Makefile
  - Created .pre-commit-config.yaml
  - Created requirements-dev.txt

## Executive Summary

This plan addresses code cleanup, testing, documentation, security, and deployment for the Illuminate Conversational Intelligence (ICI) system. The system has been recently refactored from a monolithic Learning Agent to a pipeline architecture (Planner → SQL → Analyst → Writer), but documentation and tests have not kept pace.

**Current State:**
- Backend: ~7,200 lines Python (multi-agent system)
- Frontend: ~2,700 lines TypeScript/React (chat UI)
- Tests: None (critical gap)
- Documentation: Outdated (references old architecture)
- .gitignore: Missing at project root
- Security: Credentials exposed in .env

**Target State:**
- Clean, simplified codebase focused on CDM_LMS only
- 80%+ test coverage
- Complete, accurate documentation
- Secure credential management
- AWS deployment ready

---

## Phase 1: Critical Security Fixes (Day 1)

### 1.1 Remove Exposed Credentials

**Issue:** `.env` contains real API keys and passwords committed to the repo.

**Actions:**
```bash
# 1. Create .env.example with placeholders
# 2. Remove credentials from .env
# 3. Add .env to .gitignore
# 4. Consider removing from git history (git filter-branch)
```

**Files to create:**
- `.env.example` - Template with placeholder values
- `.gitignore` - Comprehensive ignore file

### 1.2 Create Root .gitignore

```gitignore
# Environment & Secrets
.env
.env.local
.env.*.local
*.pem
*.key

# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
venv/
.venv/
ENV/
*.egg-info/
dist/
build/
.eggs/
.pytest_cache/
.coverage
htmlcov/
.mypy_cache/
.ruff_cache/

# Node/Frontend
node_modules/
frontend/node_modules/
frontend/dist/
frontend/.vite/
*.log
npm-debug.log*

# IDE
.vscode/
.idea/
*.swp
*.swo
.DS_Store

# Infrastructure
infrastructure/cdk.out/
infrastructure/node_modules/

# Temporary
tmp/
temp/
*.tmp
scratchpad/
```

---

## Phase 2: Code Cleanup & Simplification (Days 2-4)

### 2.1 Remove Unused CDM References (UI Simplification)

**Current State:** UI shows 4 data domains (All, Learning, Student, Engagement)
**Target State:** UI shows only CDM_LMS (single schema focus)

**Files to modify:**

#### `frontend/src/components/layout/Sidebar.tsx`
- Remove Student (SIS) domain option
- Remove Engagement (TLM) domain option
- Remove "All Data" cross-domain option
- Simplify to single "Learning Data" focus
- Update footer to show only "CDM_LMS • Blackboard Learn"

#### `frontend/src/services/agentClient.ts`
- Remove domain routing logic (not needed with single schema)
- Simplify API calls

### 2.2 Remove Unused Backend Agents

**Files to delete:**
```
agents/student/          # Incomplete CDM_SIS agent
agents/telemetry/        # Incomplete CDM_TLM agent
```

**Files to update:**
- `agents/__init__.py` - Remove student/telemetry exports
- `agents/shared/models.py` - Remove unused AgentType enum values
- `agents/orchestrator/agent.py` - Remove multi-domain routing

### 2.3 Clean Up Shared Utilities

**Files to review/simplify:**
- `agents/shared/snowflake_mcp.py` - Remove CDM_SIS, CDM_TLM mock data
- `agents/shared/schema_cache.py` - Remove multi-schema logic
- `agents/shared/artifact_utils.py` - Verify usage, remove if minimal

### 2.4 Remove Dead Code

**Files to delete:**
```
agents/orchestrator/api_handler.py      # Duplicate/unused
agents/orchestrator/secure_api_handler.py  # Not integrated
```

**Code patterns to remove:**
- Old Learning Agent references in documentation
- Commented-out code blocks
- Unused imports (use `ruff` to detect)

### 2.5 Standardize Code Style

**Actions:**
```bash
# Format Python code
pip install black ruff
black agents/ main.py
ruff check --fix agents/ main.py

# Format TypeScript code
cd frontend
npm run lint -- --fix
npx prettier --write src/
```

---

## Phase 3: Testing (Days 5-10)

### 3.1 Backend Test Structure

Create test directory structure:
```
tests/
├── __init__.py
├── conftest.py              # Pytest fixtures
├── unit/
│   ├── __init__.py
│   ├── test_planner.py      # Planner agent tests
│   ├── test_sql_agent.py    # SQL agent tests
│   ├── test_analyst.py      # Analyst agent tests
│   ├── test_writer.py       # Writer agent tests
│   ├── test_validator.py    # Validator agent tests
│   ├── test_visualization.py # Visualization agent tests
│   └── test_models.py       # Data model tests
├── integration/
│   ├── __init__.py
│   ├── test_pipeline.py     # Full pipeline tests
│   ├── test_orchestrator.py # Orchestrator integration
│   └── test_streaming.py    # Streaming response tests
└── fixtures/
    ├── sample_queries.json  # Test queries
    └── expected_plans.json  # Expected execution plans
```

### 3.2 Test Configuration

**pytest.ini:**
```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_functions = test_*
asyncio_mode = auto
addopts = -v --cov=agents --cov-report=html --cov-report=term-missing
filterwarnings =
    ignore::DeprecationWarning
```

**requirements-dev.txt:**
```
pytest>=7.0
pytest-asyncio>=0.21
pytest-cov>=4.0
pytest-mock>=3.10
httpx>=0.24
respx>=0.20
```

### 3.3 Unit Tests to Create

#### `tests/unit/test_planner.py`
```python
# Test cases:
- test_simple_query_returns_simple_path()
- test_analytical_query_returns_standard_path()
- test_complex_query_returns_deep_analysis_path()
- test_visualization_request_returns_viz_only_path()
- test_plan_includes_correct_agents()
- test_opus_selected_for_complex_analysis()
- test_context_awareness_for_followups()
```

#### `tests/unit/test_sql_agent.py`
```python
# Test cases:
- test_simple_count_query()
- test_aggregate_query_with_group_by()
- test_join_query_across_tables()
- test_ferpa_columns_excluded()
- test_sql_injection_prevented()
- test_query_timeout_handling()
```

#### `tests/unit/test_analyst.py`
```python
# Test cases:
- test_identifies_key_insights()
- test_computes_statistics()
- test_suggests_visualization_type()
- test_handles_empty_data()
- test_model_selection_sonnet_vs_opus()
```

#### `tests/unit/test_writer.py`
```python
# Test cases:
- test_creates_natural_language_response()
- test_includes_data_table_artifact()
- test_extracts_followup_questions()
- test_handles_large_datasets()
```

#### `tests/unit/test_validator.py`
```python
# Test cases:
- test_passes_valid_response()
- test_blocks_pii_exposure()
- test_detects_hallucination()
- test_validates_sql_safety()
- test_confidence_scoring()
```

### 3.4 Integration Tests

#### `tests/integration/test_pipeline.py`
```python
# Test cases:
- test_simple_query_full_pipeline()
- test_standard_query_full_pipeline()
- test_deep_analysis_full_pipeline()
- test_visualization_followup()
- test_error_recovery()
- test_context_preservation()
```

### 3.5 Frontend Tests

**Frontend test structure:**
```
frontend/src/
├── __tests__/
│   ├── components/
│   │   ├── ChatContainer.test.tsx
│   │   ├── MessageBubble.test.tsx
│   │   ├── DataTable.test.tsx
│   │   └── ChartRenderer.test.tsx
│   ├── hooks/
│   │   └── useChat.test.ts
│   └── services/
│       └── agentClient.test.ts
```

**Install test dependencies:**
```bash
cd frontend
npm install -D vitest @testing-library/react @testing-library/jest-dom @testing-library/user-event jsdom
```

**vitest.config.ts:**
```typescript
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/__tests__/setup.ts',
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html'],
      exclude: ['node_modules/', 'src/__tests__/']
    }
  }
})
```

---

## Phase 4: Documentation (Days 11-15)

### 4.1 Documentation Structure

```
docs/
├── README.md                    # Project overview (updated)
├── QUICKSTART.md               # 5-minute getting started
├── SETUP.md                    # Full setup guide (updated)
├── ARCHITECTURE.md             # System architecture (updated)
├── API.md                      # REST API reference
├── DEPLOYMENT.md               # AWS deployment guide
├── SECURITY.md                 # Security, compliance, privacy
├── CONTRIBUTING.md             # Development guidelines
├── TROUBLESHOOTING.md          # Common issues & solutions
└── CHANGELOG.md                # Version history
```

### 4.2 Root README.md Update

```markdown
# Illuminate Conversational Intelligence

Natural language access to Anthology Illuminate's educational data warehouse.

## Quick Start

```bash
# Backend
source venv/bin/activate
python main.py

# Frontend (new terminal)
cd frontend && npm run dev
```

Open http://localhost:3000

## Features

- Natural language queries ("What is the average GPA?")
- Automatic data visualization
- Multi-turn conversation support
- FERPA-compliant data access

## Documentation

- [Quick Start Guide](docs/QUICKSTART.md)
- [Full Setup Guide](docs/SETUP.md)
- [Architecture Overview](docs/ARCHITECTURE.md)
- [API Reference](docs/API.md)
- [AWS Deployment](docs/DEPLOYMENT.md)
- [Security & Compliance](docs/SECURITY.md)

## Architecture

```
User Query → Planner (Opus) → Orchestrator
                               ├── SQL Agent
                               ├── Analyst Agent
                               ├── Writer Agent
                               ├── Visualization Agent
                               └── Validator Agent
                               → Response
```

## License

Proprietary - Anthology Inc.
```

### 4.3 QUICKSTART.md (New)

```markdown
# Quick Start Guide

Get running in 5 minutes.

## Prerequisites

- Python 3.11+
- Node.js 18+
- Anthropic API key

## Setup

1. **Clone and setup backend:**
   ```bash
   git clone <repo>
   cd illuminate-ici
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Configure environment:**
   ```bash
   cp .env.example .env
   # Edit .env and add your ANTHROPIC_API_KEY
   ```

3. **Setup frontend:**
   ```bash
   cd frontend
   npm install
   cd ..
   ```

4. **Start services:**
   ```bash
   # Terminal 1: Backend
   python main.py

   # Terminal 2: Frontend
   cd frontend && npm run dev
   ```

5. **Open browser:** http://localhost:3000

## Try It

Ask questions like:
- "What is the average GPA?"
- "Show enrollment by department"
- "Which courses have the most students?"
```

### 4.4 ARCHITECTURE.md Update

Update to reflect new pipeline architecture:

```markdown
# System Architecture

## Agent Pipeline

The system uses a **Planner-Executor** pattern:

```
User Query
    ↓
PLANNER (Claude Opus)
    │ Creates ExecutionPlan
    ↓
ORCHESTRATOR (Claude Sonnet)
    │ Executes plan, coordinates agents
    │
    ├──→ SQL Agent ──────→ Query data
    │         ↓
    ├──→ Analyst Agent ──→ Interpret results
    │         ↓
    ├──→ Writer Agent ───→ Craft response
    │         ↓
    ├──→ Visualization ──→ Generate charts
    │         ↓
    └──→ Validator ──────→ FERPA compliance
    │
    ↓
Final Response
```

## Pipeline Paths

| Path | When Used | Agents |
|------|-----------|--------|
| SIMPLE | Basic counts, lookups | SQL only |
| STANDARD | Analytical queries | SQL → Analyst → Writer |
| DEEP_ANALYSIS | Complex patterns | SQL → Analyst(Opus) → Writer |
| VIZ_ONLY | "Chart that" | Visualization only |

## Agent Responsibilities

| Agent | Model | Responsibility |
|-------|-------|----------------|
| Planner | Opus | Query analysis, plan creation |
| Orchestrator | Sonnet | Plan execution, coordination |
| SQL | Sonnet | SQL generation, execution |
| Analyst | Sonnet/Opus | Data interpretation |
| Writer | Sonnet | Response composition |
| Visualization | N/A | Chart generation |
| Validator | Sonnet | FERPA compliance |
```

### 4.5 API.md (New)

```markdown
# API Reference

## Base URL

```
http://localhost:8000
```

## Authentication

Development mode uses API key authentication:

```bash
curl -H "Authorization: Bearer dev-key-123" ...
```

## Endpoints

### POST /api/chat

Send a query and receive a response.

**Request:**
```json
{
  "message": "What is the average GPA?",
  "context_id": "optional-session-id"
}
```

**Response:**
```json
{
  "text": "The average GPA is 3.42...",
  "artifacts": [...],
  "context_id": "session-123",
  "suggested_followups": [...]
}
```

### POST /api/chat/stream

Send a query with streaming response.

**Request:** Same as `/api/chat`

**Response:** Server-Sent Events (SSE)
```
event: status
data: {"message": "Analyzing query..."}

event: thinking
data: {"agent": "planner", "content": "Planning execution..."}

event: complete
data: {"text": "...", "artifacts": [...]}
```

### GET /health

Health check endpoint.

**Response:**
```json
{"status": "healthy", "version": "0.1.0"}
```
```

### 4.6 DEPLOYMENT.md (New)

```markdown
# AWS Deployment Guide

## Prerequisites

- AWS CLI v2 configured
- AWS CDK v2 installed
- AWS account with Bedrock access
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

```bash
# Snowflake credentials
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

# Anthropic API key
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

### 4. Deploy Frontend

```bash
cd frontend
npm run build

# Upload to S3
aws s3 sync dist/ s3://illuminate-frontend-bucket/
```

### 5. Configure DNS (Optional)

Point your domain to CloudFront distribution.

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
BEDROCK_MODEL_WORKER=anthropic.claude-opus-4-20250514-v1:0

# Secrets (retrieved from Secrets Manager)
SNOWFLAKE_SECRET_ARN=arn:aws:secretsmanager:...
ANTHROPIC_SECRET_ARN=arn:aws:secretsmanager:...
```

## Monitoring

### CloudWatch Dashboards

- API latency and errors
- Lambda invocations
- Bedrock token usage

### Alerts

Configure alerts for:
- Error rate > 5%
- P99 latency > 30s
- Daily cost > $X

## Cost Estimation

| Component | Estimated Monthly Cost |
|-----------|----------------------|
| Lambda | $50-200 (usage dependent) |
| Bedrock (Claude) | $200-1000 (query volume) |
| CloudFront | $10-50 |
| S3 | <$5 |
| Secrets Manager | <$5 |
| **Total** | **$300-1500** |
```

### 4.7 SECURITY.md (New)

```markdown
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

1. **Query-Time Validation**
   - Validator Agent checks all responses before returning
   - Blocks queries that would expose individual student data
   - Requires minimum aggregation of 5 students per group

2. **SQL Generation Safeguards**
   - PERSON_ID never returned in final results
   - Student names, emails, SSNs blocked from SELECT
   - Automatic GROUP BY enforcement for student data

3. **Response Filtering**
   - LLM responses scanned for PII patterns
   - Numerical precision limited to prevent re-identification

### Example: Compliant vs Non-Compliant

**Non-Compliant Query (Blocked):**
```
"Show me John Smith's grades"
→ BLOCKED: Individual student data request
```

**Compliant Query (Allowed):**
```
"Show average grades by department"
→ ALLOWED: Aggregate data, no individual identification
```

## Authentication & Authorization

### Current Implementation (Development)

- API key authentication (dev-key-123)
- Suitable for development/demo only

### Production Requirements

1. **SSO Integration**
   - SAML 2.0 or OIDC with institutional IdP
   - AWS Cognito as identity broker

2. **Role-Based Access**
   ```
   Roles:
   - admin: Full access, system configuration
   - analyst: Query access, data export
   - viewer: Query access only
   ```

3. **Audit Logging**
   - All queries logged with user identity
   - Retention: 7 years (FERPA requirement)

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
- Automatic rotation enabled
- Lambda accesses secrets at runtime only
- Never stored in code or environment variables

### Data Encryption

| Data State | Encryption |
|------------|------------|
| In Transit | TLS 1.3 |
| At Rest (S3) | AES-256 (SSE-S3) |
| At Rest (Snowflake) | AES-256 |
| In Memory | Not applicable |

## Incident Response

### Data Breach Procedure

1. **Identify**: Detect unauthorized access
2. **Contain**: Revoke access, isolate systems
3. **Assess**: Determine scope and impact
4. **Notify**: Inform affected parties (72 hours)
5. **Remediate**: Fix vulnerabilities
6. **Document**: Post-incident report

### Contact

Security issues: security@anthology.com

## Compliance Checklist

### Pre-Production

- [ ] FERPA training for all developers
- [ ] Penetration testing completed
- [ ] Security review by InfoSec team
- [ ] Data handling agreement with institution
- [ ] Audit logging configured
- [ ] Incident response plan documented

### Ongoing

- [ ] Quarterly access reviews
- [ ] Annual penetration testing
- [ ] FERPA compliance audit (annual)
- [ ] Security patch management (monthly)

## Privacy Considerations

### Data Minimization

- Only query data necessary for the question
- Don't store conversation history beyond session
- No persistent storage of query results

### User Consent

- Users must accept terms of service
- Clear explanation of data usage
- Opt-out available for analytics

### Data Retention

| Data Type | Retention |
|-----------|-----------|
| Query logs | 7 years (audit) |
| Session data | 24 hours |
| Exported data | User responsibility |
```

---

## Phase 5: Final Cleanup (Days 16-18)

### 5.1 Update Package Files

**requirements.txt** (add dev dependencies section):
```
# Core
fastapi>=0.100
uvicorn>=0.23
httpx>=0.24
pydantic>=2.0

# Agents
strands-agents>=0.1
anthropic>=0.25
mcp>=0.1

# Development (install with: pip install -r requirements-dev.txt)
# pytest>=7.0
# pytest-asyncio>=0.21
# pytest-cov>=4.0
# black>=23.0
# ruff>=0.1
```

**package.json** (frontend) - add test scripts:
```json
{
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "preview": "vite preview",
    "lint": "eslint src --ext ts,tsx",
    "format": "prettier --write src/",
    "test": "vitest",
    "test:coverage": "vitest --coverage"
  }
}
```

### 5.2 Add Pre-commit Hooks

**.pre-commit-config.yaml:**
```yaml
repos:
  - repo: https://github.com/psf/black
    rev: 23.12.1
    hooks:
      - id: black
        language_version: python3.11

  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.1.9
    hooks:
      - id: ruff
        args: [--fix]

  - repo: https://github.com/pre-commit/mirrors-prettier
    rev: v3.1.0
    hooks:
      - id: prettier
        files: \.(ts|tsx|js|jsx|json|md)$
```

### 5.3 Create Makefile for Common Tasks

**Makefile:**
```makefile
.PHONY: install test lint format run clean

install:
	python -m venv venv
	. venv/bin/activate && pip install -r requirements.txt
	cd frontend && npm install

test:
	. venv/bin/activate && pytest
	cd frontend && npm test

lint:
	. venv/bin/activate && ruff check agents/ main.py
	cd frontend && npm run lint

format:
	. venv/bin/activate && black agents/ main.py
	cd frontend && npm run format

run:
	. venv/bin/activate && python main.py &
	cd frontend && npm run dev

clean:
	rm -rf venv/ __pycache__/ .pytest_cache/ .coverage htmlcov/
	rm -rf frontend/node_modules/ frontend/dist/
```

---

## Implementation Timeline

| Phase | Duration | Deliverables |
|-------|----------|--------------|
| 1. Security Fixes | Day 1 | .gitignore, .env.example, credentials removed |
| 2. Code Cleanup | Days 2-4 | Simplified UI, removed unused agents |
| 3. Testing | Days 5-10 | 80%+ test coverage |
| 4. Documentation | Days 11-15 | Complete docs suite |
| 5. Final Cleanup | Days 16-18 | Package files, pre-commit, Makefile |

**Total: ~3 weeks**

---

## Success Criteria

1. **Security**
   - No credentials in repository
   - .gitignore comprehensive
   - Security documentation complete

2. **Code Quality**
   - All unused code removed
   - Lint passes with no errors
   - Single CDM focus in UI

3. **Testing**
   - pytest runs successfully
   - 80%+ backend coverage
   - Frontend tests pass

4. **Documentation**
   - All docs up-to-date
   - AWS deployment documented
   - Security/compliance documented
   - Can setup from scratch using docs

5. **Usability**
   - `make install && make run` works
   - `make test` passes
   - New developer can onboard in <1 hour

---

## Appendix: File Inventory

### Files to Create
- `.gitignore`
- `.env.example`
- `pytest.ini`
- `requirements-dev.txt`
- `Makefile`
- `.pre-commit-config.yaml`
- `docs/QUICKSTART.md`
- `docs/API.md`
- `docs/DEPLOYMENT.md`
- `docs/SECURITY.md`
- `docs/CONTRIBUTING.md`
- `docs/TROUBLESHOOTING.md`
- `docs/CHANGELOG.md`
- `tests/` (entire directory)
- `frontend/src/__tests__/` (entire directory)
- `frontend/vitest.config.ts`

### Files to Update
- `README.md`
- `docs/SETUP.md`
- `docs/ARCHITECTURE.md`
- `frontend/src/components/layout/Sidebar.tsx`
- `agents/__init__.py`
- `agents/shared/models.py`
- `agents/shared/snowflake_mcp.py`
- `requirements.txt`
- `frontend/package.json`

### Files to Delete
- `agents/student/` (entire directory)
- `agents/telemetry/` (entire directory)
- `agents/orchestrator/api_handler.py`
- `agents/orchestrator/secure_api_handler.py`
- `.env` (recreate from .env.example)
