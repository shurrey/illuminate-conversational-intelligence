# Illuminate POC Backend - API Reference

The Illuminate API is served by a Lambda proxy (`lambda_handler.py`) built with FastAPI and running via Lambda Web Adapter (LWA) for real SSE streaming. The API is accessed directly via the Lambda Function URL.

Streaming responses are delivered as real-time Server-Sent Events via the Function URL's `RESPONSE_STREAM` invoke mode (not buffered).

## Authentication

All endpoints except `GET /health` require a valid **Amazon Cognito JWT token** passed in the `Authorization` header:

```
Authorization: Bearer <cognito_jwt_token>
```

Tokens are issued by the Cognito User Pool (`illuminate-users-dev`).

## CORS

CORS is configured via the `ALLOWED_ORIGINS` environment variable on the Lambda. Allowed origins typically include `localhost` development origins and any production domains.

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

**Request Body (Simplified Format)**

```json
{
  "message": "What is the average GPA for Fall 2024?",
  "context_id": "<uuid>"
}
```

| Field        | Type   | Description                                                         |
| ------------ | ------ | ------------------------------------------------------------------- |
| `message`    | string | The user's question or instruction.                                 |
| `context_id` | string | UUID for the conversation context. Reuse across messages in the same conversation. |

**Request Body (A2A JSON-RPC Format)**

The endpoint also accepts the full A2A JSON-RPC 2.0 format:

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
| `artifacts`  | array       | List of artifact objects (charts, tables, SQL). May be empty. |
| `context_id` | string      | The conversation context ID for follow-up messages.     |
| `sources`    | array\|null | Source references, if any.                              |

---

### POST /api/chat/stream

Streaming chat request via **Server-Sent Events (SSE)**. This is the primary endpoint for real-time interaction. It sends a message to the orchestrator and streams back real-time status updates and the final response.

Streaming is real-time (not buffered) thanks to Lambda Web Adapter running uvicorn inside Lambda with `RESPONSE_STREAM` invoke mode.

**Headers**

| Header          | Value                        | Required |
| --------------- | ---------------------------- | -------- |
| Authorization   | `Bearer <cognito_jwt_token>` | Yes      |
| Content-Type    | `application/json`           | Yes      |
| Accept          | `text/event-stream`          | Yes      |

**Request Body**

Same format as `POST /api/chat` (either simplified or A2A JSON-RPC format).

**Response** `200 OK` (`text/event-stream`)

The response is a stream of SSE events. Each event has the format:

```
data: <json_payload>\n\n
```

#### Event types

**Status event** -- Real-time progress updates as the orchestrator invokes each specialist agent. These are generated from `[TOOL_STATUS:agent_name]` markers detected in the streaming response.

