> **Note:** This is the **original PRD** written before implementation began. The actual
> implementation has diverged significantly from this specification in several ways:
>
> - **Agents implemented:** SQL, Analyst, Writer, Validator (not Learning, Student,
>   Telemetry, Visualization, or Collaboration as originally planned). A single SQL agent
>   handles all schemas rather than domain-specific agents per CDM schema.
> - **No Snowflake MCP server:** The SQL agent connects directly to Snowflake via
>   `snowflake-connector-python` rather than through an MCP server layer.
> - **No Cortex Analyst:** The LLM generates SQL directly from schema introspection
>   rather than using Snowflake Cortex Analyst with semantic models.
> - **Auth:** Amazon Cognito JWT authentication (not stub auth or institutional SSO).
> - **No assistant-ui:** Custom React components (ChatContainer, MessageBubble, etc.)
>   instead of the assistant-ui library.
> - **Infrastructure:** AWS CDK (TypeScript, 3 stacks) replaced the planned CloudFormation
>   approach. Agents run as Docker containers on AgentCore, not zip-based runtimes.
> - **Lambda proxy:** Uses Lambda Web Adapter (LWA) for real SSE streaming instead of Mangum.
> - **Models:** All agents currently use Claude Sonnet 4.6 via cross-region inference profiles.
>
> The spec below is preserved as a historical reference for the original vision and requirements.

---

# Product Requirements Document: Illuminate Conversational Intelligence Platform

## Executive Summary

This PRD defines a multi-agent conversational analytics system that enables natural language access to Anthology Illuminate's educational data warehouse. The platform leverages Google's A2A (Agent-to-Agent) protocol for inter-agent communication, Snowflake MCP servers for data access, and AWS Bedrock AgentCore for enterprise-grade deployment and orchestration.

**Product Name:** Illuminate Conversational Intelligence (ICI)

**Vision:** Enable institutional stakeholders---from analysts to administrators---to explore complex educational data through natural language conversations, removing the barrier between users and insights.

---

## 1. Product Overview

### 1.1 Problem Statement

Educational institutions struggle to democratize access to their data:
- Technical expertise required for SQL/BI tool usage limits who can extract insights
- Data silos across LMS, SIS, and telemetry systems create fragmented understanding
- Manual reporting cycles delay decision-making for student success interventions
- Existing dashboards provide fixed views, not exploratory conversations

### 1.2 Solution

A multi-agent conversational platform where specialized AI agents collaborate to:
- Translate natural language queries into precise SQL against Illuminate's Snowflake warehouse
- Provide contextual insights across learning management (CDM_LMS), student information (CDM_SIS), collaboration (CDM_CLB), telemetry (CDM_TLM), and media (CDM_MEDIA) domains
- Maintain conversation context for iterative exploration
- Visualize results through charts and summaries

### 1.3 Target Users

| User Persona | Needs |
|--------------|-------|
| **Institutional Researcher** | Ad-hoc queries, cohort analysis, compliance reporting |
| **Academic Advisor** | Student performance patterns, early warning indicators |
| **Department Chair** | Course effectiveness, instructor workload analysis |
| **Enrollment Manager** | Retention trends, registration patterns |
| **IT Administrator** | System usage analytics, integration monitoring |

---

## 2. Technical Architecture

### 2.1 Multi-Agent System Design (A2A Protocol)

The system follows a **Supervisor-Specialist pattern** using Google's A2A protocol for agent communication:

