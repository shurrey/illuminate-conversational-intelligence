"""
Schema Cache - Auto-discovers and caches Snowflake schema at startup.

This module queries the actual database schema once at startup and caches it,
so agents have accurate column information without querying on every request.
"""
import os
import logging
from typing import Optional
from dataclasses import dataclass, field

logger = logging.getLogger("SCHEMA")


@dataclass
class ColumnInfo:
    """Information about a database column."""
    name: str
    data_type: str
    nullable: bool = True
    description: str = ""


@dataclass
class TableInfo:
    """Information about a database table or view."""
    name: str
    schema: str
    database: str
    columns: list[ColumnInfo] = field(default_factory=list)

    @property
    def full_name(self) -> str:
        return f"{self.database}.{self.schema}.{self.name}"


@dataclass
class SchemaInfo:
    """Information about a database schema."""
    name: str
    database: str
    tables: dict[str, TableInfo] = field(default_factory=dict)


class SchemaCache:
    """
    Caches database schema information discovered at startup.

    Usage:
        cache = SchemaCache()
        cache.discover(mcp_tools)  # Run once at startup

        # Get schema info for agents
        cdm_lms_info = cache.get_schema_description("CDM_LMS")
    """

    def __init__(self):
        self._schemas: dict[str, SchemaInfo] = {}
        self._discovered = False
        self._database: Optional[str] = None

    @property
    def is_discovered(self) -> bool:
        return self._discovered

    @property
    def database(self) -> str:
        return self._database or os.environ.get("SNOWFLAKE_DATABASE", "UNKNOWN")

    def discover(self, mcp_tools: list) -> bool:
        """
        Discover schema from Snowflake using MCP tools.

        Args:
            mcp_tools: List of MCP tools from the Snowflake server

        Returns:
            True if discovery succeeded, False otherwise
        """
        if self._discovered:
            logger.info("Schema already discovered, using cache")
            return True

        self._database = os.environ.get("SNOWFLAKE_DATABASE")
        if not self._database:
            logger.warning("SNOWFLAKE_DATABASE not set, skipping schema discovery")
            return False

        # Find the tools we need
        list_objects_tool = None
        describe_object_tool = None

        for tool in mcp_tools:
            tool_name = getattr(tool, 'name', getattr(tool, 'tool_name', str(tool)))
            if 'list_objects' in tool_name:
                list_objects_tool = tool
            elif 'describe_object' in tool_name:
                describe_object_tool = tool

        if not list_objects_tool or not describe_object_tool:
            logger.warning("Required MCP tools not found for schema discovery")
            return False

        # Discover schemas relevant to our agents
        target_schemas = ["CDM_LMS"]

        for schema_name in target_schemas:
            try:
                self._discover_schema(schema_name, list_objects_tool, describe_object_tool)
            except Exception as e:
                logger.warning(f"Failed to discover schema {schema_name}: {e}")

        self._discovered = True
        logger.info(f"Schema discovery complete. Found {len(self._schemas)} schemas.")
        return True

    def _discover_schema(self, schema_name: str, list_tool, describe_tool):
        """Discover tables, views, and columns for a specific schema."""
        logger.info(f"Discovering schema: {self._database}.{schema_name}")

        schema_info = SchemaInfo(name=schema_name, database=self._database)

        # Discover both tables and views
        for object_type in ["table", "view"]:
            try:
                # Call the list_objects tool
                result = list_tool(
                    object_type=object_type,
                    database=self._database,
                    schema=schema_name
                )

                # Parse the result - format depends on MCP tool response
                objects = self._parse_list_result(result)

                if not objects:
                    logger.info(f"No {object_type}s found in {schema_name}")
                    continue

                logger.info(f"Found {len(objects)} {object_type}s in {schema_name}")

                for obj_name in objects:
                    # Skip if already discovered (shouldn't happen, but be safe)
                    if obj_name in schema_info.tables:
                        continue

                    try:
                        # Describe each object to get columns
                        desc_result = describe_tool(
                            object_type=object_type,
                            database=self._database,
                            schema=schema_name,
                            name=obj_name
                        )

                        columns = self._parse_describe_result(desc_result)

                        table_info = TableInfo(
                            name=obj_name,
                            schema=schema_name,
                            database=self._database,
                            columns=columns
                        )
                        schema_info.tables[obj_name] = table_info
                        logger.debug(f"Discovered {object_type} {obj_name} with {len(columns)} columns")

                    except Exception as e:
                        logger.warning(f"Failed to describe {object_type} {obj_name}: {e}")

            except Exception as e:
                logger.warning(f"Failed to list {object_type}s in {schema_name}: {e}")

        if schema_info.tables:
            self._schemas[schema_name] = schema_info
            logger.info(f"Discovered {len(schema_info.tables)} objects (tables+views) in {schema_name}")
        else:
            logger.info(f"No tables or views found in {schema_name}")

    def _parse_list_result(self, result) -> list[str]:
        """Parse the result from list_objects to extract table names."""
        tables = []

        # Handle different result formats
        if isinstance(result, str):
            # Parse string response - look for table names
            for line in result.split('\n'):
                line = line.strip()
                if line and not line.startswith('-') and not line.startswith('|'):
                    # Could be a table name
                    parts = line.split()
                    if parts:
                        tables.append(parts[0])
        elif isinstance(result, dict):
            # Dict response
            if 'tables' in result:
                tables = result['tables']
            elif 'objects' in result:
                tables = [obj.get('name', obj) for obj in result['objects']]
            elif 'data' in result:
                for row in result.get('data', []):
                    if isinstance(row, dict):
                        tables.append(row.get('name', row.get('TABLE_NAME', '')))
                    elif isinstance(row, (list, tuple)) and row:
                        tables.append(row[0])
        elif isinstance(result, list):
            for item in result:
                if isinstance(item, str):
                    tables.append(item)
                elif isinstance(item, dict):
                    tables.append(item.get('name', item.get('TABLE_NAME', '')))

        return [t for t in tables if t]  # Filter empty

    def _parse_describe_result(self, result) -> list[ColumnInfo]:
        """Parse the result from describe_object to extract column info."""
        columns = []

        if isinstance(result, str):
            # Parse string response
            for line in result.split('\n'):
                line = line.strip()
                if line and '|' in line:
                    parts = [p.strip() for p in line.split('|')]
                    if len(parts) >= 2 and parts[0] and not parts[0].startswith('-'):
                        columns.append(ColumnInfo(
                            name=parts[0],
                            data_type=parts[1] if len(parts) > 1 else "UNKNOWN"
                        ))
                elif line and not line.startswith('-'):
                    parts = line.split()
                    if len(parts) >= 2:
                        columns.append(ColumnInfo(name=parts[0], data_type=parts[1]))
        elif isinstance(result, dict):
            if 'columns' in result:
                for col in result['columns']:
                    if isinstance(col, dict):
                        columns.append(ColumnInfo(
                            name=col.get('name', col.get('COLUMN_NAME', '')),
                            data_type=col.get('type', col.get('DATA_TYPE', 'UNKNOWN')),
                            nullable=col.get('nullable', True)
                        ))
            elif 'data' in result:
                for row in result.get('data', []):
                    if isinstance(row, dict):
                        columns.append(ColumnInfo(
                            name=row.get('name', row.get('COLUMN_NAME', '')),
                            data_type=row.get('type', row.get('DATA_TYPE', 'UNKNOWN'))
                        ))
        elif isinstance(result, list):
            for item in result:
                if isinstance(item, dict):
                    columns.append(ColumnInfo(
                        name=item.get('name', item.get('COLUMN_NAME', '')),
                        data_type=item.get('type', item.get('DATA_TYPE', 'UNKNOWN'))
                    ))

        return [c for c in columns if c.name]  # Filter empty

    def get_schema(self, schema_name: str) -> Optional[SchemaInfo]:
        """Get cached schema info."""
        return self._schemas.get(schema_name)

    def get_schema_description(self, schema_name: str) -> str:
        """
        Get a formatted description of a schema for use in agent prompts.

        Returns a string describing all tables and columns in the schema.
        """
        schema = self._schemas.get(schema_name)
        if not schema:
            return f"Schema {schema_name} not discovered. Use describe_object to discover table structures."

        lines = [f"## {self._database}.{schema_name} Tables/Views\n"]

        for table_name, table in sorted(schema.tables.items()):
            lines.append(f"### {table.full_name}")
            lines.append("Columns:")
            for col in table.columns:
                lines.append(f"  - {col.name} ({col.data_type})")
            lines.append("")

        return "\n".join(lines)

    def get_all_schemas_description(self) -> str:
        """Get formatted description of all discovered schemas."""
        if not self._schemas:
            return "No schemas discovered. Schema discovery may have failed."

        parts = []
        for schema_name in sorted(self._schemas.keys()):
            parts.append(self.get_schema_description(schema_name))

        return "\n".join(parts)


# Singleton instance
_schema_cache: Optional[SchemaCache] = None


def get_schema_cache() -> SchemaCache:
    """Get the singleton schema cache instance."""
    global _schema_cache
    if _schema_cache is None:
        _schema_cache = SchemaCache()
    return _schema_cache


def discover_schema(mcp_tools: list) -> bool:
    """
    Discover and cache the database schema.

    Call this once at startup after MCP tools are available.
    """
    cache = get_schema_cache()
    return cache.discover(mcp_tools)
