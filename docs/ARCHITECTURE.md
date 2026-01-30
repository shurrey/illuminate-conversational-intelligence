# System Architecture

## Overview

Illuminate Conversational Intelligence uses a **Planner-Executor** pattern with specialized agents:

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

## Design Philosophy

### Why Planner-Executor?

This pattern separates reasoning from execution:

1. **Planner (Claude Opus)**: Uses deep reasoning to analyze query complexity, determine the pipeline path, and select appropriate agents. Called once per query.

2. **Orchestrator (Claude Sonnet)**: Executes the plan efficiently, coordinating specialist agents without re-reasoning about strategy.

Benefits:
- **Cost efficiency**: Opus is only used for planning, not every agent interaction
- **Consistency**: Plans are explicit and auditable
- **Flexibility**: Different pipeline paths for different query types

### Specialist Agents

Each agent has a focused responsibility:

| Agent | Model | Responsibility |
|-------|-------|----------------|
| Planner | Opus | Query analysis, plan creation |
| Orchestrator | Sonnet | Plan execution, coordination |
| SQL | Sonnet | SQL generation and execution |
| Analyst | Sonnet/Opus | Data interpretation, pattern finding |
| Writer | Sonnet | Natural language response crafting |
| Visualization | N/A | Chart configuration generation |
| Validator | Sonnet | FERPA compliance checking |

## Pipeline Paths

The Planner selects one of four execution paths:

| Path | When Used | Agents | Example |
|------|-----------|--------|---------|
| SIMPLE | Basic counts, lookups | SQL only | "How many courses?" |
| STANDARD | Analytical queries | SQL → Analyst → Writer | "Average GPA by department?" |
| DEEP_ANALYSIS | Complex patterns | SQL → Analyst(Opus) → Writer | "What trends do you see?" |
| VIZ_ONLY | Visualization requests | Visualization only | "Chart that" |

## Data Flow

### Standard Query Flow

```python
async def handle_query(query: str, context: ConversationContext):
    # 1. Planner creates execution plan (Opus - ONE call)
    plan = await planner.create_plan(query, context)
    # Returns: ExecutionPlan with path, agents, model selections

    yield {"type": "planning", "plan": plan.to_dict()}

    # 2. Orchestrator executes the plan (Sonnet)
    if plan.pipeline_path == PipelinePath.VIZ_ONLY:
        return await self._handle_viz_only(context)

    # 3. SQL Agent - generate and execute query
    sql_result = await sql_agent.handle_query(query, context)
    yield {"type": "sql_complete", "row_count": sql_result.row_count}

    if plan.pipeline_path == PipelinePath.SIMPLE:
        return self._format_simple_response(sql_result)

    # 4. Analyst Agent - interpret data (model selected by plan)
    analysis = await analyst_agent.analyze(
        query=query,
        data=sql_result.data,
        model=plan.analyst_model  # "sonnet" or "opus"
    )
    yield {"type": "analysis_complete"}

    # 5. Writer Agent - craft response
    response = await writer_agent.write(
        query=query,
        data=sql_result.data,
        analysis=analysis
    )

    # 6. Visualization (if planned)
    if plan.needs_visualization:
        chart = await visualization_agent.generate(...)
        response.artifacts.append(chart)

    # 7. Validation (unless skipped for simple queries)
    if not plan.skip_validation:
        await validator_agent.validate(...)

    return response
```

## Execution Plan Structure

```python
@dataclass
class ExecutionPlan:
    pipeline_path: PipelinePath     # simple, standard, deep, viz_only
    agents_to_call: list[str]       # ["sql", "analyst", "writer"]
    analyst_model: str              # "sonnet" or "opus"
    needs_visualization: bool       # Generate chart?
    skip_validation: bool           # Skip FERPA check? (simple queries)
    context_notes: str              # Relevant context for agents
    reasoning: str                  # Why this plan was chosen
```

## Agent Details

### Planner Agent

**Purpose**: Analyze query intent and create execution plan

**Model**: Claude Opus (deep reasoning)

**Input**: User query + conversation context

**Output**: ExecutionPlan

**Decision factors**:
- Query complexity (keywords, structure)
- Previous conversation context
- Data requirements
- Visualization needs

### SQL Agent

**Purpose**: Generate and execute SQL queries

**Model**: Claude Sonnet + Snowflake MCP

**Input**: Natural language query

**Output**: SQLResult with data, columns, row count

**Capabilities**:
- Schema-aware SQL generation
- FERPA-safe column selection
- Query optimization

### Analyst Agent

**Purpose**: Interpret data and find insights

**Model**: Claude Sonnet (standard) or Opus (deep analysis)

**Input**: Query + raw data from SQL

**Output**: AnalysisResult with insights, statistics, trends

**Capabilities**:
- Statistical analysis
- Pattern recognition
- Visualization suggestions
- Educational context

### Writer Agent

**Purpose**: Craft natural language responses

**Model**: Claude Sonnet

**Input**: Query + data + analysis

**Output**: WriteResult with text, artifacts, follow-ups

**Capabilities**:
- Clear, concise prose
- Data table formatting
- Follow-up question generation

### Validator Agent

**Purpose**: Ensure FERPA compliance

**Model**: Claude Sonnet

**Input**: Query + response + SQL

**Output**: Validation result (pass/fail + issues)

**Checks**:
- PII exposure
- Individual student data
- Minimum aggregation (5 students)
- SQL safety

## Snowflake MCP Integration

Agents access Snowflake via the Model Context Protocol:

```
Strands Agent → MCPClient → snowflake-labs-mcp → Snowflake
```

**Available tools**:
- `read_query(sql)` - Execute SELECT queries
- `list_tables(schema)` - List available tables
- `describe_table(name)` - Get column information

**Mock mode** (`ILLUMINATE_MOCK_MODE=true`):
- Uses sample data for development
- No Snowflake connection required
- Same tool interface

## Streaming Events

The system emits events during processing for real-time UI feedback:

| Event | When | Data |
|-------|------|------|
| `status` | Status update | `{message: string}` |
| `thinking` | Agent processing | `{agent, content}` |
| `planning` | Plan created | `{plan: ExecutionPlan}` |
| `sql_complete` | SQL finished | `{row_count, execution_time_ms}` |
| `analysis_complete` | Analysis done | `{agent}` |
| `complete` | Final response | `{text, artifacts, followups}` |

## Context Management

Conversation context enables multi-turn interactions:

```python
@dataclass
class ConversationContext:
    id: str                      # Session identifier
    messages: list[Message]      # Conversation history
    metadata: dict               # Session metadata
```

**Context features**:
- Follow-up question handling ("Chart that")
- Reference to previous data
- Session isolation

## Data Domain

Currently focused on **CDM_LMS** (Blackboard Learn):

| Table | Description |
|-------|-------------|
| COURSE | Course catalog |
| PERSON_COURSE | Enrollments |
| GRADE | Grade records |
| ASSIGNMENT | Assignments |

## Extension Points

### Adding New Agents

1. Create agent in `agents/<name>/agent.py`
2. Implement `analyze()` or `handle_query()` method
3. Register in orchestrator's agent map
4. Update Planner's system prompt

### Adding Pipeline Paths

1. Add to `PipelinePath` enum
2. Update Planner's decision logic
3. Implement path in Orchestrator

### Adding Data Domains

1. Add mock data in `snowflake_mcp.py`
2. Update SQL Agent's schema knowledge
3. Add to Planner's routing logic