```
+-------------------------------------------------------------+
|                     Frontend (React Chat UI)                     |
+-------------------------------------------------------------+
                                |
                                v
+-------------------------------------------------------------+
|                    Orchestrator Agent (Supervisor)               |
|  - Routes queries to appropriate specialist agents               |
|  - Maintains conversation context via AgentCore Memory           |
|  - Aggregates responses for user presentation                    |
|  - Handles clarification requests                                |
+-------------------------------------------------------------+
           |              |              |              |
     A2A   |        A2A   |        A2A   |        A2A   |
           v              v              v              v
+--------------+  +--------------+  +--------------+  +--------------+
|  Learning    |  |   Student    |  |  Telemetry   |  | Visualization|
|    Agent     |  |    Agent     |  |    Agent     |  |    Agent     |
|              |  |              |  |              |  |              |
| CDM_LMS data |  | CDM_SIS data |  | CDM_TLM data |  | Chart/Graph  |
| Courses      |  | Enrollments  |  | User activity|  | generation   |
| Grades       |  | Demographics |  | Engagement   |  | Summaries    |
| Assignments  |  | Programs     |  | Sessions     |  |              |
+--------------+  +--------------+  +--------------+  +--------------+
           |              |              |
           +------------------------------+
                          |
                          v
+-------------------------------------------------------------+
|                    Snowflake MCP Server Layer                    |
|  - Cortex Analyst for semantic SQL generation                   |
|  - Schema introspection tools                                    |
|  - Query execution with RBAC enforcement                         |
|  - Result formatting and pagination                              |
+-------------------------------------------------------------+
                          |
                          v
+-------------------------------------------------------------+
|               Anthology Illuminate Snowflake Warehouse           |
|  CDM_LMS | CDM_SIS | CDM_CLB | CDM_TLM | CDM_MEDIA | LEARN      |
+-------------------------------------------------------------+
```

### 2.2 Agent Specifications

#### 2.2.1 Orchestrator Agent (Supervisor)

**Role:** Central coordinator that receives user queries and delegates to specialists

**Agent Card (A2A):**
```json
{
  "name": "illuminate-orchestrator",
  "description": "Central coordinator for educational data queries. Routes requests to specialized domain agents and aggregates responses.",
  "protocolVersion": "0.3",
  "capabilities": {
    "streaming": true,
    "pushNotifications": true
  },
  "defaultInputModes": ["text"],
  "defaultOutputModes": ["text", "data"],
  "skills": [
    {
      "id": "query_routing",
      "name": "Query Router",
      "description": "Analyzes user intent and routes to appropriate specialist agents"
    },
    {
      "id": "response_aggregation",
      "name": "Response Aggregator",
      "description": "Combines results from multiple agents into coherent responses"
    },
    {
      "id": "clarification",
      "name": "Clarification Handler",
      "description": "Requests additional context when queries are ambiguous"
    }
  ]
}
```

**Responsibilities:**
- Parse user intent from natural language
- Determine which specialist agent(s) to invoke
- Manage multi-turn conversation state
- Handle cross-domain queries requiring multiple agents
- Format final responses for presentation

#### 2.2.2 Learning Agent (CDM_LMS Specialist)

**Role:** Expert on Blackboard Learn data---courses, enrollments, grades, assignments

**Agent Card:**
```json
{
  "name": "illuminate-learning-agent",
  "description": "Specialist for LMS data including courses, enrollments, grades, and assignments from Blackboard Learn",
  "skills": [
    {
      "id": "course_analytics",
      "name": "Course Analytics",
      "description": "Analyze course performance, completion rates, and activity patterns"
    },
    {
      "id": "grade_analysis",
      "name": "Grade Analysis",
      "description": "Query and analyze student grades, GPA trends, and assessment results"
    },
    {
      "id": "enrollment_queries",
      "name": "Enrollment Queries",
      "description": "Track enrollment patterns, role assignments, and course participation"
    }
  ]
}
```

**MCP Tools:**
- `query_courses` - Search/filter course catalog
- `get_enrollments` - Retrieve enrollment data with filters
- `analyze_grades` - Grade distribution and trend analysis
- `get_assignments` - Assignment completion and submission data

**Key Tables:** CDM_LMS.PERSON_COURSE, CDM_LMS.COURSE, CDM_LMS.GRADE, CDM_LMS.ASSIGNMENT

#### 2.2.3 Student Agent (CDM_SIS Specialist)

**Role:** Expert on student information---demographics, programs, academic records

