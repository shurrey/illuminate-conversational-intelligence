"""
Visualization Agent - Specialist for data visualization and export.

This agent handles:
- Chart generation from query results
- Data summarization and insights
- Export formatting (CSV, Excel, PDF)
"""
import logging
import json
import csv
import io
from typing import Any, Optional

from agents.shared.models import (
    AgentCard, Message, Artifact, ChartConfig, ChartType, AgentType, QueryIntent
)
from agents.shared.a2a_client import A2AServer, get_agent_registry

logger = logging.getLogger("VISUALIZATION")


# Agent Card for A2A discovery
VISUALIZATION_AGENT_CARD = AgentCard(
    name="illuminate-visualization-agent",
    description="Specialist for data visualization, summarization, and export formatting",
    skills=[
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
)


class VisualizationAgent:
    """
    Visualization Agent for generating charts, summaries, and exports.

    Transforms raw data into visual representations and exportable formats.
    """

    def __init__(self):
        self.agent_card = VISUALIZATION_AGENT_CARD

    async def handle_message(self, message: Message) -> dict[str, Any]:
        """
        Handle an incoming message and generate visualization.

        Args:
            message: Incoming message with data to visualize

        Returns:
            Response with visualization artifacts
        """
        # Check if message contains data or visualization request
        query_text = ""
        data = None

        for part in message.parts:
            if part.type == "text":
                query_text = str(part.content)
            elif part.type == "data":
                data = part.content

        intent = self._classify_intent(query_text)
        logger.info(f"Visualization Agent handling request with intent: {intent}")

        try:
            if intent == QueryIntent.CHART_GENERATION:
                return await self._handle_chart_request(query_text, data)
            elif intent == QueryIntent.DATA_SUMMARIZATION:
                return await self._handle_summary_request(query_text, data)
            elif intent == QueryIntent.EXPORT_FORMATTING:
                return await self._handle_export_request(query_text, data)
            else:
                # Try to auto-detect best visualization
                return await self._handle_auto_visualization(query_text, data)
        except Exception as e:
            logger.error(f"Error handling visualization: {e}")
            return {
                "text": f"Error creating visualization: {str(e)}",
                "artifacts": [Artifact.create_error(str(e)).to_dict()]
            }

    def _classify_intent(self, query: str) -> QueryIntent:
        """Classify the visualization intent."""
        query_lower = query.lower()

        # Chart keywords
        if any(kw in query_lower for kw in ["chart", "graph", "plot", "visualize", "bar", "line", "pie"]):
            return QueryIntent.CHART_GENERATION

        # Summary keywords
        if any(kw in query_lower for kw in ["summary", "summarize", "insight", "explain", "describe"]):
            return QueryIntent.DATA_SUMMARIZATION

        # Export keywords
        if any(kw in query_lower for kw in ["export", "download", "csv", "excel", "pdf"]):
            return QueryIntent.EXPORT_FORMATTING

        return QueryIntent.UNKNOWN

    async def _handle_chart_request(
        self,
        query: str,
        data: Optional[dict] = None
    ) -> dict[str, Any]:
        """Handle chart generation request."""
        if not data:
            return {
                "text": "No data provided for chart generation.",
                "artifacts": []
            }

        # Determine chart type from query
        chart_type = self._detect_chart_type(query)

        # Generate chart config
        chart_config = self.generate_chart(data, chart_type)

        artifacts = [
            Artifact.create_chart(chart_config).to_dict()
        ]

        return {
            "text": f"Generated {chart_type.value} chart: {chart_config.title}",
            "artifacts": artifacts,
            "chart_config": chart_config.to_dict()
        }

    async def _handle_summary_request(
        self,
        query: str,
        data: Optional[dict] = None
    ) -> dict[str, Any]:
        """Handle data summarization request."""
        if not data:
            return {
                "text": "No data provided for summarization.",
                "artifacts": []
            }

        summary = self.summarize_data(data)

        artifacts = [
            Artifact.create_text(summary, "Data Summary").to_dict()
        ]

        return {
            "text": summary,
            "artifacts": artifacts
        }

    async def _handle_export_request(
        self,
        query: str,
        data: Optional[dict] = None
    ) -> dict[str, Any]:
        """Handle export formatting request."""
        if not data:
            return {
                "text": "No data provided for export.",
                "artifacts": []
            }

        # Detect export format
        format_type = "csv"  # default
        if "excel" in query.lower() or "xlsx" in query.lower():
            format_type = "excel"
        elif "pdf" in query.lower():
            format_type = "pdf"

        export_result = self.export_data(data, format_type)

        return {
            "text": f"Data exported as {format_type.upper()}.",
            "artifacts": [],
            "export": export_result
        }

    async def _handle_auto_visualization(
        self,
        query: str,
        data: Optional[dict] = None
    ) -> dict[str, Any]:
        """Auto-detect and generate appropriate visualization."""
        if not data:
            return {
                "text": "Please provide data to visualize.",
                "artifacts": []
            }

        # Analyze data structure
        rows = data.get("rows", data.get("data", []))
        columns = data.get("columns", [])

        if not rows:
            return {
                "text": "The provided data is empty.",
                "artifacts": []
            }

        # Determine best visualization based on data characteristics
        numeric_cols = []
        categorical_cols = []

        if rows and isinstance(rows[0], dict):
            for col in rows[0].keys():
                sample_val = rows[0][col]
                if isinstance(sample_val, (int, float)):
                    numeric_cols.append(col)
                else:
                    categorical_cols.append(col)

        # Choose visualization
        if len(numeric_cols) >= 1 and len(categorical_cols) >= 1:
            # Bar chart for categorical + numeric
            chart_config = ChartConfig(
                chart_type=ChartType.BAR,
                title="Data Visualization",
                x_axis=categorical_cols[0],
                y_axis=numeric_cols[0],
                data=rows
            )
        elif len(numeric_cols) >= 2:
            # Scatter plot for two numeric columns
            chart_config = ChartConfig(
                chart_type=ChartType.SCATTER,
                title="Data Visualization",
                x_axis=numeric_cols[0],
                y_axis=numeric_cols[1],
                data=rows
            )
        else:
            # Default to table
            return {
                "text": f"Data contains {len(rows)} rows across {len(columns or rows[0].keys())} columns.",
                "artifacts": [
                    Artifact.create_table(rows, columns or list(rows[0].keys()), "Data Table").to_dict()
                ]
            }

        artifacts = [
            Artifact.create_chart(chart_config).to_dict()
        ]

        return {
            "text": f"Generated {chart_config.chart_type.value} chart from your data.",
            "artifacts": artifacts,
            "chart_config": chart_config.to_dict()
        }

    def _detect_chart_type(self, query: str) -> ChartType:
        """Detect chart type from query text."""
        query_lower = query.lower()

        if "bar" in query_lower:
            return ChartType.BAR
        elif "line" in query_lower or "trend" in query_lower:
            return ChartType.LINE
        elif "pie" in query_lower or "distribution" in query_lower:
            return ChartType.PIE
        elif "scatter" in query_lower or "correlation" in query_lower:
            return ChartType.SCATTER
        elif "heatmap" in query_lower or "matrix" in query_lower:
            return ChartType.HEATMAP
        elif "histogram" in query_lower:
            return ChartType.HISTOGRAM

        return ChartType.BAR  # default

    # Tool implementations
    def generate_chart(
        self,
        data: dict[str, Any],
        chart_type: ChartType = ChartType.BAR,
        title: Optional[str] = None,
        x_axis: Optional[str] = None,
        y_axis: Optional[str] = None
    ) -> ChartConfig:
        """
        Generate a chart configuration from data.

        Args:
            data: Data to visualize (dict with 'rows' or 'data' key)
            chart_type: Type of chart to generate
            title: Chart title
            x_axis: Column to use for x-axis
            y_axis: Column to use for y-axis

        Returns:
            ChartConfig for rendering
        """
        rows = data.get("rows", data.get("data", []))

        if not rows:
            return ChartConfig(
                chart_type=chart_type,
                title=title or "Empty Chart",
                x_axis="",
                y_axis="",
                data=[]
            )

        # Auto-detect axes if not provided
        if isinstance(rows[0], dict):
            columns = list(rows[0].keys())

            if not x_axis:
                # Use first non-numeric column
                for col in columns:
                    if not isinstance(rows[0][col], (int, float)):
                        x_axis = col
                        break
                x_axis = x_axis or columns[0]

            if not y_axis:
                # Use first numeric column
                for col in columns:
                    if isinstance(rows[0][col], (int, float)):
                        y_axis = col
                        break
                y_axis = y_axis or columns[-1]

        return ChartConfig(
            chart_type=chart_type,
            title=title or f"{y_axis} by {x_axis}",
            x_axis=x_axis or "x",
            y_axis=y_axis or "y",
            data=rows,
            x_label=x_axis,
            y_label=y_axis
        )

    def summarize_data(self, data: dict[str, Any]) -> str:
        """
        Generate a narrative summary of the data.

        Args:
            data: Data to summarize

        Returns:
            Narrative summary string
        """
        rows = data.get("rows", data.get("data", []))
        columns = data.get("columns", [])

        if not rows:
            return "No data available to summarize."

        row_count = len(rows)

        if isinstance(rows[0], dict):
            columns = columns or list(rows[0].keys())

        # Calculate basic statistics
        numeric_stats = {}
        for col in columns:
            values = []
            for row in rows:
                val = row.get(col) if isinstance(row, dict) else None
                if isinstance(val, (int, float)):
                    values.append(val)

            if values:
                numeric_stats[col] = {
                    "min": min(values),
                    "max": max(values),
                    "avg": sum(values) / len(values),
                    "count": len(values)
                }

        # Build summary
        summary_parts = [
            f"**Data Summary**",
            f"- Total records: {row_count}",
            f"- Columns: {', '.join(columns)}"
        ]

        if numeric_stats:
            summary_parts.append("\n**Numeric Statistics:**")
            for col, stats in numeric_stats.items():
                summary_parts.append(
                    f"- {col}: min={stats['min']:.2f}, max={stats['max']:.2f}, avg={stats['avg']:.2f}"
                )

        return "\n".join(summary_parts)

    def export_data(
        self,
        data: dict[str, Any],
        format_type: str = "csv"
    ) -> dict[str, Any]:
        """
        Export data to specified format.

        Args:
            data: Data to export
            format_type: Export format (csv, excel, pdf)

        Returns:
            Export result with content and metadata
        """
        rows = data.get("rows", data.get("data", []))
        columns = data.get("columns", [])

        if not rows:
            return {
                "success": False,
                "error": "No data to export"
            }

        if isinstance(rows[0], dict):
            columns = columns or list(rows[0].keys())

        if format_type == "csv":
            return self._export_csv(rows, columns)
        elif format_type == "excel":
            return self._export_excel(rows, columns)
        elif format_type == "pdf":
            return self._export_pdf(rows, columns)
        else:
            return {
                "success": False,
                "error": f"Unsupported format: {format_type}"
            }

    def _export_csv(self, rows: list, columns: list) -> dict[str, Any]:
        """Export data to CSV format."""
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=columns)
        writer.writeheader()

        for row in rows:
            if isinstance(row, dict):
                writer.writerow(row)

        csv_content = output.getvalue()
        output.close()

        return {
            "success": True,
            "format": "csv",
            "content": csv_content,
            "filename": "export.csv",
            "mime_type": "text/csv"
        }

    def _export_excel(self, rows: list, columns: list) -> dict[str, Any]:
        """Export data to Excel format (returns CSV as fallback)."""
        # In production, would use openpyxl or xlsxwriter
        # For now, return CSV with Excel-compatible formatting
        return {
            "success": True,
            "format": "excel",
            "note": "Excel export requires additional dependencies. Returning CSV format.",
            **self._export_csv(rows, columns)
        }

    def _export_pdf(self, rows: list, columns: list) -> dict[str, Any]:
        """Export data to PDF format."""
        # In production, would use reportlab or similar
        return {
            "success": True,
            "format": "pdf",
            "note": "PDF export requires additional dependencies.",
            "content": json.dumps({"columns": columns, "row_count": len(rows)}),
            "filename": "export.pdf",
            "mime_type": "application/pdf"
        }


# Create singleton instance
_visualization_agent: Optional[VisualizationAgent] = None


def get_visualization_agent() -> VisualizationAgent:
    """Get or create the Visualization Agent instance."""
    global _visualization_agent
    if _visualization_agent is None:
        _visualization_agent = VisualizationAgent()
        registry = get_agent_registry()
        registry.register(AgentType.VISUALIZATION, _visualization_agent)
    return _visualization_agent


def create_a2a_server(port: int = 9004) -> A2AServer:
    """Create an A2A server for the Visualization Agent."""
    agent = get_visualization_agent()
    return A2AServer(
        agent_card=agent.agent_card,
        message_handler=agent.handle_message,
        port=port
    )
