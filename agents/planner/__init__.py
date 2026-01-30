"""
Planner Agent - Creates execution plans for query processing.

Uses Opus model for deep reasoning about:
- Query intent and complexity
- Which agents to involve
- Pipeline path selection
- Model selection for downstream agents
"""
from agents.planner.agent import PlannerAgent, get_planner_agent, create_plan

__all__ = ["PlannerAgent", "get_planner_agent", "create_plan"]