**Agent Card:**
```json
{
  "name": "illuminate-student-agent",
  "description": "Specialist for student information system data including demographics, programs, and academic records",
  "skills": [
    {
      "id": "student_lookup",
      "name": "Student Lookup",
      "description": "Search and retrieve student demographic information"
    },
    {
      "id": "program_analysis",
      "name": "Program Analysis",
      "description": "Analyze program enrollment, progression, and completion"
    },
    {
      "id": "retention_metrics",
      "name": "Retention Metrics",
      "description": "Calculate retention, persistence, and graduation rates"
    }
  ]
}
```

**MCP Tools:**
- `search_students` - Find students by various criteria
- `get_program_data` - Academic program information
- `calculate_retention` - Retention/completion metrics
- `cohort_analysis` - Compare student cohorts

**Key Tables:** CDM_SIS.STUDENT, CDM_SIS.PROGRAM, CDM_SIS.ENROLLMENT, CDM_SIS.ACADEMIC_RECORD

#### 2.2.4 Telemetry Agent (CDM_TLM Specialist)

**Role:** Expert on user behavior---engagement, activity patterns, session data

**Agent Card:**
```json
{
  "name": "illuminate-telemetry-agent",
  "description": "Specialist for user engagement and activity telemetry across Anthology solutions",
  "skills": [
    {
      "id": "engagement_analysis",
      "name": "Engagement Analysis",
      "description": "Analyze user engagement patterns and activity levels"
    },
    {
      "id": "usage_metrics",
      "name": "Usage Metrics",
      "description": "Track system usage, feature adoption, and interaction patterns"
    },
    {
      "id": "early_warning",
      "name": "Early Warning Indicators",
      "description": "Identify at-risk students based on activity patterns"
    }
  ]
}
```

**MCP Tools:**
- `get_activity_data` - User activity and interaction data
- `analyze_engagement` - Engagement scoring and trends
- `detect_risk_indicators` - Early warning analysis
- `session_analytics` - Session duration and patterns

**Key Tables:** CDM_TLM.ACTIVITY, CDM_TLM.SESSION, CDM_TLM.EVENT

#### 2.2.5 Visualization Agent

**Role:** Transform data into charts, summaries, and exportable formats

**Agent Card:**
```json
{
  "name": "illuminate-visualization-agent",
  "description": "Specialist for data visualization, summarization, and export formatting",
  "skills": [
    {
      "id": "chart_generation",
      "name": "Chart Generation",
      "description": "Create charts and graphs from query results"
    },
    {
      "id": "data_summarization",
      "name": "Data Summarization",
      "description": "Generate narrative summaries of data insights"
    },
    {
      "id": "export_formatting",
      "name": "Export Formatting",
      "description": "Format data for CSV, Excel, or PDF export"
    }
  ]
}
```

### 2.3 A2A Communication Flow

**Query Lifecycle:**

1. **User Input** -> Frontend sends message to Orchestrator
2. **Intent Classification** -> Orchestrator analyzes query, determines required agents
3. **Task Delegation** (A2A) -> Orchestrator sends JSON-RPC `message/send` to specialists
4. **MCP Execution** -> Specialists invoke Snowflake MCP tools
5. **Result Aggregation** -> Specialists return artifacts to Orchestrator
6. **Visualization** (optional) -> Orchestrator delegates to Visualization Agent
7. **Response Delivery** -> Formatted response streamed to frontend

**Example A2A Task Delegation:**
```json
{
  "jsonrpc": "2.0",
  "method": "message/send",
  "params": {
    "message": {
      "role": "user",
      "parts": [{
        "type": "text",
        "text": "Get average grade by course for Fall 2024 with more than 50 enrollments"
      }],
      "messageId": "msg-123",
      "contextId": "session-456"
    }
  },
  "id": "task-789"
}
```

### 2.4 Snowflake MCP Server Configuration

