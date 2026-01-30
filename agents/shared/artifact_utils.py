"""
Shared utilities for extracting artifacts from Strands AgentResults.

These utilities help specialist agents convert Strands tool results
into structured artifacts that can be visualized or shared across agents.
"""
import json
import logging
import uuid
from typing import Any, Optional

logger = logging.getLogger("ARTIFACTS")


def _create_artifact(artifact_type: str, data: Any, title: str = "Query Results") -> dict[str, Any]:
    """Create an artifact dict with all required fields including id."""
    return {
        "id": str(uuid.uuid4()),
        "type": artifact_type,
        "data": data,
        "title": title
    }


def extract_artifacts_from_result(result) -> list[dict[str, Any]]:
    """
    Extract structured data from Strands AgentResult as artifacts.

    Looks for tool results containing tabular data from SQL queries.

    Args:
        result: Strands AgentResult object

    Returns:
        List of artifact dictionaries with type, data, and title
    """
    artifacts = []

    logger.info(f"Extracting artifacts from result type: {type(result).__name__}")

    try:
        # AgentResult has message.content which is a list of ContentBlocks
        if hasattr(result, 'message') and hasattr(result.message, 'content'):
            content_blocks = result.message.content
            logger.info(f"Found {len(content_blocks)} content blocks in message")

            for i, content_block in enumerate(content_blocks):
                block_type = type(content_block).__name__
                block_attrs = [attr for attr in dir(content_block) if not attr.startswith('_')]
                logger.debug(f"Content block {i}: type={block_type}, attrs={block_attrs[:5]}")

                # Check for tool results (might be dict or object)
                tool_result = None
                if hasattr(content_block, 'toolResult') and content_block.toolResult:
                    tool_result = content_block.toolResult
                elif isinstance(content_block, dict) and 'toolResult' in content_block:
                    tool_result = content_block['toolResult']

                if tool_result:
                    logger.info(f"Found toolResult: type={type(tool_result)}, keys={tool_result.keys() if isinstance(tool_result, dict) else 'N/A'}")
                    status = tool_result.get('status') if isinstance(tool_result, dict) else getattr(tool_result, 'status', None)
                    content = tool_result.get('content') if isinstance(tool_result, dict) else getattr(tool_result, 'content', None)

                    if status == 'success' and content:
                        logger.info(f"Tool result success with {len(content)} content items")
                        for content_item in content:
                            # Look for text content that might be JSON data
                            text_content = None
                            if isinstance(content_item, dict) and 'text' in content_item:
                                text_content = content_item['text']
                            elif hasattr(content_item, 'text'):
                                text_content = content_item.text

                            if text_content:
                                logger.debug(f"Parsing text content (first 200 chars): {text_content[:200]}")
                                data = _parse_data_from_text(text_content)
                                if data:
                                    logger.info(f"Parsed artifact from text content")
                                    artifacts.append(data)

                # Also check for text blocks that might contain data
                text_content = None
                if hasattr(content_block, 'text') and content_block.text:
                    text_content = content_block.text
                elif isinstance(content_block, dict) and 'text' in content_block:
                    text_content = content_block['text']

                if text_content and len(text_content) > 50:
                    # Only try to parse longer text that might be data
                    data = _parse_data_from_text(text_content)
                    if data:
                        logger.info(f"Parsed artifact from text block")
                        artifacts.append(data)

        # Also check if result itself is dict-like with data
        if hasattr(result, 'to_dict'):
            result_dict = result.to_dict()
            logger.debug(f"Result dict keys: {list(result_dict.keys())[:10]}")
            if 'data' in result_dict:
                artifacts.append(_create_artifact(
                    "table",
                    result_dict['data'],
                    "Query Results"
                ))

    except Exception as e:
        logger.warning(f"Error extracting artifacts: {e}", exc_info=True)

    return artifacts


def _parse_data_from_text(text: str) -> Optional[dict[str, Any]]:
    """Try to parse tabular data from text content."""
    try:
        # Try to parse as JSON first
        data = json.loads(text)
        if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
            return _create_artifact(
                "table",
                {
                    "rows": data,
                    "columns": list(data[0].keys()) if data else []
                },
                "Query Results"
            )
        elif isinstance(data, dict):
            # Check if it's already structured
            if 'rows' in data or 'data' in data:
                return _create_artifact("table", data, "Query Results")
    except json.JSONDecodeError:
        pass

    # Try to find markdown table anywhere in the text
    lines = text.strip().split('\n')

    # Find the start of a markdown table (line with | that's followed by separator line)
    for i in range(len(lines) - 1):
        line = lines[i].strip()
        next_line = lines[i + 1].strip() if i + 1 < len(lines) else ""

        # Check if this looks like a table header (has |) and next line is separator
        if '|' in line and '|' in next_line and '-' in next_line:
            # Extract table lines starting from header
            table_lines = [lines[i]]
            for j in range(i + 1, len(lines)):
                if '|' in lines[j]:
                    table_lines.append(lines[j])
                elif lines[j].strip() == '':
                    continue  # Skip empty lines
                else:
                    break  # End of table

            if len(table_lines) >= 3:  # Header + separator + at least one data row
                logger.info(f"Found markdown table with {len(table_lines)} lines")
                result = _parse_markdown_table(table_lines)
                if result:
                    return result

    return None


def _parse_markdown_table(lines: list[str]) -> Optional[dict[str, Any]]:
    """Parse a markdown-formatted table into structured data."""
    try:
        # First line should be headers
        header_line = lines[0]
        if '|' not in header_line:
            return None

        headers = [h.strip() for h in header_line.strip('|').split('|')]
        headers = [h for h in headers if h]  # Remove empty

        # Skip separator line if present
        data_start = 1
        if len(lines) > 1 and set(lines[1].replace('|', '').replace('-', '').strip()) == set():
            data_start = 2

        rows = []
        for line in lines[data_start:]:
            if '|' in line:
                values = [v.strip() for v in line.strip('|').split('|')]
                if len(values) == len(headers):
                    row = {}
                    for i, header in enumerate(headers):
                        # Try to convert to number
                        val = values[i]
                        try:
                            if '.' in val:
                                row[header] = float(val)
                            else:
                                row[header] = int(val)
                        except ValueError:
                            row[header] = val
                    rows.append(row)

        if rows:
            return _create_artifact(
                "table",
                {
                    "rows": rows,
                    "columns": headers
                },
                "Query Results"
            )
    except Exception:
        pass

    return None


def create_table_artifact(
    rows: list[dict[str, Any]],
    columns: Optional[list[str]] = None,
    title: str = "Query Results"
) -> dict[str, Any]:
    """
    Create a table artifact from structured data.

    Args:
        rows: List of row dictionaries
        columns: Optional list of column names (will be inferred from rows if not provided)
        title: Title for the artifact

    Returns:
        Artifact dictionary
    """
    if not columns and rows:
        columns = list(rows[0].keys())

    return _create_artifact(
        "table",
        {
            "rows": rows,
            "columns": columns or []
        },
        title
    )
