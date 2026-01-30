"""
Planner Agent - Creates execution plans for query processing.

Uses Opus model for deep reasoning about query complexity and pipeline selection.
Called once per query to create the execution plan, which is then executed by Orchestrator.
"""

import logging
from typing import Optional, AsyncGenerator

from agents.shared.models import (
    ExecutionPlan, PipelinePath, ConversationContext
)
from agents.shared.llm_client import get_worker_llm

logger = logging.getLogger("PLANNER")

# System prompt for the Planner Agent
PLANNER_SYSTEM_PROMPT = """You are the Planner Agent for an educational data analytics system.
Your job is to analyze user queries and create execution plans.

## Your Role
You receive a user's natural language question about educational data and must decide:
1. Which pipeline path to use (simple, standard, deep analysis, or visualization-only)
2. Which agents need to be involved
3. What model the Analyst should use (Sonnet for simple, Opus for complex)
4. Whether visualization is needed
5. Whether validation can be skipped (for simple queries)

## Pipeline Paths
- SIMPLE: For basic counts, lookups, or single aggregations. Skip analysis, just format the SQL result.
- STANDARD: For most analytical queries. SQL → Analyst → Writer.
- DEEP_ANALYSIS: For complex analysis (trends, predictions, comparisons). Use Opus for Analyst.
- VIZ_ONLY: When user wants to visualize data already retrieved in the conversation.

## Available Data
The system has access to CDM_LMS (Blackboard Learn data):
- Courses, enrollments, grades, assignments
- Student-course relationships
- Academic performance data

## Response Format
Return a JSON object with this structure:
{
    "pipeline_path": "simple" | "standard" | "deep" | "viz_only",
    "agents_to_call": ["sql", "analyst", "writer"],  // List of agents needed
    "analyst_model": "sonnet" | "opus",  // Which model for analyst
    "needs_visualization": true | false,
    "skip_validation": true | false,  // True for simple, trusted queries
    "context_notes": "Any relevant context from conversation history",
    "reasoning": "Brief explanation of why this plan was chosen"
}

## Decision Guidelines
- Use SIMPLE for: "How many courses?", "List all departments", "What is the total enrollment?"
- Use STANDARD for: "What is the average GPA by department?", "Show grade distribution"
- Use DEEP_ANALYSIS for: "What trends do you see?", "Compare performance across terms", "Predict..."
- Use VIZ_ONLY for: "Chart that", "Show that as a graph", "Visualize the data"

Be concise but accurate. The plan will be executed by other agents.
"""