**Server Definition:**
```yaml
# illuminate-mcp-server.yaml
name: illuminate-mcp-server
version: 1.0.0

connection:
  account: ${SNOWFLAKE_ACCOUNT}
  warehouse: ILLUMINATE_WH
  database: ILLUMINATE
  role: ILLUMINATE_ANALYST_ROLE

analyst_services:
  - name: illuminate_analyst
    semantic_model_file: illuminate_semantic_model.yaml
    description: "Semantic model for Illuminate canonical data"

other_services:
  object_manager: true
  query_manager: true
  semantic_views: true

sql_statement_permissions:
  allow:
    - Select
  deny:
    - Insert
    - Update
    - Delete
    - Drop
    - Alter
```

**Semantic Model (Cortex Analyst):**
```yaml
# illuminate_semantic_model.yaml
name: illuminate_analytics
tables:
  - name: CDM_LMS.PERSON_COURSE
    description: "Student-course enrollment mappings with roles and status"
    columns:
      - name: PERSON_ID
        description: "Unique student identifier"
      - name: COURSE_ID
        description: "Unique course identifier"
      - name: ROLE
        description: "User role in course (Student, Instructor, TA)"
      - name: ENROLLMENT_STATUS
        description: "Active, Dropped, Completed"

  - name: CDM_LMS.GRADE
    description: "Grade records for course assessments"
    columns:
      - name: GRADE_VALUE
        description: "Numeric or letter grade"
      - name: GRADE_POINTS
        description: "Grade points for GPA calculation"

  # Additional table definitions...

verified_queries:
  - name: "Average grade by course"
    question: "What is the average grade for each course?"
    sql: |
      SELECT c.COURSE_NAME, AVG(g.GRADE_POINTS) as avg_grade
      FROM CDM_LMS.GRADE g
      JOIN CDM_LMS.COURSE c ON g.COURSE_ID = c.COURSE_ID
      GROUP BY c.COURSE_NAME
      ORDER BY avg_grade DESC
```

### 2.5 AWS Bedrock AgentCore Deployment

**Architecture Components:**

| Component | AgentCore Service | Purpose |
|-----------|-------------------|---------|
| Agent Hosting | AgentCore Runtime | Serverless execution of all agents |
| Tool Integration | AgentCore Gateway | MCP server connectivity |
| Conversation State | AgentCore Memory | Session and long-term context |
| Authentication | AgentCore Identity | SSO integration with institutional IdP |
| Guardrails | AgentCore Policy | Query safety and data access controls |
| Monitoring | CloudWatch + Evaluations | Performance tracking and quality scoring |

### 2.6 Strands Agents Implementation

**Project Structure:**
```
agents/
├── orchestrator/
│   ├── agent.py                 # Orchestrator agent definition
│   ├── tools/
│   │   ├── route_query.py       # Intent classification and routing
│   │   ├── aggregate_results.py # Response aggregation
│   │   └── clarify.py           # Clarification requests
│   └── prompts/
│       └── system_prompt.txt    # Orchestrator behavior
├── learning/
│   ├── agent.py                 # Learning agent (CDM_LMS)
│   ├── tools/
│   │   ├── query_courses.py
│   │   ├── get_enrollments.py
│   │   ├── analyze_grades.py
│   │   └── get_assignments.py
│   └── prompts/
│       └── system_prompt.txt
├── student/
│   ├── agent.py                 # Student agent (CDM_SIS)
│   ├── tools/
│   │   ├── search_students.py
│   │   ├── get_program_data.py
│   │   ├── calculate_retention.py
│   │   └── cohort_analysis.py
│   └── prompts/
│       └── system_prompt.txt
├── telemetry/
│   ├── agent.py                 # Telemetry agent (CDM_TLM)
│   ├── tools/
│   │   ├── get_activity_data.py
│   │   ├── analyze_engagement.py
│   │   ├── detect_risk_indicators.py
│   │   └── session_analytics.py
│   └── prompts/
│       └── system_prompt.txt
├── visualization/
│   ├── agent.py                 # Visualization agent
│   ├── tools/
│   │   ├── generate_chart.py
│   │   ├── summarize_data.py
│   │   └── export_data.py
│   └── prompts/
│       └── system_prompt.txt
└── shared/
    ├── snowflake_mcp.py         # Snowflake MCP server integration
    ├── a2a_client.py            # A2A protocol utilities
    └── models.py                # Shared data models
```

