"""
Orchestrator Agent - Central coordinator for the multi-agent system.

This agent:
- Receives user queries
- Calls Planner Agent (Opus) to create execution plan
- Executes the plan by coordinating specialist agents
- Acts as central hub - all agents return results to Orchestrator
- Validates responses before returning

Architecture:
    User Query → Planner (Opus) → Orchestrator executes plan
                                   ├── SQL Agent → Orchestrator
                                   ├── Analyst Agent → Orchestrator
                                   ├── Writer Agent → Orchestrator
                                   ├── Visualization Agent → Orchestrator
                                   └── Validator Agent → Orchestrator
                                   → Final Response

Model: Claude Sonnet 4 (fast, efficient plan execution)
"""
import os
import logging
import uuid
import json
from typing import Any, AsyncGenerator, Optional

from agents.shared.models import (
    AgentCard, Message, MessageRole, MessagePart, Artifact, ArtifactType,
    AgentType, ConversationContext,
    ExecutionPlan, PipelinePath, AnalysisResult, WriteResult
)
from agents.shared.a2a_client import (
    A2AClient, A2AServer, get_agent_registry
)
from agents.shared.llm_client import get_orchestrator_llm, LLMClient

# Import new pipeline agents
from agents.planner.agent import get_planner_agent, PlannerAgent
from agents.sql.agent import handle_query as sql_handle_query
from agents.sql.agent import handle_query_streaming as sql_handle_query_streaming
from agents.analyst.agent import get_analyst_agent, AnalystAgent
from agents.writer.agent import get_writer_agent, WriterAgent

# Import visualization agent (custom, no Snowflake)
from agents.visualization.agent import get_visualization_agent, VisualizationAgent

# Import validator agent
from agents.validator.agent import get_validator_agent, ValidationStatus

logger = logging.getLogger("ORCHESTRATOR")


# Agent Card for A2A discovery
ORCHESTRATOR_AGENT_CARD = AgentCard(
    name="illuminate-orchestrator",
    description="Central coordinator for educational data queries. Uses Planner Agent to create execution plans, then coordinates SQL, Analyst, and Writer agents.",
    capabilities={
        "streaming": True,
        "pushNotifications": True,
        "validation": True,
        "planning": True  # Uses Planner Agent for intelligent routing
    },
    default_input_modes=["text"],
    default_output_modes=["text", "data"],
    skills=[
        {
            "id": "plan_execution",
            "name": "Plan Executor",
            "description": "Executes plans created by Planner Agent"
        },
        {
            "id": "agent_coordination",
            "name": "Agent Coordinator",
            "description": "Coordinates SQL, Analyst, Writer, and Visualization agents"
        },
        {
            "id": "response_validation",
            "name": "Response Validator",
            "description": "Validates all responses for accuracy, safety, and FERPA compliance"
        }
    ]
)


# Default A2A server URLs for specialists
DEFAULT_SPECIALIST_URLS = {
    AgentType.SQL: "http://127.0.0.1:9001",
}


