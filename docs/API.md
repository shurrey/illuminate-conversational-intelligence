# Illuminate API Reference

The Illuminate API is served by a Lambda proxy (`lambda_handler.py`) built with FastAPI. All traffic is routed through CloudFront:

- `/*` routes to S3 (frontend static assets)
- `/api/*` and `/health` route to the Lambda Function URL

## Authentication

All endpoints except `GET /health` require a valid **Amazon Cognito JWT token** passed in the `Authorization` header:

```
Authorization: Bearer <cognito_jwt_token>
```

Tokens are issued by the Cognito User Pool (`illuminate-users-dev`).

## CORS

CORS is configured to allow requests from the CloudFront distribution domain and `localhost` development origins.

---

## Endpoints

### GET /health

Health check endpoint. No authentication required.

**Response** `200 OK`

```json
{
  "status": "healthy",
  "version": "0.2.0",
  "mode": "proxy"
}
```

---

### POST /api/chat

Non-streaming chat request. Sends a message to the orchestrator agent and returns the complete response once all agents have finished processing.

**Headers**

| Header          | Value                        | Required |
| --------------- | ---------------------------- | -------- |
| Authorization   | `Bearer <cognito_jwt_token>` | Yes      |
| Content-Type    | `application/json`           | Yes      |

**Request Body** (A2A JSON-RPC format)

```json
{
  "jsonrpc": "2.0",
  "method": "message/send",
  "params": {
    "message": {
      "role": "user",
      "parts": [
        {
          "type": "text",
          "text": "your question here"
        }
      ],
      "messageId": "<uuid>",
      "contextId": "<uuid>"
    }
  },
  "id": "<uuid>"
}
```

| Field                          | Type   | Description                                      |
| ------------------------------ | ------ | ------------------------------------------------ |
| `params.message.role`          | string | Always `"user"` for client-sent messages.        |
| `params.message.parts`         | array  | Array of message parts (currently text only).    |
| `params.message.parts[].type`  | string | Part type. Use `"text"`.                         |
| `params.message.parts[].text`  | string | The user's question or instruction.              |
| `params.message.messageId`     | string | Unique UUID identifying this message.            |
| `params.message.contextId`     | string | UUID for the conversation context. Reuse across messages in the same conversation. |
| `id`                           | string | JSON-RPC request identifier (UUID).              |

**Response** `200 OK`

```json
{
  "text": "Here is the analysis you requested...",
  "artifacts": [],
  "context_id": "<uuid>",
  "sources": null
}
```

| Field        | Type        | Description                                             |
| ------------ | ----------- | ------------------------------------------------------- |
| `text`       | string      | The agent's text response.                              |
| `artifacts`  | array       | List of artifact objects (charts, tables). May be empty. |
| `context_id` | string      | The conversation context ID for follow-up messages.     |
| `sources`    | array\|null | Source references, if any.                              |

---

### POST /api/chat/stream

Streaming chat request via **Server-Sent Events (SSE)**. This is the primary endpoint used by the frontend. It sends a message to the orchestrator and streams back status updates and the final response.

**Headers**

| Header          | Value                        | Required |
| --------------- | ---------------------------- | -------- |
| Authorization   | `Bearer <cognito_jwt_token>` | Yes      |
| Content-Type    | `application/json`           | Yes      |
| Accept          | `text/event-stream`          | Yes      |

**Request Body**

Same format as `POST /api/chat` (see above).

**Response** `200 OK` (`text/event-stream`)

The response is a stream of SSE events. Each event has the format:

```
data: <json_payload>\n\n
```

#### Event types

**Status event** -- Progress updates while agents are working.

```json
{
  "type": "status",
  "message": "Querying agents..."
}
```

**Complete event** -- Final result with the agent's response and any artifacts.

```json
{
  "type": "complete",
  "data": {
    "text": "Here is the analysis you requested...",
    "artifacts": [],
    "contextId": "<uuid>"
  }
}
```

**Error event** -- Sent if an error occurs during processing.

```json
{
  "type": "error",
  "message": "An error occurred while processing your request."
}
```

---

### POST /api/chat/cancel/{request_id}

Cancel an in-progress chat request.

**Path Parameters**

| Parameter    | Type   | Description                          |
| ------------ | ------ | ------------------------------------ |
| `request_id` | string | The ID of the request to cancel.     |

**Headers**

| Header          | Value                        | Required |
| --------------- | ---------------------------- | -------- |
| Authorization   | `Bearer <cognito_jwt_token>` | Yes      |

**Response** `200 OK`

```json
{
  "success": true,
  "request_id": "<request_id>"
}
```

---

### GET /api/conversations/{context_id}

Retrieve the message history for a conversation. Conversation state is managed by AgentCore memory.

**Path Parameters**

| Parameter    | Type   | Description                     |
| ------------ | ------ | ------------------------------- |
| `context_id` | string | The conversation context UUID.  |

**Headers**

| Header          | Value                        | Required |
| --------------- | ---------------------------- | -------- |
| Authorization   | `Bearer <cognito_jwt_token>` | Yes      |

**Response** `200 OK`

```json
{
  "messages": []
}
```

| Field      | Type  | Description                                    |
| ---------- | ----- | ---------------------------------------------- |
| `messages` | array | Ordered list of messages in the conversation.  |

---

### DELETE /api/conversations/{context_id}

Clear all messages in a conversation.

**Path Parameters**

| Parameter    | Type   | Description                     |
| ------------ | ------ | ------------------------------- |
| `context_id` | string | The conversation context UUID.  |

**Headers**

| Header          | Value                        | Required |
| --------------- | ---------------------------- | -------- |
| Authorization   | `Bearer <cognito_jwt_token>` | Yes      |

**Response** `200 OK`

```json
{
  "success": true
}
```

---

## Artifacts

Agents may return **artifacts** alongside text responses. Artifacts represent structured data such as charts or tables that the frontend renders as interactive visualizations.

### Chart artifact

```json
{
  "id": "<uuid>",
  "type": "chart",
  "title": "Chart Title",
  "data": {
    "chart_type": "bar",
    "title": "Chart Title",
    "x_axis": "field_name",
    "y_axis": "field_name",
    "x_label": "X Axis Label",
    "y_label": "Y Axis Label",
    "data": [
      { "field_name": "Category A", "field_name2": 123 },
      { "field_name": "Category B", "field_name2": 456 }
    ]
  }
}
```

| Field              | Type   | Description                                                        |
| ------------------ | ------ | ------------------------------------------------------------------ |
| `id`               | string | Unique identifier for the artifact.                                |
| `type`             | string | Artifact type. Currently `"chart"`.                                |
| `title`            | string | Display title for the artifact.                                    |
| `data.chart_type`  | string | One of `bar`, `line`, `pie`, `scatter`, `histogram`.               |
| `data.title`       | string | Chart title (may duplicate the top-level `title`).                 |
| `data.x_axis`      | string | Field name in the data array to use for the x-axis.               |
| `data.y_axis`      | string | Field name in the data array to use for the y-axis.               |
| `data.x_label`     | string | Human-readable label for the x-axis.                              |
| `data.y_label`     | string | Human-readable label for the y-axis.                              |
| `data.data`        | array  | Array of data point objects. Keys correspond to `x_axis`/`y_axis`. |
