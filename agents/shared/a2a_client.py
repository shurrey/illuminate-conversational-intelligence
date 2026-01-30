"""
A2A (Agent-to-Agent) Protocol Client for Illuminate Conversational Intelligence.

This module implements the Google A2A protocol for inter-agent communication,
following the specification at https://a2a-protocol.org/latest/

Key features:
- Agent discovery via Agent Cards
- Task delegation and management
- Streaming response support
- JSON-RPC 2.0 message format
"""
import os
import json
import uuid
import logging
from typing import Any, Optional, AsyncGenerator, Callable
from dataclasses import dataclass
from enum import Enum

import httpx

from .models import (
    AgentCard, Message, MessageRole, MessagePart, A2ATask, AgentType
)

logger = logging.getLogger("A2A")


class TaskStatus(Enum):
    """Status of an A2A task."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class A2AConfig:
    """Configuration for A2A client."""
    base_url: str = "http://localhost:9000"
    timeout: float = 30.0
    max_retries: int = 3
    enable_streaming: bool = True

    @classmethod
    def from_env(cls) -> "A2AConfig":
        return cls(
            base_url=os.environ.get("A2A_BASE_URL", "http://localhost:9000"),
            timeout=float(os.environ.get("A2A_TIMEOUT", "30.0")),
            max_retries=int(os.environ.get("A2A_MAX_RETRIES", "3")),
            enable_streaming=os.environ.get("A2A_ENABLE_STREAMING", "true").lower() == "true"
        )


class A2AClient:
    """
    Client for A2A protocol communication between agents.

    Implements the A2A protocol for:
    - Discovering agent capabilities
    - Sending messages to remote agents
    - Managing task lifecycle
    - Streaming responses
    """

    def __init__(self, config: Optional[A2AConfig] = None):
        self.config = config or A2AConfig.from_env()
        self._agent_registry: dict[str, AgentCard] = {}
        self._http_client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        self._http_client = httpx.AsyncClient(timeout=self.config.timeout)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._http_client:
            await self._http_client.aclose()

    def _get_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=self.config.timeout)
        return self._http_client

    async def discover_agent(self, agent_url: str) -> AgentCard:
        """
        Discover an agent's capabilities by fetching its Agent Card.

        The Agent Card is fetched from /.well-known/agent.json

        Args:
            agent_url: Base URL of the agent

        Returns:
            AgentCard describing the agent's capabilities
        """
        client = self._get_client()
        card_url = f"{agent_url.rstrip('/')}/.well-known/agent.json"

        try:
            response = await client.get(card_url)
            response.raise_for_status()
            data = response.json()

            card = AgentCard(
                name=data["name"],
                description=data["description"],
                protocol_version=data.get("protocolVersion", "0.3"),
                capabilities=data.get("capabilities", {}),
                default_input_modes=data.get("defaultInputModes", ["text"]),
                default_output_modes=data.get("defaultOutputModes", ["text"]),
                skills=data.get("skills", [])
            )

            # Cache the agent card
            self._agent_registry[agent_url] = card
            return card

        except httpx.HTTPError as e:
            logger.error(f"Failed to discover agent at {agent_url}: {e}")
            raise

    def register_agent(self, agent_url: str, card: AgentCard) -> None:
        """
        Register an agent's card locally (for local agents).

        Args:
            agent_url: URL or identifier for the agent
            card: The agent's AgentCard
        """
        self._agent_registry[agent_url] = card

    async def send_message(
        self,
        agent_url: str,
        message: Message,
        context_id: Optional[str] = None
    ) -> A2ATask:
        """
        Send a message to a remote agent.

        Args:
            agent_url: URL of the target agent
            message: Message to send
            context_id: Optional conversation context ID

        Returns:
            A2ATask representing the pending task
        """
        client = self._get_client()
        task_id = str(uuid.uuid4())

        # Build JSON-RPC request
        request = {
            "jsonrpc": "2.0",
            "method": "message/send",
            "params": {
                "message": {
                    "role": message.role.value,
                    "parts": [{"type": p.type, "text" if p.type == "text" else "data": p.content} for p in message.parts],
                    "messageId": message.id,
                    "contextId": context_id or message.context_id
                }
            },
            "id": task_id
        }

        try:
            response = await client.post(
                agent_url,
                json=request,
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()
            result = response.json()

            return A2ATask(
                id=task_id,
                message=message,
                source_agent="orchestrator",
                target_agent=agent_url,
                status=TaskStatus.COMPLETED.value if "result" in result else TaskStatus.PENDING.value,
                result=result.get("result")
            )

        except httpx.HTTPError as e:
            logger.error(f"Failed to send message to {agent_url}: {e}")
            return A2ATask(
                id=task_id,
                message=message,
                source_agent="orchestrator",
                target_agent=agent_url,
                status=TaskStatus.FAILED.value,
                result={"error": str(e)}
            )

    async def send_message_streaming(
        self,
        agent_url: str,
        message: Message,
        context_id: Optional[str] = None
    ) -> AsyncGenerator[dict[str, Any], None]:
        """
        Send a message and receive streaming response.

        Uses Server-Sent Events (SSE) for streaming.

        Args:
            agent_url: URL of the target agent
            message: Message to send
            context_id: Optional conversation context ID

        Yields:
            Streaming response chunks
        """
        client = self._get_client()
        task_id = str(uuid.uuid4())

        request = {
            "jsonrpc": "2.0",
            "method": "message/stream",
            "params": {
                "message": {
                    "role": message.role.value,
                    "parts": [{"type": p.type, "text" if p.type == "text" else "data": p.content} for p in message.parts],
                    "messageId": message.id,
                    "contextId": context_id or message.context_id
                }
            },
            "id": task_id
        }

        try:
            async with client.stream(
                "POST",
                agent_url,
                json=request,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream"
                }
            ) as response:
                response.raise_for_status()

                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data = json.loads(line[6:])
                        yield data

        except httpx.HTTPError as e:
            logger.error(f"Streaming failed for {agent_url}: {e}")
            yield {"error": str(e), "status": "failed"}

    async def get_task_status(self, agent_url: str, task_id: str) -> TaskStatus:
        """
        Get the status of a task.

        Args:
            agent_url: URL of the agent handling the task
            task_id: ID of the task

        Returns:
            Current TaskStatus
        """
        client = self._get_client()

        request = {
            "jsonrpc": "2.0",
            "method": "task/status",
            "params": {"taskId": task_id},
            "id": str(uuid.uuid4())
        }

        try:
            response = await client.post(agent_url, json=request)
            response.raise_for_status()
            result = response.json()
            return TaskStatus(result.get("result", {}).get("status", "pending"))
        except Exception as e:
            logger.error(f"Failed to get task status: {e}")
            return TaskStatus.FAILED

    async def cancel_task(self, agent_url: str, task_id: str) -> bool:
        """
        Cancel a running task.

        Args:
            agent_url: URL of the agent handling the task
            task_id: ID of the task to cancel

        Returns:
            True if cancellation was successful
        """
        client = self._get_client()

        request = {
            "jsonrpc": "2.0",
            "method": "task/cancel",
            "params": {"taskId": task_id},
            "id": str(uuid.uuid4())
        }

        try:
            response = await client.post(agent_url, json=request)
            response.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Failed to cancel task: {e}")
            return False


class A2AServer:
    """
    Server for handling A2A protocol requests.

    This server exposes an agent's capabilities and handles incoming
    messages from other agents.
    """

    def __init__(
        self,
        agent_card: AgentCard,
        message_handler: Callable[[Message], Any],
        port: int = 9000
    ):
        """
        Initialize the A2A server.

        Args:
            agent_card: This agent's capability card
            message_handler: Function to handle incoming messages
            port: Port to listen on
        """
        self.agent_card = agent_card
        self.message_handler = message_handler
        self.port = port
        self._tasks: dict[str, A2ATask] = {}

    def get_agent_card_json(self) -> dict[str, Any]:
        """Get the agent card as JSON for the well-known endpoint."""
        return self.agent_card.to_dict()

    async def handle_request(self, request: dict[str, Any]) -> dict[str, Any]:
        """
        Handle an incoming JSON-RPC request.

        Args:
            request: JSON-RPC request

        Returns:
            JSON-RPC response
        """
        method = request.get("method")
        params = request.get("params", {})
        request_id = request.get("id")

        if method == "message/send":
            return await self._handle_message_send(params, request_id)
        elif method == "task/status":
            return await self._handle_task_status(params, request_id)
        elif method == "task/cancel":
            return await self._handle_task_cancel(params, request_id)
        else:
            return {
                "jsonrpc": "2.0",
                "error": {"code": -32601, "message": f"Method not found: {method}"},
                "id": request_id
            }

    async def _handle_message_send(
        self,
        params: dict[str, Any],
        request_id: str
    ) -> dict[str, Any]:
        """Handle message/send method."""
        try:
            msg_data = params.get("message", {})
            message = Message(
                id=msg_data.get("messageId", str(uuid.uuid4())),
                role=MessageRole(msg_data.get("role", "user")),
                parts=[MessagePart(type=p.get("type", "text"), content=p.get("text", p.get("data", ""))) for p in msg_data.get("parts", [])],
                context_id=msg_data.get("contextId")
            )

            # Create task
            task = A2ATask(
                id=request_id,
                message=message,
                source_agent="remote",
                target_agent=self.agent_card.name,
                status=TaskStatus.IN_PROGRESS.value
            )
            self._tasks[request_id] = task

            # Process message
            result = await self.message_handler(message)

            # Update task
            task.status = TaskStatus.COMPLETED.value
            task.result = result

            return {
                "jsonrpc": "2.0",
                "result": result,
                "id": request_id
            }

        except Exception as e:
            logger.error(f"Error handling message: {e}")
            return {
                "jsonrpc": "2.0",
                "error": {"code": -32000, "message": str(e)},
                "id": request_id
            }

    async def _handle_task_status(
        self,
        params: dict[str, Any],
        request_id: str
    ) -> dict[str, Any]:
        """Handle task/status method."""
        task_id = params.get("taskId")
        task = self._tasks.get(task_id)

        if task:
            return {
                "jsonrpc": "2.0",
                "result": {"status": task.status, "result": task.result},
                "id": request_id
            }
        else:
            return {
                "jsonrpc": "2.0",
                "error": {"code": -32001, "message": "Task not found"},
                "id": request_id
            }

    async def _handle_task_cancel(
        self,
        params: dict[str, Any],
        request_id: str
    ) -> dict[str, Any]:
        """Handle task/cancel method."""
        task_id = params.get("taskId")
        task = self._tasks.get(task_id)

        if task and task.status == TaskStatus.IN_PROGRESS.value:
            task.status = TaskStatus.CANCELLED.value
            return {
                "jsonrpc": "2.0",
                "result": {"cancelled": True},
                "id": request_id
            }
        else:
            return {
                "jsonrpc": "2.0",
                "result": {"cancelled": False},
                "id": request_id
            }


# Agent registry for local development
class LocalAgentRegistry:
    """
    Registry for managing local agent instances.

    In production, agent discovery happens via A2A protocol.
    For local development, this provides direct agent references.
    """

    _instance: Optional["LocalAgentRegistry"] = None
    _agents: dict[AgentType, Any] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._agents = {}
        return cls._instance

    def register(self, agent_type: AgentType, agent: Any) -> None:
        """Register a local agent."""
        self._agents[agent_type] = agent

    def get(self, agent_type: AgentType) -> Optional[Any]:
        """Get a registered agent."""
        return self._agents.get(agent_type)

    def get_all(self) -> dict[AgentType, Any]:
        """Get all registered agents."""
        return self._agents.copy()


def get_agent_registry() -> LocalAgentRegistry:
    """Get the global agent registry."""
    return LocalAgentRegistry()
