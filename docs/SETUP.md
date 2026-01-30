# Full Setup Guide

Complete setup instructions for Illuminate Conversational Intelligence.

## Prerequisites

| Software | Version | Purpose |
|----------|---------|---------|
| Python | 3.11+ | Backend runtime |
| Node.js | 18+ | Frontend build |
| npm | 9+ | Package management |

### Check Prerequisites

```bash
python3 --version  # Should be 3.11+
node --version     # Should be 18+
npm --version      # Should be 9+
```

## Installation

### Step 1: Clone Repository

```bash
git clone <repo-url>
cd illuminate-ici
```

### Step 2: Set Up Python Backend

```bash
# Create virtual environment
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate  # macOS/Linux
# OR
venv\Scripts\activate     # Windows

# Install dependencies
pip install -r requirements.txt
```

### Step 3: Set Up Frontend

```bash
cd frontend
npm install
cd ..
```

### Step 4: Configure Environment

```bash
cp .env.example .env
```

Edit `.env` and add your Anthropic API key:

```bash
ANTHROPIC_API_KEY=sk-ant-api03-YOUR_KEY_HERE
```

### Quick Install with Makefile

```bash
make install      # Install production dependencies
make install-dev  # Install with test tools
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | (required) | Anthropic API key |
| `ILLUMINATE_MOCK_MODE` | `true` | Use mock data for development |
| `PORT` | `8000` | Backend API port |
| `LOG_LEVEL` | `INFO` | Logging level |

### Snowflake Configuration (Production)

When `ILLUMINATE_MOCK_MODE=false`:

```bash
SNOWFLAKE_ACCOUNT=your-account
SNOWFLAKE_USER=your-user
SNOWFLAKE_PASSWORD=your-password
SNOWFLAKE_WAREHOUSE=your-warehouse
SNOWFLAKE_DATABASE=your-database
SNOWFLAKE_ROLE=your-role
```

### LLM Model Configuration

```bash
# For local development (Anthropic API)
MODEL_ORCHESTRATOR=claude-sonnet-4-20250514
MODEL_VALIDATOR=claude-sonnet-4-20250514
MODEL_WORKER=claude-opus-4-20250514

# For AWS Bedrock (production)
USE_BEDROCK=true
BEDROCK_MODEL_ORCHESTRATOR=anthropic.claude-sonnet-4-20250514-v1:0
BEDROCK_MODEL_WORKER=anthropic.claude-opus-4-20250514-v1:0
```

## Running the System

### Development Mode

**Terminal 1: Backend**
```bash
source venv/bin/activate
python main.py
```

**Terminal 2: Frontend**
```bash
cd frontend
npm run dev
```

### Using Makefile

```bash
make run  # Starts both backend and frontend
```

### Verify Services

| Service | URL | Expected |
|---------|-----|----------|
| Frontend | http://localhost:3000 | Chat interface |
| Backend API | http://localhost:8000 | JSON response |
| Health Check | http://localhost:8000/health | `{"status":"healthy"}` |
| API Docs | http://localhost:8000/docs | Swagger UI |

## Running Tests

### Backend Tests

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

### Frontend Tests

```bash
cd frontend
npm test
```

### All Tests

```bash
make test
```

## Code Quality

### Linting

```bash
make lint
```

### Formatting

```bash
make format
```

### Pre-commit Hooks

```bash
pip install pre-commit
pre-commit install
```

## Troubleshooting

### "ANTHROPIC_API_KEY not set"

Make sure `.env` exists and contains your API key:
```bash
cp .env.example .env
# Edit .env and add ANTHROPIC_API_KEY
```

### "ModuleNotFoundError"

Ensure virtual environment is activated:
```bash
source venv/bin/activate
```

### "Port already in use"

```bash
lsof -i :8000
kill -9 <PID>
```

### Frontend can't connect to API

1. Verify backend is running: `curl http://localhost:8000/health`
2. Check `frontend/.env` has correct `VITE_API_URL`

### Debug Logging

```bash
LOG_LEVEL=DEBUG python main.py
```

## Project Structure

```
├── agents/                 # Multi-agent system
│   ├── orchestrator/       # Central coordinator
│   ├── planner/            # Query planning (Opus)
│   ├── sql/                # SQL generation
│   ├── analyst/            # Data interpretation
│   ├── writer/             # Response crafting
│   ├── visualization/      # Charts & exports
│   ├── validator/          # FERPA compliance
│   └── shared/             # Shared utilities
├── frontend/               # React chat UI
├── tests/                  # Test suite
├── docs/                   # Documentation
├── config/                 # Configuration
└── infrastructure/         # AWS CDK deployment
```

## Next Steps

- [Quick Start](QUICKSTART.md) - Get running in 5 minutes
- [Architecture](ARCHITECTURE.md) - How the system works
- [API Reference](API.md) - REST API documentation
- [Deployment](DEPLOYMENT.md) - AWS deployment guide
- [Security](SECURITY.md) - Security and compliance
