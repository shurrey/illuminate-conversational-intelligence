# Illuminate Conversational Intelligence

Natural language access to Anthology Illuminate's educational data warehouse.

## Quick Start

```bash
# Backend
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # Add your ANTHROPIC_API_KEY
python main.py

# Frontend (new terminal)
cd frontend && npm install && npm run dev
```

Open http://localhost:3000

## Features

- Natural language queries ("What is the average GPA?")
- Automatic data visualization
- Multi-turn conversation support
- FERPA-compliant data access

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

The system uses a **Planner-Executor** pattern:
- **Planner Agent** (Claude Opus): Analyzes queries and creates execution plans
- **Orchestrator** (Claude Sonnet): Executes plans and coordinates specialist agents
- **SQL Agent**: Generates and executes SQL via Snowflake MCP
- **Analyst Agent**: Interprets data and identifies patterns
- **Writer Agent**: Crafts natural language responses
- **Validator Agent**: Ensures FERPA compliance

## Documentation

- [Quick Start Guide](docs/QUICKSTART.md)
- [Full Setup Guide](docs/SETUP.md)
- [Architecture Overview](docs/ARCHITECTURE.md)
- [API Reference](docs/API.md)
- [AWS Deployment](docs/DEPLOYMENT.md)
- [Security & Compliance](docs/SECURITY.md)

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

## Development

```bash
# Run tests
pip install -r requirements-dev.txt
pytest

# Format code
black agents/ main.py
ruff check --fix agents/ main.py

# Frontend tests
cd frontend && npm test
```

## Example Queries

- "What is the average GPA?"
- "Show enrollment by department"
- "Which courses have the most students?"
- "Chart that as a bar graph"

## Configuration

### Mock Mode (Development)

Set `ILLUMINATE_MOCK_MODE=true` in `.env` for development without Snowflake.

### Production Mode

1. Configure Snowflake credentials in `.env`
2. Set `ILLUMINATE_MOCK_MODE=false`
3. Obtain an Anthropic API key

## License

Proprietary - Anthology Inc.
