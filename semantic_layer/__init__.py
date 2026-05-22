"""Illuminate semantic layer — canonical metric catalog + Snowflake SQL compiler.

Ported from github.com/shurrey/illuminate-semantic-layer-prototype. Adapted for:
- Snowflake dialect (sqlglot read='snowflake')
- Database name injected as Jinja variable
- CDM_LMS allowed-tables list

No Anthropic SDK dependency; the planner is the outer Bedrock Converse loop
in chat_engine.py, which uses tool_use to commit to a metric_id.
"""

__version__ = "0.1.0"
