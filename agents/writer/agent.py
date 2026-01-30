"""
Writer Agent - Crafts natural language responses.

This agent receives:
- User's original question
- Raw data from SQL Agent
- Analysis from Analyst Agent

And produces:
- Clear, conversational response
- Formatted data tables as artifacts
- Suggested follow-up questions

Model: Claude Sonnet 4 (clear writing)
"""
import logging
import uuid
from typing import Any, Optional, AsyncGenerator

from agents.shared.models import WriteResult, Artifact, ArtifactType, AnalysisResult
from agents.shared.llm_client import get_orchestrator_llm

logger = logging.getLogger("WRITER")

# System prompt for the Writer Agent
WRITER_SYSTEM_PROMPT = """You are the Writer Agent for an educational data analytics system.
Your job is to craft clear, helpful responses for users.

## Your Role
You receive:
1. The user's original question
2. Raw data from the database
3. Analysis and insights from the Analyst

You must:
1. Write a clear, conversational response
2. Answer the user's specific question directly
3. Include key insights naturally
4. Format data appropriately
5. Suggest helpful follow-up questions

## Response Guidelines
- Start with a direct answer to the question
- Use natural language, not technical jargon
- Reference specific numbers from the data
- Keep it concise but complete
- End with 2-3 suggested follow-up questions

## Data Formatting
- For small datasets (< 10 rows): Include as markdown table in response
- For larger datasets: Summarize key points, mention full data is available
- Always mention the row count

## Tone
- Professional but friendly
- Confident but not arrogant
- Helpful and proactive

## Example Structure
```
[Direct answer to the question]

[Key findings with specific numbers]

[Brief interpretation/context]

**You might also want to know:**
- [Follow-up question 1]
- [Follow-up question 2]
```

Do NOT return JSON. Write natural prose.
"""


