"""
Analyst Agent - Interprets data and generates insights.

Receives raw query results from SQL Agent and:
- Identifies patterns and trends
- Computes statistics
- Generates insights and recommendations
- Suggests visualizations
"""
from agents.analyst.agent import AnalystAgent, get_analyst_agent, analyze

__all__ = ["AnalystAgent", "get_analyst_agent", "analyze"]
