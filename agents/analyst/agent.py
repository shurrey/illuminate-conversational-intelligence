"""
Analyst Agent - Interprets data and generates insights.

This agent receives raw query results and:
- Identifies patterns and trends
- Computes statistics
- Generates insights and recommendations
- Suggests appropriate visualizations

Model: Sonnet by default, Opus for complex analysis (selected by Planner)
"""
import logging
import json
from typing import Any, Optional, AsyncGenerator

from agents.shared.models import AnalysisResult
from agents.shared.llm_client import get_orchestrator_llm, get_worker_llm

logger = logging.getLogger("ANALYST")

# System prompt for analysis
ANALYST_SYSTEM_PROMPT = """You are the Analyst Agent for an educational data analytics system.
Your job is to interpret data and generate insights.

## Your Role
You receive:
1. The user's original question
2. Raw data from a SQL query (as a table)
3. Column information

You must:
1. Analyze the data to answer the user's question
2. Identify key patterns, trends, or anomalies
3. Compute relevant statistics
4. Generate actionable insights
5. Suggest appropriate visualizations

## Response Format
Return a JSON object with this structure:
{
    "key_insights": [
        "First major insight about the data",
        "Second insight",
        "Third insight"
    ],
    "statistics": {
        "total": 100,
        "average": 3.45,
        "min": 1.2,
        "max": 4.0
    },
    "trends": [
        {"description": "Upward trend in...", "strength": "strong"}
    ],
    "anomalies": [
        {"description": "Department X is unusually low", "severity": "medium"}
    ],
    "recommendations": [
        "Consider focusing on..."
    ],
    "educational_context": "In the context of academic performance, these results suggest...",
    "visualization_suggestion": {
        "chart_type": "bar",
        "title": "Average GPA by Department",
        "x_axis": "DEPARTMENT",
        "y_axis": "AVG_GPA"
    }
}

## Analysis Guidelines
- Focus on answering the user's specific question first
- Highlight the most important findings
- Put numbers in context (is 3.2 GPA good or bad?)
- For educational data, consider semester timing, cohort effects, etc.
- Only suggest visualizations when the data is suitable for charts

## Visualization Types
- **bar**: Comparing categories (departments, terms)
- **line**: Trends over time (enrollment by semester)
- **pie**: Proportions of a whole (grade distribution)
- **scatter**: Correlations between variables
- **heatmap**: Patterns across two dimensions

Be concise but thorough. Focus on actionable insights.
"""


class AnalystAgent:
    """
    Analyzes data and generates insights.

    Supports model selection:
    - "sonnet": Fast analysis for simple queries
    - "opus": Deep analysis for complex patterns
    """

    def __init__(self):
        logger.info("Analyst Agent initialized")

    async def analyze(
        self,
        user_query: str,
        data: list[dict[str, Any]],
        columns: list[str],
        model: str = "sonnet"
    ) -> AnalysisResult:
        """
        Analyze data and generate insights.

        Args:
            user_query: Original user question
            data: Query result data (list of row dicts)
            columns: Column names
            model: "sonnet" or "opus"

        Returns:
            AnalysisResult with insights and recommendations
        """
        logger.info(f"Analyzing {len(data)} rows with {model} model")

        # Select LLM based on model parameter
        if model == "opus":
            llm = get_worker_llm(caller="ANALYST")
        else:
            llm = get_orchestrator_llm(caller="ANALYST")

        # Format data for analysis
        data_table = self._format_data_as_table(data, columns)

        user_prompt = f"""Analyze this data to answer the user's question.

USER QUESTION: {user_query}

DATA ({len(data)} rows):
{data_table}

COLUMNS: {', '.join(columns)}

Provide your analysis as JSON."""

        try:
            result = await llm.invoke_with_json_response(
                system_prompt=ANALYST_SYSTEM_PROMPT,
                user_message=user_prompt,
                temperature=0.3
            )

            return self._parse_analysis(result)

        except Exception as e:
            logger.error(f"Analysis failed: {e}")
            # Return a minimal analysis
            return AnalysisResult(
                key_insights=[f"Data contains {len(data)} rows"],
                statistics={"row_count": len(data)},
                educational_context=f"Analysis error: {e}"
            )

    async def analyze_streaming(
        self,
        user_query: str,
        data: list[dict[str, Any]],
        columns: list[str],
        model: str = "sonnet"
    ) -> AsyncGenerator[dict, None]:
        """
        Analyze data with streaming events.

        Yields progress events, then final result.
        """
        yield {
            "type": "thinking",
            "agent": "analyst",
            "content": f"Analyzing {len(data)} rows of data..."
        }

        result = await self.analyze(user_query, data, columns, model)

        yield {
            "type": "analysis_complete",
            "agent": "analyst",
            "analysis": result.to_dict()
        }

    def _format_data_as_table(
        self,
        data: list[dict[str, Any]],
        columns: list[str],
        max_rows: int = 50
    ) -> str:
        """Format data as markdown table for LLM."""
        if not data:
            return "(No data)"

        # Use provided columns or extract from first row
        if not columns and data:
            columns = list(data[0].keys())

        # Build header
        lines = [
            "| " + " | ".join(columns) + " |",
            "| " + " | ".join(["---"] * len(columns)) + " |"
        ]

        # Add rows (limit to max_rows)
        for row in data[:max_rows]:
            values = [str(row.get(col, "")) for col in columns]
            lines.append("| " + " | ".join(values) + " |")

        if len(data) > max_rows:
            lines.append(f"... and {len(data) - max_rows} more rows")

        return "\n".join(lines)

    def _parse_analysis(self, result: dict) -> AnalysisResult:
        """Parse LLM response into AnalysisResult."""
        return AnalysisResult(
            key_insights=result.get("key_insights", []),
            statistics=result.get("statistics", {}),
            trends=result.get("trends", []),
            anomalies=result.get("anomalies", []),
            recommendations=result.get("recommendations", []),
            educational_context=result.get("educational_context", ""),
            visualization_suggestion=result.get("visualization_suggestion")
        )


# Singleton instance
_analyst_agent: Optional[AnalystAgent] = None


def get_analyst_agent() -> AnalystAgent:
    """Get or create the singleton Analyst Agent instance."""
    global _analyst_agent
    if _analyst_agent is None:
        _analyst_agent = AnalystAgent()
    return _analyst_agent


async def analyze(
    user_query: str,
    data: list[dict[str, Any]],
    columns: list[str],
    model: str = "sonnet"
) -> AnalysisResult:
    """Convenience function to analyze data."""
    agent = get_analyst_agent()
    return await agent.analyze(user_query, data, columns, model)
