"""
Writer Agent - Crafts natural language responses.

Receives data and analysis to produce:
- Clear, concise answers
- Formatted data tables
- Suggested follow-up questions
"""
from agents.writer.agent import WriterAgent, get_writer_agent, write

__all__ = ["WriterAgent", "get_writer_agent", "write"]