class OrchestratorAgent:
    """
    Orchestrator Agent for coordinating multi-agent interactions.

    Implements the Planner-Executor pattern:
    1. Receives user queries
    2. Calls Planner Agent (Opus) to create execution plan
    3. Executes plan by calling SQL → Analyst → Writer as needed
    4. Validates responses with Validator Agent
    5. Manages conversation context

    All agents return results to Orchestrator (hub pattern).
    No direct agent-to-agent communication.

    Supports two modes:
    - Local mode (use_a2a=False): Calls specialist agents directly via Python
    - A2A mode (use_a2a=True): Communicates via A2A protocol over HTTP
    """

    def __init__(
        self,
        use_a2a: bool = False,
        specialist_urls: Optional[dict[AgentType, str]] = None
    ):
        """
        Initialize the Orchestrator Agent.

        Args:
            use_a2a: If True, communicate with specialists via A2A protocol.
                    If False, call specialist agents directly (local mode).
            specialist_urls: URLs for specialist A2A servers. Uses defaults if not provided.
        """
        self.agent_card = ORCHESTRATOR_AGENT_CARD
        self._conversations: dict[str, ConversationContext] = {}
        self._use_a2a = use_a2a
        self._specialist_urls = specialist_urls or DEFAULT_SPECIALIST_URLS

        # Lazy-loaded agents
        self._llm: Optional[LLMClient] = None
        self._planner: Optional[PlannerAgent] = None
        self._analyst: Optional[AnalystAgent] = None
        self._writer: Optional[WriterAgent] = None
        self._validator = None
        self._visualization_agent: Optional[VisualizationAgent] = None
        self._a2a_tool_provider = None

    @property
    def llm(self) -> LLMClient:
        """Lazy-load LLM client."""
        if self._llm is None:
            self._llm = get_orchestrator_llm()
        return self._llm

    @property
    def planner(self) -> PlannerAgent:
        """Lazy-load Planner Agent."""
        if self._planner is None:
            self._planner = get_planner_agent()
        return self._planner

    @property
    def analyst(self) -> AnalystAgent:
        """Lazy-load Analyst Agent."""
        if self._analyst is None:
            self._analyst = get_analyst_agent()
        return self._analyst

    @property
    def writer(self) -> WriterAgent:
        """Lazy-load Writer Agent."""
        if self._writer is None:
            self._writer = get_writer_agent()
        return self._writer

    @property
    def validator(self):
        """Lazy-load validator agent."""
        if self._validator is None:
            self._validator = get_validator_agent()
        return self._validator

    @property
    def visualization_agent(self) -> VisualizationAgent:
        """Lazy-load visualization agent."""
        if self._visualization_agent is None:
            self._visualization_agent = get_visualization_agent()
        return self._visualization_agent

    @property
    def a2a_tool_provider(self):
        """Lazy-load A2A client tool provider for specialist communication."""
        if self._a2a_tool_provider is None and self._use_a2a:
            from strands_tools.a2a_client import A2AClientToolProvider
            self._a2a_tool_provider = A2AClientToolProvider(
                known_agent_urls=list(self._specialist_urls.values()),
                timeout=30.0
            )
        return self._a2a_tool_provider

    async def handle_message(self, message: Message) -> dict[str, Any]:
        """
        Handle an incoming user message.

        This is the main entry point for all user queries.
        Uses Planner Agent (Opus) to create execution plan, then executes it.

        Args:
            message: User message to process

        Returns:
            Response with text, artifacts, and metadata
        """
        # Get or create conversation context
        context_id = message.context_id or str(uuid.uuid4())
        context = self._get_or_create_context(context_id)
        context.add_message(message)

        # Extract query text
        query_text = self._extract_text(message)
        logger.info(f"Orchestrator received query: {query_text[:100]}...")

        try:
            # 1. Call Planner Agent to create execution plan (Opus)
            plan = await self.planner.create_plan(query_text, context)
            logger.info(f"Plan: {plan.pipeline_path.value}, agents: {plan.agents_to_call}, analyst_model: {plan.analyst_model}")

            # 2. Execute the plan based on pipeline path
            if plan.pipeline_path == PipelinePath.VIZ_ONLY:
                # Visualization-only: use existing data from context
                response = await self._handle_visualization_only(query_text, context)

            elif plan.pipeline_path == PipelinePath.CLARIFICATION:
                # Clarification needed - return Planner's context_notes as the response
                response = {
                    "text": plan.context_notes or "Could you please provide more details about what you're looking for?",
                    "artifacts": []
                }

            else:
                # Execute pipeline: SQL → (optional) Analyst → Writer
                response = await self._execute_pipeline(query_text, plan, context)

                # Validate response before returning (unless skipped)
                if not plan.skip_validation:
                    response = await self._validate_response(query_text, response, plan)

            # Create response message and add to context
            artifacts_list = response.get("artifacts", [])
            response_message = Message(
                id=str(uuid.uuid4()),
                role=MessageRole.ASSISTANT,
                parts=[MessagePart(type="text", content=response.get("text", ""))],
                artifacts=artifacts_list,
                context_id=context_id
            )
            context.add_message(response_message)
            logger.info(f"Stored response with {len(artifacts_list)} artifacts in context")

            # Add context_id to response
            response["context_id"] = context_id

            return response

        except Exception as e:
            logger.error(f"Error processing query: {e}")
            return {
                "text": f"I apologize, but I encountered an error processing your request: {str(e)}",
                "artifacts": [Artifact.create_error(str(e)).to_dict()],
                "context_id": context_id
            }

    async def _execute_pipeline(
        self,
        query_text: str,
        plan: ExecutionPlan,
        context: ConversationContext
    ) -> dict[str, Any]:
        """
        Execute the pipeline based on the plan.

        Pipeline paths:
        - SIMPLE: SQL → format response (no analysis)
        - STANDARD: SQL → Analyst(Sonnet) → Writer
        - DEEP_ANALYSIS: SQL → Analyst(Opus) → Writer

        Args:
            query_text: User's query
            plan: Execution plan from Planner
            context: Conversation context

        Returns:
            Response dict with text and artifacts
        """
        # Build query with conversation history
        query_with_context = self._build_query_with_context(query_text, context)

        # Step 1: SQL Agent - get data
        logger.info("Executing SQL Agent...")
        sql_result = await sql_handle_query(query_with_context)

        data = sql_result.get("data", [])
        columns = sql_result.get("columns", [])
        row_count = sql_result.get("row_count", 0)

        logger.info(f"SQL Agent returned {row_count} rows")

        # Check for SQL errors
        if sql_result.get("error"):
            return {
                "text": f"I encountered an error querying the data: {sql_result['error']}",
                "artifacts": []
            }

        # For SIMPLE path, format a basic response without analysis
        if plan.pipeline_path == PipelinePath.SIMPLE:
            # Create table artifact
            artifacts = []
            if data:
                artifacts.append({
                    "id": str(uuid.uuid4()),
                    "type": "table",
                    "data": {"rows": data, "columns": columns},
                    "title": "Query Results"
                })

            return {
                "text": f"Found {row_count} results." if row_count > 0 else "No results found for your query.",
                "artifacts": artifacts,
                "data": data,
                "columns": columns,
                "row_count": row_count
            }

        # Step 2: Analyst Agent - interpret data (STANDARD or DEEP_ANALYSIS)
        analysis = None
        if "analyst" in plan.agents_to_call and data:
            logger.info(f"Executing Analyst Agent with {plan.analyst_model} model...")
            analysis = await self.analyst.analyze(
                user_query=query_text,
                data=data,
                columns=columns,
                model=plan.analyst_model
            )
            logger.info(f"Analyst returned {len(analysis.key_insights)} insights")

        # Step 3: Writer Agent - craft response
        logger.info("Executing Writer Agent...")
        write_result = await self.writer.write(
            user_query=query_text,
            data=data,
            columns=columns,
            analysis=analysis
        )

        # Convert WriteResult artifacts to dicts
        artifacts = [a.to_dict() for a in write_result.artifacts]

        # Step 4: Visualization (if needed)
        if plan.needs_visualization and data:
            logger.info("Generating visualization...")
            viz_result = await self._generate_visualization(
                query_text, data, columns, analysis
            )
            if viz_result:
                artifacts.extend(viz_result.get("artifacts", []))

        return {
            "text": write_result.text,
            "artifacts": artifacts,
            "suggested_followups": write_result.suggested_followups,
            "data": data,
            "columns": columns,
            "row_count": row_count,
            "analysis": analysis.to_dict() if analysis else None
        }

    async def _generate_visualization(
        self,
        query_text: str,
        data: list[dict[str, Any]],
        columns: list[str],
        analysis: Optional[AnalysisResult]
    ) -> Optional[dict[str, Any]]:
        """Generate visualization from data and analysis."""
        viz_agent = self.visualization_agent

        # Get visualization suggestion from analysis if available
        viz_hint = None
        if analysis and analysis.visualization_suggestion:
            viz_hint = analysis.visualization_suggestion

        # Create visualization request
        viz_message = Message(
            id=str(uuid.uuid4()),
            role=MessageRole.USER,
            parts=[
                MessagePart(type="text", content=query_text),
                MessagePart(type="data", content={"rows": data, "columns": columns})
            ]
        )

        try:
            return await viz_agent.handle_message(viz_message)
        except Exception as e:
            logger.error(f"Visualization failed: {e}")
            return None

    async def handle_message_streaming(
        self,
        message: Message
    ) -> AsyncGenerator[dict[str, Any], None]:
        """
        Handle an incoming user message with streaming responses.

        Yields events as the query is processed:
        - type: "status" - Processing status updates
        - type: "planning" - Plan created by Planner Agent
        - type: "thinking" - Agent thinking/reasoning
        - type: "tool_call" - Tool being invoked
        - type: "complete" - Final response with artifacts

        Args:
            message: User message to process

        Yields:
            Event dictionaries with type and data
        """
        # Get or create conversation context
        context_id = message.context_id or str(uuid.uuid4())
        context = self._get_or_create_context(context_id)
        context.add_message(message)

        # Extract query text
        query_text = self._extract_text(message)
        logger.info(f"Orchestrator streaming query: {query_text[:100]}...")

        yield {"type": "status", "message": "Analyzing your question...", "context_id": context_id}

        try:
            # 1. Call Planner Agent with streaming
            yield {
                "type": "thinking",
                "agent": "planner",
                "content": "Planning query execution...",
                "accumulated": "Planning query execution..."
            }

            plan = None
            plan_dict = None
            async for event in self.planner.create_plan_streaming(query_text, context):
                if event.get("type") == "plan_complete":
                    plan_dict = event.get("plan")
                    # Convert dict back to ExecutionPlan
                    plan = ExecutionPlan(
                        pipeline_path=PipelinePath(plan_dict["pipeline_path"]),
                        agents_to_call=plan_dict.get("agents_to_call", ["sql", "analyst", "writer"]),
                        analyst_model=plan_dict.get("analyst_model", "sonnet"),
                        needs_visualization=plan_dict.get("needs_visualization", False),
                        skip_validation=plan_dict.get("skip_validation", False),
                        context_notes=plan_dict.get("context_notes", ""),
                        reasoning=plan_dict.get("reasoning", "")
                    )
                else:
                    yield event

            if not plan:
                raise ValueError("Planner did not return a plan")

            # Emit planning event
            yield {
                "type": "planning",
                "plan": plan.to_dict(),
                "message": f"Plan: {plan.pipeline_path.value} path with agents: {', '.join(plan.agents_to_call)}"
            }

            # 2. Execute based on pipeline path
            if plan.pipeline_path == PipelinePath.VIZ_ONLY:
                yield {"type": "status", "message": "Creating visualization from previous data..."}
                response = await self._handle_visualization_only(query_text, context)

            elif plan.pipeline_path == PipelinePath.CLARIFICATION:
                response = {
                    "text": plan.context_notes or "Could you please provide more details?",
                    "artifacts": []
                }

            else:
                # Execute pipeline with streaming
                response = None
                async for event in self._execute_pipeline_streaming(query_text, plan, context):
                    if event.get("type") == "pipeline_complete":
                        response = event.get("response")
                    else:
                        yield event

                if not response:
                    raise ValueError("Pipeline did not return a response")

                # Validate response (unless skipped)
                if not plan.skip_validation:
                    yield {
                        "type": "thinking",
                        "agent": "validator",
                        "content": "Validating response for accuracy, safety, and FERPA compliance...",
                        "accumulated": "Validating response for accuracy, safety, and FERPA compliance..."
                    }
                    yield {
                        "type": "tool_call",
                        "agent": "validator",
                        "tool": "validate_response",
                        "tool_id": 1,
                        "input": {"checks": ["accuracy", "safety", "ferpa_compliance"]}
                    }
                    response = await self._validate_response(query_text, response, plan)

                    # Emit validation result
                    validation_status = response.get("confidence", "unknown")
                    if response.get("blocked"):
                        yield {
                            "type": "thinking",
                            "agent": "validator",
                            "content": "Response blocked due to policy violation.",
                            "accumulated": "Response blocked due to policy violation."
                        }
                    elif response.get("warnings"):
                        yield {
                            "type": "thinking",
                            "agent": "validator",
                            "content": f"Validation passed with warnings. Confidence: {validation_status}",
                            "accumulated": f"Validation passed with warnings. Confidence: {validation_status}"
                        }
                    else:
                        yield {
                            "type": "thinking",
                            "agent": "validator",
                            "content": f"Validation passed. Confidence: {validation_status}",
                            "accumulated": f"Validation passed. Confidence: {validation_status}"
                        }

            # Create response message and add to context
            artifacts_list = response.get("artifacts", [])
            response_message = Message(
                id=str(uuid.uuid4()),
                role=MessageRole.ASSISTANT,
                parts=[MessagePart(type="text", content=response.get("text", ""))],
                artifacts=artifacts_list,
                context_id=context_id
            )
            context.add_message(response_message)

            # Yield final response
            response["context_id"] = context_id
            yield {"type": "complete", "data": response}

        except Exception as e:
            logger.error(f"Error in streaming query: {e}")
            yield {
                "type": "error",
                "message": str(e),
                "context_id": context_id
            }
            yield {
                "type": "complete",
                "data": {
                    "text": f"I apologize, but I encountered an error: {str(e)}",
                    "artifacts": [],
                    "context_id": context_id
                }
            }

    async def _execute_pipeline_streaming(
        self,
        query_text: str,
        plan: ExecutionPlan,
        context: ConversationContext
    ) -> AsyncGenerator[dict[str, Any], None]:
        """
        Execute the pipeline with streaming events.

        Yields events for each agent, then final result.
        """
        # Build query with conversation history
        query_with_context = self._build_query_with_context(query_text, context)

        # Step 1: SQL Agent with streaming
        yield {
            "type": "thinking",
            "agent": "sql",
            "content": "Generating and executing SQL query...",
            "accumulated": "Generating and executing SQL query..."
        }

        data = []
        columns = []
        sql_error = None

        async for event in sql_handle_query_streaming(query_with_context):
            if event.get("type") == "complete":
                sql_data = event.get("data", {})
                data = sql_data.get("data", [])
                columns = sql_data.get("columns", [])
                sql_error = sql_data.get("error")
            else:
                yield event

        row_count = len(data)
        logger.info(f"SQL Agent returned {row_count} rows")

        # Check for SQL errors
        if sql_error:
            yield {
                "type": "pipeline_complete",
                "response": {
                    "text": f"I encountered an error querying the data: {sql_error}",
                    "artifacts": []
                }
            }
            return

        # For SIMPLE path, format a basic response
        if plan.pipeline_path == PipelinePath.SIMPLE:
            artifacts = []
            if data:
                artifacts.append({
                    "id": str(uuid.uuid4()),
                    "type": "table",
                    "data": {"rows": data, "columns": columns},
                    "title": "Query Results"
                })

            yield {
                "type": "pipeline_complete",
                "response": {
                    "text": f"Found {row_count} results." if row_count > 0 else "No results found.",
                    "artifacts": artifacts,
                    "data": data,
                    "columns": columns,
                    "row_count": row_count
                }
            }
            return

        # Step 2: Analyst Agent (if needed)
        analysis = None
        if "analyst" in plan.agents_to_call and data:
            yield {
                "type": "thinking",
                "agent": "analyst",
                "content": f"Analyzing {row_count} rows of data...",
                "accumulated": f"Analyzing {row_count} rows of data..."
            }

            async for event in self.analyst.analyze_streaming(
                user_query=query_text,
                data=data,
                columns=columns,
                model=plan.analyst_model
            ):
                if event.get("type") == "analysis_complete":
                    analysis = AnalysisResult(**event.get("analysis", {}))
                else:
                    yield event

            if analysis:
                logger.info(f"Analyst returned {len(analysis.key_insights)} insights")

        # Step 3: Writer Agent
        yield {
            "type": "thinking",
            "agent": "writer",
            "content": "Composing response...",
            "accumulated": "Composing response..."
        }

        write_result = None
        async for event in self.writer.write_streaming(
            user_query=query_text,
            data=data,
            columns=columns,
            analysis=analysis
        ):
            if event.get("type") == "write_complete":
                result_data = event.get("result", {})
                write_result = WriteResult(
                    text=result_data.get("text", ""),
                    artifacts=[
                        self._artifact_from_dict(a) if isinstance(a, dict) else a
                        for a in result_data.get("artifacts", [])
                    ],
                    suggested_followups=result_data.get("suggested_followups", [])
                )
            else:
                yield event

        if not write_result:
            # Fallback if streaming didn't return result
            write_result = await self.writer.write(query_text, data, columns, analysis)

        # Convert artifacts to dicts
        artifacts = [a.to_dict() for a in write_result.artifacts]

        # Step 4: Visualization (if needed)
        if plan.needs_visualization and data:
            yield {
                "type": "thinking",
                "agent": "visualization",
                "content": "Generating visualization...",
                "accumulated": "Generating visualization..."
            }
            viz_result = await self._generate_visualization(
                query_text, data, columns, analysis
            )
            if viz_result:
                artifacts.extend(viz_result.get("artifacts", []))

        yield {
            "type": "pipeline_complete",
            "response": {
                "text": write_result.text,
                "artifacts": artifacts,
                "suggested_followups": write_result.suggested_followups,
                "data": data,
                "columns": columns,
                "row_count": row_count,
                "analysis": analysis.to_dict() if analysis else None
            }
        }

    async def _handle_visualization_only(
        self,
        query_text: str,
        context: ConversationContext
    ) -> dict[str, Any]:
        """
        Handle a visualization-only request using data from conversation context.

        Args:
            query_text: User's visualization request
            context: Conversation context with previous messages/artifacts

        Returns:
            Response with visualization
        """
        logger.info("Handling visualization-only request - extracting data from context")
        logger.info(f"Context has {len(context.messages)} messages")

        # Find the most recent data artifact in conversation history
        data = None
        for msg in reversed(context.messages):
            logger.debug(f"Checking message: role={msg.role}, artifacts_count={len(msg.artifacts)}")
            if msg.role == MessageRole.ASSISTANT and msg.artifacts:
                logger.info(f"Found assistant message with {len(msg.artifacts)} artifacts")
                for artifact in msg.artifacts:
                    if isinstance(artifact, dict):
                        artifact_type = artifact.get("type", "")
                        artifact_data = artifact.get("data", {})
                        logger.info(f"Dict artifact: type={artifact_type}, has_data={bool(artifact_data)}")
                    else:
                        artifact_type = artifact.type.value if hasattr(artifact.type, 'value') else str(artifact.type)
                        artifact_data = artifact.data
                        logger.info(f"Object artifact: type={artifact_type}, has_data={bool(artifact_data)}")

                    # Look for table data we can visualize
                    if artifact_type == "table" and artifact_data:
                        if isinstance(artifact_data, dict):
                            data = artifact_data
                            logger.info(f"Found table data with keys: {list(artifact_data.keys()) if isinstance(artifact_data, dict) else 'N/A'}")
                        break
                if data:
                    break

        if not data:
            logger.warning(f"No table data found in {len(context.messages)} context messages")
            return {
                "text": "I couldn't find any data from our recent conversation to visualize. Please ask a data question first, and then I can create a visualization.",
                "artifacts": []
            }

        # Use visualization agent
        viz_agent = self.visualization_agent

        # Create visualization message
        viz_message = Message(
            id=str(uuid.uuid4()),
            role=MessageRole.USER,
            parts=[
                MessagePart(type="text", content=query_text),
                MessagePart(type="data", content=data)
            ]
        )

        try:
            viz_result = await viz_agent.handle_message(viz_message)
            return {
                "text": viz_result.get("text", "Here's a visualization of your data."),
                "artifacts": viz_result.get("artifacts", []),
                "visualization": viz_result.get("chart_config")
            }
        except Exception as e:
            logger.error(f"Visualization failed: {e}")
            return {
                "text": f"I encountered an error creating the visualization: {str(e)}",
                "artifacts": []
            }

    def _extract_text(self, message: Message) -> str:
        """Extract text content from message."""
        for part in message.parts:
            if part.type == "text":
                return str(part.content)
        return ""

    def _get_or_create_context(self, context_id: str) -> ConversationContext:
        """Get existing or create new conversation context."""
        if context_id not in self._conversations:
            self._conversations[context_id] = ConversationContext(id=context_id)
        return self._conversations[context_id]

    def _build_query_with_context(
        self,
        query_text: str,
        context: Optional[ConversationContext]
    ) -> str:
        """
        Build a query string that includes relevant conversation history AND data.

        For follow-up questions, this provides the agent with:
        - Previous conversation text
        - Actual data from previous responses (for cross-agent queries)
        """
        if not context or len(context.messages) <= 1:
            # No history or only current message
            return query_text

        # Get recent conversation history (last 4 exchanges max to avoid token limits)
        recent_messages = context.messages[-8:]  # 4 user + 4 assistant messages

        # Build context summary
        history_parts = []
        data_parts = []

        for msg in recent_messages[:-1]:  # Exclude current message
            role = "User" if msg.role == MessageRole.USER else "Assistant"
            text = self._extract_text(msg)
            if text:
                # Truncate long responses to keep context manageable
                if len(text) > 500:
                    text = text[:500] + "..."
                history_parts.append(f"{role}: {text}")

            # Include artifact data from assistant messages
            if msg.role == MessageRole.ASSISTANT and msg.artifacts:
                for artifact in msg.artifacts:
                    artifact_data = self._extract_artifact_data(artifact)
                    if artifact_data:
                        data_parts.append(artifact_data)

        if not history_parts and not data_parts:
            return query_text

        # Combine history with current query
        context_parts = []

        if history_parts:
            history_text = "\n".join(history_parts)
            context_parts.append(f"## Previous Conversation:\n{history_text}")

        if data_parts:
            # Include up to 2 most recent data artifacts (to avoid token limits)
            recent_data = data_parts[-2:]
            data_text = "\n\n".join(recent_data)
            context_parts.append(f"## Previously Retrieved Data:\n{data_text}")

        context_parts.append(f"## Current Question:\n{query_text}")
        context_parts.append("Please answer the current question, using the conversation context and data if relevant.")

        return "\n\n".join(context_parts)

    def _artifact_from_dict(self, data: dict) -> Artifact:
        """Convert a dict to an Artifact object, handling type conversion."""
        artifact_type = data.get("type", "table")
        # Convert string type to ArtifactType enum
        if isinstance(artifact_type, str):
            type_map = {
                "table": ArtifactType.TABLE,
                "chart": ArtifactType.CHART,
                "text": ArtifactType.TEXT,
                "error": ArtifactType.ERROR,
            }
            artifact_type = type_map.get(artifact_type.lower(), ArtifactType.TABLE)

        return Artifact(
            id=data.get("id", str(uuid.uuid4())),
            type=artifact_type,
            data=data.get("data"),
            title=data.get("title"),
            description=data.get("description")
        )

    def _extract_artifact_data(self, artifact: Any) -> Optional[str]:
        """Extract data from an artifact as a string summary."""
        try:
            if isinstance(artifact, dict):
                artifact_type = artifact.get("type", "")
                artifact_data = artifact.get("data", {})
                artifact_title = artifact.get("title", "Data")
            else:
                artifact_type = artifact.type.value if hasattr(artifact.type, 'value') else str(artifact.type)
                artifact_data = artifact.data
                artifact_title = artifact.title or "Data"

            if artifact_type == "table" and artifact_data:
                if isinstance(artifact_data, dict):
                    rows = artifact_data.get("rows", artifact_data.get("data", []))
                    columns = artifact_data.get("columns", [])

                    if rows:
                        # Limit to first 10 rows for context
                        sample_rows = rows[:10]
                        import json
                        data_json = json.dumps({
                            "title": artifact_title,
                            "columns": columns or list(sample_rows[0].keys()) if sample_rows else [],
                            "row_count": len(rows),
                            "sample_data": sample_rows
                        }, indent=2)
                        return f"### {artifact_title}\n```json\n{data_json}\n```"

            elif artifact_type == "text":
                return f"### {artifact_title}\n{str(artifact_data)[:500]}"

        except Exception as e:
            logger.warning(f"Failed to extract artifact data: {e}")

        return None

    async def _validate_response(
        self,
        query: str,
        response: dict[str, Any],
        plan: ExecutionPlan
    ) -> dict[str, Any]:
        """
        Validate response using the Validator Agent.

        Args:
            query: Original user query
            response: Pipeline response
            plan: Execution plan (for context)

        Returns:
            Validated (possibly modified) response
        """
        try:
            # Extract data from response
            artifacts = None
            if response.get("artifacts"):
                artifacts = [
                    self._artifact_from_dict(a) if isinstance(a, dict) else a
                    for a in response["artifacts"]
                ]

            # Run validation
            validation = await self.validator.validate(
                user_query=query,
                response_text=response.get("text", ""),
                sql_query=None,  # SQL query not tracked in new pipeline
                query_result=response.get("data"),
                artifacts=artifacts
            )

            # Handle validation result
            if validation.blocked:
                logger.warning(f"Response blocked: {validation.block_reason}")
                return {
                    "text": "I'm unable to provide this information due to data privacy constraints. Please try a more aggregated query.",
                    "artifacts": [],
                    "validation": validation.to_dict(),
                    "blocked": True
                }

            if validation.overall_status == ValidationStatus.FAILED:
                logger.warning(f"Validation failed: {[c.message for c in validation.checks]}")
                return {
                    "text": "I encountered issues with this response. " + response.get("text", ""),
                    "artifacts": response.get("artifacts", []),
                    "validation": validation.to_dict(),
                    "warnings": [c.message for c in validation.checks if c.status == ValidationStatus.FAILED]
                }

            if validation.overall_status == ValidationStatus.WARNING:
                # Add warnings to response
                response["validation"] = validation.to_dict()
                response["warnings"] = [c.message for c in validation.checks if c.status == ValidationStatus.WARNING]

            # Use corrected response if provided
            if validation.validated_response:
                response["text"] = validation.validated_response

            # Add confidence score
            response["confidence"] = validation.confidence_score

            return response

        except Exception as e:
            logger.error(f"Validation failed with exception: {e}")
            # Return original response with warning
            response["validation_error"] = str(e)
            return response

    def get_conversation_history(self, context_id: str) -> list[dict[str, Any]]:
        """Get conversation history for a context."""
        context = self._conversations.get(context_id)
        if context:
            return [m.to_dict() for m in context.messages]
        return []

    def clear_conversation(self, context_id: str) -> bool:
        """Clear a conversation context."""
        if context_id in self._conversations:
            del self._conversations[context_id]
            return True
        return False