---

## 3. Frontend Architecture

### 3.1 Technology Stack

| Layer | Technology | Rationale |
|-------|------------|-----------|
| Agent Framework | Strands Agents | AWS-native with strong AgentCore/MCP/A2A integration |
| Frontend | React 18+ | Component-based, large ecosystem |
| UI Library | assistant-ui | Purpose-built for AI chat interfaces |
| Styling | Tailwind CSS | Utility-first, matches Anthology patterns |
| State Management | React Context + assistant-ui hooks | Optimized for chat state |
| Data Visualization | Plotly.js | Interactive charts with export |
| API Client | Vercel AI SDK | Streaming support, tool call handling |

### 3.2 Component Architecture

```
src/
├── components/
│   ├── chat/
│   │   ├── ChatContainer.tsx       # Main chat wrapper
│   │   ├── MessageList.tsx         # Virtualized message rendering
│   │   ├── MessageBubble.tsx       # Individual message display
│   │   ├── InputArea.tsx           # User input with suggestions
│   │   └── TypingIndicator.tsx     # Agent response indicator
│   ├── visualization/
│   │   ├── ChartRenderer.tsx       # Dynamic chart display
│   │   ├── DataTable.tsx           # Tabular result display
│   │   └── ExportButton.tsx        # CSV/PDF export
│   ├── context/
│   │   ├── ConversationPanel.tsx   # Conversation history sidebar
│   │   └── QuerySuggestions.tsx    # Recommended queries
│   └── layout/
│       ├── AppShell.tsx            # Main application layout
│       ├── Header.tsx              # Navigation and user info
│       └── Sidebar.tsx             # Data domain selector
├── hooks/
│   ├── useChat.ts                  # Chat state management
│   ├── useAgentConnection.ts       # A2A client connection
│   └── useVisualization.ts         # Chart rendering logic
├── services/
│   ├── agentClient.ts              # A2A protocol client
│   └── authService.ts              # Authentication handling
└── types/
    ├── message.ts                  # Message type definitions
    └── visualization.ts            # Chart/data types
```

### 3.3 Design System Alignment

Following Anthology's UEF patterns and accessibility standards:

- **Color Palette:** Anthology brand colors with WCAG AA contrast
- **Typography:** System fonts with clear hierarchy
- **Spacing:** 8px grid system
- **Components:** Consistent with Blackboard Ultra patterns
- **Accessibility:** ARIA labels, keyboard navigation, screen reader support

---

## 4. Data Model Integration

### 4.1 Illuminate Canonical Data Model (CDM)

| Schema | Source | Refresh Rate | Key Entities |
|--------|--------|--------------|--------------|
| CDM_LMS | Blackboard Learn | Overnight | Courses, Enrollments, Grades, Assignments |
| CDM_SIS | Anthology Student | Daily 8:00 UTC | Students, Programs, Academic Records |
| CDM_CLB | Collaborate | 2 hours | Sessions, Attendance, Recordings |
| CDM_TLM | Telemetry | 30 minutes | Activity, Events, Engagement |
| CDM_MEDIA | Video Studio | Near real-time | Media, Views, Interactions |
| LEARN | Blackboard ODS | 4 hours | 191 source tables |

### 4.2 Key Entity Relationships

```
CDM_LMS.PERSON_COURSE -----+------- CDM_LMS.COURSE
         |                 |
         |                 +------- CDM_LMS.GRADE
         |
         +------- CDM_SIS.STUDENT ------- CDM_SIS.PROGRAM
                     |
                     +------- CDM_TLM.ACTIVITY
```

---

## 5. Security Architecture

### 5.1 Authentication Flow

**Phase 1-3 (Stub Authentication):**
```
User -> API Key / Basic Auth -> Backend Validation -> Session Token
```