```json
{
  "type": "status",
  "message": "Querying database..."
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

Retrieve the message history for a conversation. Conversation state is managed by AgentCore Short-Term Memory (STM).

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

### GET /api/v1/dictionary/submodels

Returns the list of available data submodels (schemas) in the data dictionary.

**Headers**

| Header          | Value                        | Required |
| --------------- | ---------------------------- | -------- |
| Authorization   | `Bearer <cognito_jwt_token>` | Yes      |

**Response** `200 OK`

```json
[
  {
    "id": 1,
    "name": "cdm_lms",
    "displayName": "LMS Common Data Model",
    "schemaId": "CDM_LMS"
  }
]
```

| Field         | Type   | Description                                |
| ------------- | ------ | ------------------------------------------ |
| `id`          | number | Unique identifier for the submodel.        |
| `name`        | string | Internal name of the submodel.             |
| `displayName` | string | Human-readable display name.               |
| `schemaId`    | string | Snowflake schema identifier.               |

---

### GET /api/v1/dictionary/definitions

Returns all data dictionary definitions (metrics, dimensions, columns).

**Headers**

| Header          | Value                        | Required |
| --------------- | ---------------------------- | -------- |
| Authorization   | `Bearer <cognito_jwt_token>` | Yes      |

**Response** `200 OK`

```json
[
  {
    "id": 1,
    "name": "person_id",
    "displayName": "Person ID",
    "text": "Unique identifier for a person record.",
    "boundSchema": "CDM_LMS",
    "boundTable": "PERSON",
    "boundColumn": "PERSON_ID",
    "columnDataType": "NUMBER",
    "columnIsIdentity": true,
    "columnIsNullable": false,
    "sourceType": "column",
    "isDeleted": false,
    "isDeprecated": false,
    "isVisible": true,
    "created": "2024-01-15T00:00:00Z",
    "lastModified": "2024-06-01T00:00:00Z",
    "majorVersion": 1,
    "minorVersion": 0,
    "technicalSpecifications": [
      {
        "objectIdentifier": "CDM_LMS.PERSON.PERSON_ID",
        "sourceProduct": "Learn",
        "isAvailableInSourceProduct": true,
        "isPii": false,
        "grainAttributes": ["PERSON_ID"],
        "majorVersion": 1,
        "minorVersion": 0,
        "lastModified": "2024-06-01T00:00:00Z"
      }
    ]
  }
]
```

| Field                    | Type        | Description                                           |
| ------------------------ | ----------- | ----------------------------------------------------- |
| `id`                     | number      | Unique identifier for the definition.                 |
| `name`                   | string      | Internal name.                                        |
| `displayName`            | string      | Human-readable display name.                          |
| `text`                   | string      | Description of the definition.                        |
| `boundSchema`            | string      | Snowflake schema this definition belongs to.          |
| `boundTable`             | string      | Snowflake table this definition is bound to.          |
| `boundColumn`            | string\|null | Snowflake column (null for table-level definitions). |
| `columnDataType`         | string\|null | Snowflake column data type.                          |
| `columnIsIdentity`       | boolean     | Whether the column is an identity column.             |
| `columnIsNullable`       | boolean     | Whether the column allows nulls.                      |
| `sourceType`             | string      | Type of definition (`column`, `table`, `metric`).     |
| `isDeleted`              | boolean     | Soft-delete flag.                                     |
| `isDeprecated`           | boolean     | Deprecation flag.                                     |
| `isVisible`              | boolean     | Visibility flag.                                      |
| `created`                | string      | ISO 8601 creation timestamp.                          |
| `lastModified`           | string      | ISO 8601 last modification timestamp.                 |
| `majorVersion`           | number      | Major version number.                                 |
| `minorVersion`           | number      | Minor version number.                                 |
| `technicalSpecifications` | array      | Array of technical specification objects.             |

**Technical Specification Object**

| Field                        | Type     | Description                                        |
| ---------------------------- | -------- | -------------------------------------------------- |
| `objectIdentifier`           | string   | Fully qualified object name.                       |
| `sourceProduct`              | string   | Source product name.                                |
| `isAvailableInSourceProduct` | boolean  | Whether available in the source product.           |
| `isPii`                      | boolean  | Whether the field contains PII.                    |
| `grainAttributes`            | string[] | Grain attribute names.                             |
| `majorVersion`               | number   | Major version number.                              |
| `minorVersion`               | number   | Minor version number.                              |
| `lastModified`               | string   | ISO 8601 last modification timestamp.              |

---

### GET /api/v1/dictionary/erd

Returns the Entity Relationship Diagram data, including foreign key relationships between tables.

**Headers**

| Header          | Value                        | Required |
| --------------- | ---------------------------- | -------- |
| Authorization   | `Bearer <cognito_jwt_token>` | Yes      |

**Response** `200 OK`

```json
{
  "schemas": [
    {
      "foreignKeys": [
        {
          "foreignKey": {
            "constraintName": "FK_ENROLLMENT_PERSON",
            "tableFQN": "CDM_LMS.ENROLLMENT",
            "tableName": "ENROLLMENT",
            "tableSchema": "CDM_LMS",
            "cardinality": "MANY",
            "columns": [
              {
                "FQN": "CDM_LMS.ENROLLMENT.PERSON_ID",
                "name": "PERSON_ID",
                "ordinalPosition": 1
              }
            ]
          },
          "uniqueKey": {
            "constraintName": "PK_PERSON",
            "tableFQN": "CDM_LMS.PERSON",
            "tableName": "PERSON",
            "tableSchema": "CDM_LMS",
            "cardinality": "ONE",
            "columns": [
              {
                "FQN": "CDM_LMS.PERSON.PERSON_ID",
                "name": "PERSON_ID",
                "ordinalPosition": 1
              }
            ]
          }
        }
      ]
    }
  ]
}
```

| Field                         | Type   | Description                                     |
| ----------------------------- | ------ | ----------------------------------------------- |
| `schemas`                     | array  | Array of schema objects containing relationships.|
| `schemas[].foreignKeys`       | array  | Array of foreign key relationship objects.       |
| `foreignKey.constraintName`   | string | Name of the foreign key constraint.             |
| `foreignKey.tableFQN`         | string | Fully qualified table name.                     |
| `foreignKey.tableName`        | string | Table name.                                     |
| `foreignKey.tableSchema`      | string | Schema name.                                    |
| `foreignKey.cardinality`      | string | Relationship cardinality (e.g., `MANY`, `ONE`). |
| `foreignKey.columns`          | array  | Array of column objects in the key.             |
| `foreignKey.columns[].FQN`    | string | Fully qualified column name.                    |
| `foreignKey.columns[].name`   | string | Column name.                                    |
| `foreignKey.columns[].ordinalPosition` | number | Position of the column in the key.     |
| `uniqueKey`                   | object | Same shape as `foreignKey`, representing the referenced unique/primary key. |

---

### GET /api/v1/dictionary/preview

Returns a preview of data from a specific table.

**Query Parameters**

| Parameter | Type   | Required | Description                          |
| --------- | ------ | -------- | ------------------------------------ |
| `schema`  | string | Yes      | Snowflake schema name (e.g., `CDM_LMS`). |
| `table`   | string | Yes      | Table name (e.g., `PERSON`).         |
| `limit`   | number | No       | Maximum rows to return (default: 20).|

**Headers**

| Header          | Value                        | Required |
| --------------- | ---------------------------- | -------- |
| Authorization   | `Bearer <cognito_jwt_token>` | Yes      |

**Example Request**

```
GET /api/v1/dictionary/preview?schema=CDM_LMS&table=PERSON&limit=20
```

**Response** `200 OK`

```json
{
  "columns": ["PERSON_ID", "FIRST_NAME", "LAST_NAME", "EMAIL"],
  "rows": [
    {"PERSON_ID": 1001, "FIRST_NAME": "Jane", "LAST_NAME": "Doe", "EMAIL": "jdoe@example.edu"},
    {"PERSON_ID": 1002, "FIRST_NAME": "John", "LAST_NAME": "Smith", "EMAIL": "jsmith@example.edu"}
  ]
}
```

| Field     | Type                          | Description                          |
| --------- | ----------------------------- | ------------------------------------ |
| `columns` | string[]                      | Ordered list of column names.        |
| `rows`    | Array<Record<string, unknown>> | Array of row objects keyed by column name. |

---

### POST /api/v1/dashboard/query

Execute an arbitrary SQL query against Snowflake. Intended for dashboard and visualization use cases.

**Headers**

| Header          | Value                        | Required |
| --------------- | ---------------------------- | -------- |
| Authorization   | `Bearer <cognito_jwt_token>` | Yes      |
| Content-Type    | `application/json`           | Yes      |

**Request Body**

```json
{
  "sql": "SELECT department, COUNT(*) as enrollment FROM DATABASE.CDM_LMS.ENROLLMENTS GROUP BY department"
}
```

| Field | Type   | Description                     |
| ----- | ------ | ------------------------------- |
| `sql` | string | The SQL query to execute.       |

**Response** `200 OK` (success)

```json
{
  "columns": ["DEPARTMENT", "ENROLLMENT"],
  "rows": [
    {"DEPARTMENT": "Computer Science", "ENROLLMENT": 342},
    {"DEPARTMENT": "Mathematics", "ENROLLMENT": 218}
  ]
}
```

| Field     | Type                          | Description                          |
| --------- | ----------------------------- | ------------------------------------ |
| `columns` | string[]                      | Ordered list of column names.        |
| `rows`    | Array<Record<string, unknown>> | Array of row objects keyed by column name. |

**Response** `200 OK` (error)

```json
{
  "error": "SQL compilation error: Object 'DATABASE.CDM_LMS.NONEXISTENT' does not exist."
}
```

| Field   | Type   | Description                              |
| ------- | ------ | ---------------------------------------- |
| `error` | string | Error message from query execution.      |

---

## Artifacts

Agents may return **artifacts** alongside text responses. Artifacts represent structured data such as charts, tables, or SQL queries. They are returned in the `artifacts` array of the API response.

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
| `type`             | string | `"chart"` for chart artifacts.                                     |
| `title`            | string | Display title for the artifact.                                    |
| `data.chart_type`  | string | One of `bar`, `line`, `pie`, `scatter`, `histogram`.               |
| `data.title`       | string | Chart title (may duplicate the top-level `title`).                 |
| `data.x_axis`      | string | Field name in the data array to use for the x-axis.               |
| `data.y_axis`      | string | Field name in the data array to use for the y-axis.               |
| `data.x_label`     | string | Human-readable label for the x-axis.                              |
| `data.y_label`     | string | Human-readable label for the y-axis.                              |
| `data.data`        | array  | Array of data point objects. Keys correspond to `x_axis`/`y_axis`. |

### SQL artifact

```json
{
  "id": "<uuid>",
  "type": "sql",
  "title": "SQL Query",
  "data": {
    "query": "SELECT department, COUNT(*) as enrollment\nFROM DATABASE.CDM_LMS.ENROLLMENTS\nGROUP BY department\nORDER BY enrollment DESC"
  }
}
```

| Field        | Type   | Description                                                 |
| ------------ | ------ | ----------------------------------------------------------- |
| `id`         | string | Unique identifier for the artifact.                         |
| `type`       | string | `"sql"` for SQL query artifacts.                            |
| `title`      | string | Display title (typically "SQL Query").                       |
| `data.query` | string | The raw SQL query that was executed against Snowflake.       |

API clients can render SQL artifacts as they see fit -- for example, displaying formatted SQL in a modal with copy-to-clipboard functionality.

### Other artifact types

| Type    | Description |
|---------|-------------|
| `table` | Tabular data rendered as an HTML table |
| `text`  | Plain text artifact |
| `error` | Error details |