class PlannerAgent:
    """
    Creates execution plans for query processing.

    Uses Opus model for deep reasoning about:
    - Query intent and complexity
    - Pipeline path selection
    - Agent and model selection
    """

    def __init__(self):
        self._llm = get_worker_llm(caller="PLANNER")
        logger.info("Planner Agent initialized")

    async def create_plan(
        self,
        query: str,
        context: Optional[ConversationContext] = None
    ) -> ExecutionPlan:
        """
        Create an execution plan for the given query.

        Args:
            query: User's natural language question
            context: Optional conversation context for follow-ups

        Returns:
            ExecutionPlan with pipeline path, agents, and settings
        """
        logger.info(f"Creating plan for query: {query[:100]}...")

        # Build context summary for follow-up awareness
        context_summary = self._build_context_summary(context)

        # Create the planning prompt
        user_prompt = f"""Create an execution plan for this query:

USER QUERY: {query}

{context_summary}

Return your plan as JSON."""

        try:
            result = await self._llm.invoke_with_json_response(
                system_prompt=PLANNER_SYSTEM_PROMPT,
                user_message=user_prompt,
                temperature=0.2  # Low temperature for consistent planning
            )

            # Parse the plan
            plan = self._parse_plan(result)
            logger.info(f"Plan created: path={plan.pipeline_path.value}, agents={plan.agents_to_call}")

            return plan

        except Exception as e:
            logger.error(f"Planning failed: {e}")
            # Return a safe default plan
            return ExecutionPlan(
                pipeline_path=PipelinePath.STANDARD,
                agents_to_call=["sql", "analyst", "writer"],
                analyst_model="sonnet",
                needs_visualization=False,
                skip_validation=False,
                context_notes="",
                reasoning=f"Default plan due to error: {e}"
            )

    async def create_plan_streaming(
        self,
        query: str,
        context: Optional[ConversationContext] = None
    ) -> AsyncGenerator[dict, None]:
        """
        Create plan with streaming events for UI feedback.

        Yields events during planning, then returns final plan.
        """
        yield {
            "type": "thinking",
            "agent": "planner",
            "content": "Analyzing query complexity and requirements..."
        }

        plan = await self.create_plan(query, context)

        yield {
            "type": "planning",
            "agent": "planner",
            "plan": plan.to_dict(),
            "content": f"Plan: {plan.reasoning}"
        }

        yield {
            "type": "plan_complete",
            "agent": "planner",
            "plan": plan.to_dict()
        }

    def _build_context_summary(self, context: Optional[ConversationContext]) -> str:
        """Build a summary of conversation context for planning."""
        if not context or not context.messages:
            return "CONTEXT: No previous conversation."

        # Get last few exchanges
        recent_messages = context.messages[-6:]  # Last 3 exchanges

        # Check for recent data artifacts
        has_data = False
        for msg in reversed(context.messages):
            if msg.artifacts:
                for artifact in msg.artifacts:
                    # Handle both dict and Artifact objects
                    if isinstance(artifact, dict):
                        artifact_type = artifact.get("type", "")
                    else:
                        artifact_type = artifact.type.value if hasattr(artifact.type, 'value') else str(artifact.type)
                    if artifact_type == "table":
                        has_data = True
                        break
                if has_data:
                    break

        context_lines = ["CONTEXT:"]
        for msg in recent_messages:
            role = msg.role.value.upper()
            text = ""
            for part in msg.parts:
                if part.type == "text":
                    text = str(part.content)[:200]
                    break
            context_lines.append(f"- {role}: {text}")

        if has_data:
            context_lines.append("- Previous response contains data table(s)")

        return "\n".join(context_lines)

    def _parse_plan(self, result: dict) -> ExecutionPlan:
        """Parse LLM response into ExecutionPlan."""
        # Parse pipeline path
        path_str = result.get("pipeline_path", "standard").lower()
        path_map = {
            "simple": PipelinePath.SIMPLE,
            "standard": PipelinePath.STANDARD,
            "deep": PipelinePath.DEEP_ANALYSIS,
            "deep_analysis": PipelinePath.DEEP_ANALYSIS,
            "viz_only": PipelinePath.VIZ_ONLY,
            "visualization_only": PipelinePath.VIZ_ONLY,
            "clarification": PipelinePath.CLARIFICATION
        }
        pipeline_path = path_map.get(path_str, PipelinePath.STANDARD)

        return ExecutionPlan(
            pipeline_path=pipeline_path,
            agents_to_call=result.get("agents_to_call", ["sql", "analyst", "writer"]),
            analyst_model=result.get("analyst_model", "sonnet"),
            needs_visualization=result.get("needs_visualization", False),
            skip_validation=result.get("skip_validation", False),
            context_notes=result.get("context_notes", ""),
            reasoning=result.get("reasoning", "")
        )


# Singleton instance
_planner_agent: Optional[PlannerAgent] = None


def get_planner_agent() -> PlannerAgent:
    """Get or create the singleton Planner Agent instance."""
    global _planner_agent
    if _planner_agent is None:
        _planner_agent = PlannerAgent()
    return _planner_agent


async def create_plan(
    query: str,
    context: Optional[ConversationContext] = None
) -> ExecutionPlan:
    """Convenience function to create an execution plan."""
    agent = get_planner_agent()
    return await agent.create_plan(query, context)