**Phase 4+ (SSO Integration Ready):**
```
User -> Institutional IdP (SAML/OIDC) -> AgentCore Identity -> Session Token
```

### 5.2 Authorization Model

| Level | Mechanism | Description |
|-------|-----------|-------------|
| User Auth | AgentCore Identity | SSO with institution IdP |
| Data Access | Snowflake RBAC | Role-based table/column access |
| Query Safety | AgentCore Policy | Natural language guardrails |
| Agent Trust | A2A Security Cards | Signed agent authentication |

### 5.3 Data Protection

- **FERPA Compliance:** Student data access logging and consent tracking
- **PII Handling:** Aggregate-only queries for sensitive demographics
- **Audit Trail:** All queries logged with user identity and timestamp
- **Encryption:** TLS 1.3 in transit, AES-256 at rest

---

## 6. Implementation Plan

> **Selected Configuration:**
> - **Agent Framework:** Strands Agents (AWS-native)
> - **Data Access:** Full CDM access (CDM_LMS, CDM_SIS, CDM_CLB, CDM_TLM, CDM_MEDIA, LEARN)
> - **Authentication:** Stub authentication initially (SSO integration deferred)
> - **Approach:** Full Analytics Suite - comprehensive functionality from start

### Phase 1: Infrastructure & Core Agents (Weeks 1-4)

**Deliverables:**
- [ ] Snowflake MCP server configured with full Illuminate connection
- [ ] Semantic models defined for all CDM schemas
- [ ] Strands-based Orchestrator Agent with routing logic
- [ ] Learning Agent (CDM_LMS) with grade/enrollment/assignment queries
- [ ] Student Agent (CDM_SIS) with demographics/program queries
- [ ] AgentCore Runtime deployment with A2A protocol
- [ ] Stub authentication service (API key or basic auth)
- [ ] React chat UI foundation with assistant-ui

### Phase 2: Full Agent Suite & Visualization (Weeks 5-8)

**Deliverables:**
- [ ] Telemetry Agent (CDM_TLM) with engagement/activity queries
- [ ] Collaboration Agent (CDM_CLB) with session/attendance queries
- [ ] Media Agent (CDM_MEDIA) with video analytics queries
- [ ] Visualization Agent with Plotly chart generation
- [ ] A2A communication between all agents
- [ ] AgentCore Memory for conversation persistence
- [ ] Data export functionality (CSV, Excel, PDF)
- [ ] Query suggestion engine based on common patterns

---

## 7. Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Query Accuracy | >95% | Evaluator scoring of response correctness |
| Response Time (p95) | <5s | CloudWatch latency metrics |
| User Adoption | 500 MAU in 6 months | Active user tracking |
| Query Volume | 10,000/month | Request logging |
| User Satisfaction | >4.0/5.0 | In-app feedback |
| Data Coverage | 80% of common queries | Query pattern analysis |

---

## 8. Appendix

### A. Reference Links

- [Google A2A Protocol Specification](https://a2a-protocol.org/latest/)
- [A2A GitHub Repository](https://github.com/a2aproject/A2A)
- [AWS Bedrock AgentCore Documentation](https://aws.amazon.com/bedrock/agentcore/)
- [AgentCore Samples Repository](https://github.com/awslabs/amazon-bedrock-agentcore-samples)
- [Snowflake MCP Server](https://github.com/Snowflake-Labs/mcp)
- [Anthology Illuminate Developer Docs](https://help.anthology.com/illuminate/en/anthology-illuminate-developer.html)
- [assistant-ui React Library](https://www.assistant-ui.com/)

### B. Glossary

| Term | Definition |
|------|------------|
| A2A | Agent-to-Agent protocol for inter-agent communication |
| MCP | Model Context Protocol for agent-to-tool communication |
| CDM | Canonical Data Model (Illuminate's unified schema) |
| AgentCore | AWS Bedrock service for agent deployment |
| Agent Card | JSON metadata describing agent capabilities (A2A) |
| Cortex Analyst | Snowflake service for natural language to SQL |
