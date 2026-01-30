# Quick Start Guide

Get Illuminate CI running in 5 minutes.

## Prerequisites

- Python 3.11+
- Node.js 18+
- Anthropic API key (get from https://console.anthropic.com/)

## Setup

### 1. Clone and setup backend

```bash
git clone <repo>
cd illuminate-ici
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and add your Anthropic API key:

```bash
ANTHROPIC_API_KEY=sk-ant-api03-YOUR_KEY_HERE
```

### 3. Setup frontend

```bash
cd frontend
npm install
cd ..
```

### 4. Start services

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

### 5. Open browser

Navigate to http://localhost:3000

## Try It

Ask questions like:

- "What is the average GPA?"
- "How many courses are there?"
- "Show enrollment by department"
- "Which courses have the highest grades?"
- "Chart that" (after getting data)

## Mock Mode vs Real Mode

By default, the system runs in **mock mode** with sample data. This is perfect for development and testing.

To connect to real Snowflake data:

1. Configure Snowflake credentials in `.env`
2. Set `ILLUMINATE_MOCK_MODE=false`
3. Restart the backend

## Troubleshooting

### "ANTHROPIC_API_KEY not set"

Make sure you've copied `.env.example` to `.env` and added your API key.

### "Module not found"

Ensure your virtual environment is activated:
```bash
source venv/bin/activate
```

### Frontend won't connect

Check that the backend is running on port 8000:
```bash
curl http://localhost:8000/health
```

## Next Steps

- [Full Setup Guide](SETUP.md) - Detailed configuration options
- [Architecture Overview](ARCHITECTURE.md) - How the system works
- [API Reference](API.md) - REST API documentation