# Create singleton instance
_orchestrator_agent: Optional[OrchestratorAgent] = None


def get_orchestrator_agent(
    use_a2a: bool = None
) -> OrchestratorAgent:
    """
    Get or create the Orchestrator Agent instance.

    Args:
        use_a2a: If True, communicate with specialists via A2A protocol.
                If False, call specialists directly. If None, auto-detect
                from ILLUMINATE_USE_A2A environment variable.
    """
    global _orchestrator_agent
    if _orchestrator_agent is None:
        # Auto-detect A2A mode from environment if not specified
        if use_a2a is None:
            use_a2a = os.environ.get("ILLUMINATE_USE_A2A", "false").lower() == "true"

        _orchestrator_agent = OrchestratorAgent(
            use_a2a=use_a2a
        )
        registry = get_agent_registry()
        registry.register(AgentType.ORCHESTRATOR, _orchestrator_agent)
    return _orchestrator_agent


def create_a2a_server(port: int = 9000) -> A2AServer:
    """Create an A2A server for the Orchestrator Agent."""
    agent = get_orchestrator_agent()
    return A2AServer(
        agent_card=agent.agent_card,
        message_handler=agent.handle_message,
        port=port
    )


# Convenience function for direct usage
async def query(text: str, context_id: Optional[str] = None) -> dict[str, Any]:
    """
    Process a natural language query.

    This is the main entry point for the Illuminate Conversational Intelligence system.

    Args:
        text: Natural language query
        context_id: Optional conversation context ID for multi-turn conversations

    Returns:
        Response with text, artifacts, and metadata

    Example:
        >>> result = await query("What is the average GPA for Fall 2024?")
        >>> print(result["text"])
    """
    agent = get_orchestrator_agent()
    message = Message.create_user_message(text, context_id or str(uuid.uuid4()))
    return await agent.handle_message(message)


async def query_streaming(
    text: str,
    context_id: Optional[str] = None
) -> AsyncGenerator[dict[str, Any], None]:
    """
    Process a natural language query with streaming responses.

    Yields events as the query is processed, including status updates,
    tool calls, and the final response.

    Args:
        text: Natural language query
        context_id: Optional conversation context ID

    Yields:
        Event dictionaries with type and data

    Example:
        >>> async for event in query_streaming("What is the average GPA?"):
        ...     print(event["type"], event.get("message", ""))
    """
    agent = get_orchestrator_agent()
    message = Message.create_user_message(text, context_id or str(uuid.uuid4()))
    async for event in agent.handle_message_streaming(message):
        yield event