class WriterAgent:
    """
    Crafts natural language responses from data and analysis.
    """

    def __init__(self):
        self._llm = get_orchestrator_llm(caller="WRITER")
        logger.info("Writer Agent initialized")

    async def write(
        self,
        user_query: str,
        data: list[dict[str, Any]],
        columns: list[str],
        analysis: Optional[AnalysisResult] = None
    ) -> WriteResult:
        """
        Craft a response from data and analysis.

        Args:
            user_query: Original user question
            data: Query result data
            columns: Column names
            analysis: Optional analysis from Analyst Agent

        Returns:
            WriteResult with text, artifacts, and follow-ups
        """
        logger.info(f"Writing response for {len(data)} rows")

        # Format data for the prompt
        data_summary = self._format_data_summary(data, columns)

        # Format analysis if available
        analysis_text = ""
        if analysis:
            analysis_text = self._format_analysis(analysis)

        user_prompt = f"""Write a response for this user question.

USER QUESTION: {user_query}

DATA SUMMARY ({len(data)} rows):
{data_summary}

{analysis_text}

Write a helpful, natural response."""

        try:
            response = await self._llm.invoke(
                system_prompt=WRITER_SYSTEM_PROMPT,
                user_message=user_prompt,
                temperature=0.5  # Some creativity for writing
            )

            # Create artifacts
            artifacts = []

            # Add table artifact if we have data
            if data:
                table_artifact = Artifact(
                    id=str(uuid.uuid4()),
                    type=ArtifactType.TABLE,
                    data={"rows": data, "columns": columns},
                    title="Query Results"
                )
                artifacts.append(table_artifact)

            # Extract follow-up suggestions from response
            followups = self._extract_followups(response)

            return WriteResult(
                text=response,
                artifacts=artifacts,
                suggested_followups=followups
            )

        except Exception as e:
            logger.error(f"Writing failed: {e}")
            # Return a basic response
            return WriteResult(
                text=f"Here are the results for your query. Found {len(data)} rows of data.",
                artifacts=[
                    Artifact(
                        id=str(uuid.uuid4()),
                        type=ArtifactType.TABLE,
                        data={"rows": data, "columns": columns},
                        title="Query Results"
                    )
                ] if data else [],
                suggested_followups=[]
            )

    async def write_streaming(
        self,
        user_query: str,
        data: list[dict[str, Any]],
        columns: list[str],
        analysis: Optional[AnalysisResult] = None
    ) -> AsyncGenerator[dict, None]:
        """
        Write response with streaming events.
        """
        yield {
            "type": "thinking",
            "agent": "writer",
            "content": "Composing response..."
        }

        result = await self.write(user_query, data, columns, analysis)

        yield {
            "type": "write_complete",
            "agent": "writer",
            "result": result.to_dict()
        }

    def _format_data_summary(
        self,
        data: list[dict[str, Any]],
        columns: list[str],
        max_rows: int = 20
    ) -> str:
        """Format data for the LLM prompt."""
        if not data:
            return "(No data returned)"

        # For small datasets, show all data
        if len(data) <= max_rows:
            return self._format_as_table(data, columns)

        # For larger datasets, show sample + summary
        lines = [
            f"Total rows: {len(data)}",
            "",
            "First few rows:",
            self._format_as_table(data[:10], columns),
            "",
            "Last few rows:",
            self._format_as_table(data[-5:], columns)
        ]
        return "\n".join(lines)

    def _format_as_table(
        self,
        data: list[dict[str, Any]],
        columns: list[str]
    ) -> str:
        """Format data as markdown table."""
        if not data:
            return ""

        if not columns and data:
            columns = list(data[0].keys())

        lines = [
            "| " + " | ".join(columns) + " |",
            "| " + " | ".join(["---"] * len(columns)) + " |"
        ]

        for row in data:
            values = [str(row.get(col, ""))[:50] for col in columns]
            lines.append("| " + " | ".join(values) + " |")

        return "\n".join(lines)

    def _format_analysis(self, analysis: AnalysisResult) -> str:
        """Format analysis for the prompt."""
        lines = ["ANALYSIS:"]

        if analysis.key_insights:
            lines.append("Key Insights:")
            for insight in analysis.key_insights:
                lines.append(f"- {insight}")

        if analysis.statistics:
            lines.append(f"Statistics: {analysis.statistics}")

        if analysis.recommendations:
            lines.append("Recommendations:")
            for rec in analysis.recommendations:
                lines.append(f"- {rec}")

        if analysis.educational_context:
            lines.append(f"Context: {analysis.educational_context}")

        return "\n".join(lines)

    def _extract_followups(self, response: str) -> list[str]:
        """Extract follow-up suggestions from response."""
        followups = []

        # Look for common patterns
        patterns = [
            "You might also want to know:",
            "You may also want to:",
            "Follow-up questions:",
            "You could also ask:",
        ]

        for pattern in patterns:
            if pattern.lower() in response.lower():
                # Find the section and extract bullet points
                idx = response.lower().find(pattern.lower())
                section = response[idx + len(pattern):]

                # Extract lines starting with - or *
                for line in section.split("\n"):
                    line = line.strip()
                    if line.startswith("- ") or line.startswith("* "):
                        followups.append(line[2:].strip())
                    elif line.startswith("1.") or line.startswith("2.") or line.startswith("3."):
                        followups.append(line[2:].strip())

                break

        return followups[:3]  # Limit to 3


# Singleton instance
_writer_agent: Optional[WriterAgent] = None


def get_writer_agent() -> WriterAgent:
    """Get or create the singleton Writer Agent instance."""
    global _writer_agent
    if _writer_agent is None:
        _writer_agent = WriterAgent()
    return _writer_agent


async def write(
    user_query: str,
    data: list[dict[str, Any]],
    columns: list[str],
    analysis: Optional[AnalysisResult] = None
) -> WriteResult:
    """Convenience function to write a response."""
    agent = get_writer_agent()
    return await agent.write(user_query, data, columns, analysis)
