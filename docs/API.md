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

Valid API keys are configured in `.env` via `VALID_API_KEYS`.

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
  "text": "The average GPA is 3.42. This is calculated across all courses...",
  "artifacts": [
    {
      "id": "artifact-123",
      "type": "table",
      "data": {
        "rows": [{"avg_gpa": 3.42}],
        "columns": ["avg_gpa"]
      },
      "title": "Average GPA"
    }
  ],
  "context_id": "session-123",
  "suggested_followups": [
    "Show GPA by department",
    "What are the trends over time?"
  ]
}
```

### POST /api/chat/stream

Send a query with streaming response (Server-Sent Events).

**Request:** Same as `/api/chat`

**Response:** SSE stream

```
event: status
data: {"message": "Analyzing query..."}

event: thinking
data: {"agent": "planner", "content": "Planning execution..."}

event: planning
data: {"agent": "planner", "plan": {...}}

event: sql_complete
data: {"row_count": 5, "execution_time_ms": 150}

event: analysis_complete
data: {"agent": "analyst"}

event: complete
data: {"text": "...", "artifacts": [...], "suggested_followups": [...]}
```

### GET /api/conversations/{context_id}

Get conversation history for a session.

**Response:**
```json
{
  "id": "session-123",
  "messages": [
    {
      "id": "msg-1",
      "role": "user",
      "parts": [{"type": "text", "content": "What is the average GPA?"}],
      "artifacts": [],
      "timestamp": "2024-01-15T10:30:00Z"
    },
    {
      "id": "msg-2",
      "role": "assistant",
      "parts": [{"type": "text", "content": "The average GPA is 3.42..."}],
      "artifacts": [...],
      "timestamp": "2024-01-15T10:30:05Z"
    }
  ]
}
```

### DELETE /api/conversations/{context_id}

Clear conversation history for a session.

**Response:**
```json
{"status": "cleared"}
```

### GET /health

Health check endpoint.

**Response:**
```json
{
  "status": "healthy",
  "version": "0.1.0",
  "mock_mode": true
}
```

## Artifact Types

### Table

```json
{
  "type": "table",
  "data": {
    "rows": [{"col1": "value1", "col2": "value2"}],
    "columns": ["col1", "col2"]
  },
  "title": "Results"
}
```

### Chart

```json
{
  "type": "chart",
  "data": {
    "chart_type": "bar",
    "title": "Enrollment by Department",
    "x_axis": "department",
    "y_axis": "count",
    "data": [{"department": "CS", "count": 270}]
  }
}
```

### Text

```json
{
  "type": "text",
  "data": "Summary text content",
  "title": "Summary"
}
```

### Error

```json
{
  "type": "error",
  "data": "Error message",
  "title": "Error"
}
```

## Error Responses

### 400 Bad Request

```json
{
  "detail": "Message is required"
}
```

### 401 Unauthorized

```json
{
  "detail": "Invalid API key"
}
```

### 500 Internal Server Error

```json
{
  "detail": "An error occurred processing your request"
}
```

## Rate Limits

Development mode has no rate limits. Production deployments should configure appropriate limits based on LLM costs and infrastructure capacity.

## CORS

The API allows CORS from `http://localhost:3000` for development. Production deployments should configure appropriate origins.
