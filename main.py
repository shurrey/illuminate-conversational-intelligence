"""
Illuminate Conversational Intelligence - API Server

FastAPI server that exposes the multi-agent system via REST API.
Supports both local mode (direct function calls) and A2A mode (agent-to-agent protocol).
"""
import os
import logging
import asyncio
import threading
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Configure logging
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("API")

# A2A server threads (global for cleanup)
_a2a_servers: list = []
_a2a_threads: list[threading.Thread] = []


# Global mock mode flag for security
MOCK_MODE = True

# Track cancelled request IDs for cancellation support
_cancelled_requests: set[str] = set()


def is_request_cancelled(request_id: Optional[str]) -> bool:
    """Check if a request has been cancelled."""
    return request_id is not None and request_id in _cancelled_requests


def cancel_request(request_id: str) -> bool:
    """Mark a request as cancelled."""
    _cancelled_requests.add(request_id)
    return True


def clear_cancelled_request(request_id: str):
    """Remove a request from the cancelled set (cleanup)."""
    _cancelled_requests.discard(request_id)

# Request/Response models
class ChatRequest(BaseModel):
    """Chat request model - supports both simple and A2A formats."""
    # Simple format
    message: Optional[str] = None
    context_id: Optional[str] = None
    request_id: Optional[str] = None  # For cancellation support
    # A2A JSON-RPC format
    jsonrpc: Optional[str] = None
    method: Optional[str] = None
    params: Optional[dict] = None
    id: Optional[str] = None

    def get_message_text(self) -> str:
        """Extract message text from either format."""
        # Simple format
        if self.message:
            return self.message
        # A2A format: params.message.parts[0].text
        if self.params and "message" in self.params:
            msg = self.params["message"]
            if "parts" in msg and msg["parts"]:
                for part in msg["parts"]:
                    if part.get("type") == "text":
                        return part.get("text", "")
        return ""

    def get_context_id(self) -> Optional[str]:
        """Extract context_id from either format."""
        # Simple format
        if self.context_id:
            return self.context_id
        # A2A format: params.message.contextId
        if self.params and "message" in self.params:
            return self.params["message"].get("contextId")
        return None

    def get_request_id(self) -> Optional[str]:
        """Extract request_id for cancellation support."""
        # Simple format
        if self.request_id:
            return self.request_id
        # A2A format: use id field or params.message.messageId
        if self.id:
            return self.id
        if self.params and "message" in self.params:
            return self.params["message"].get("messageId")
        return None


class ChatResponse(BaseModel):
    """Chat response model."""
    text: str
    artifacts: list = []
    context_id: Optional[str] = None
    sources: Optional[list] = None


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    version: str


def _run_a2a_server_in_thread(server, name: str, host: str, port: int):
    """Run an A2A server in its own thread with a new event loop."""
    def target():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            logger.info(f"Starting {name} A2A server on {host}:{port}")
            # Strands A2AServer uses .serve() method
            loop.run_until_complete(server.serve())
        except Exception as e:
            logger.error(f"Error in {name} A2A server: {e}")
        finally:
            loop.close()

    thread = threading.Thread(target=target, name=f"a2a-{name}", daemon=True)
    thread.start()
    return thread


def _start_a2a_servers():
    """Start the Learning A2A server in a background thread."""
    global _a2a_servers, _a2a_threads

    # Get MCP tools for agents (uses property, not method)
    from agents.shared.snowflake_mcp import get_mcp_manager
    mcp_manager = get_mcp_manager()
    tools = mcp_manager.tools

    # Import and create A2A server for the Learning agent
    from agents.learning import create_a2a_server as create_learning_server

    # Create server with configured port
    learning_port = 9001
    learning_server = create_learning_server(port=learning_port, tools=tools)

    _a2a_servers = [learning_server]

    # Start server in its own thread
    _a2a_threads.append(_run_a2a_server_in_thread(learning_server, "learning", "127.0.0.1", learning_port))

    # Give server time to start
    import time
    time.sleep(1)

    logger.info("Learning A2A server started")


def _stop_a2a_servers():
    """Stop all A2A servers."""
    global _a2a_servers, _a2a_threads

    for server in _a2a_servers:
        try:
            # A2A servers typically have a stop method
            if hasattr(server, 'stop'):
                asyncio.run(server.stop())
        except Exception as e:
            logger.warning(f"Error stopping A2A server: {e}")

    _a2a_servers.clear()
    _a2a_threads.clear()
    logger.info("All A2A servers stopped")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    logger.info("Starting Illuminate Conversational Intelligence API")

    # Load environment variables
    from dotenv import load_dotenv
    load_dotenv()

    # Check if A2A mode is enabled and mock mode
    use_a2a = os.environ.get("ILLUMINATE_USE_A2A", "false").lower() == "true"
    mock_mode = os.environ.get("ILLUMINATE_MOCK_MODE", "true").lower() == "true"
    
    # Set global MOCK_MODE for security checks
    global MOCK_MODE
    MOCK_MODE = mock_mode

    # Start Snowflake MCP server (or mock tools)
    from agents.shared.snowflake_mcp import get_mcp_manager
    mcp_manager = get_mcp_manager()
    mcp_manager.start()

    # If A2A mode, start specialist A2A servers before initializing orchestrator
    if use_a2a:
        logger.info("A2A mode enabled - starting specialist A2A servers")
        _start_a2a_servers()

    # Initialize orchestrator (will auto-detect A2A mode from env var)
    from agents.orchestrator.agent import get_orchestrator_agent
    get_orchestrator_agent()
    logger.info(f"Orchestrator initialized (A2A mode: {use_a2a})")

    yield

    # Shutdown
    logger.info("Shutting down API")

    if use_a2a:
        _stop_a2a_servers()

    mcp_manager.stop()


# Create FastAPI app
app = FastAPI(
    title="Illuminate Conversational Intelligence",
    description="Natural language access to Anthology Illuminate educational data",
    version="0.1.0",
    lifespan=lifespan
)

# CORS middleware with environment-based origins
allowed_origins = [
    "http://localhost:3000",  # React dev server
    "http://localhost:5173",  # Vite dev server
]

# In production, use environment variable or default to secure origin
if not MOCK_MODE:
    prod_origins = os.environ.get("ALLOWED_ORIGINS", "https://illuminate.anthology.com")
    allowed_origins = prod_origins.split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    return HealthResponse(status="healthy", version="0.1.0")


@app.post("/api/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    authorization: Optional[str] = Header(None)
):
    """
    Send a message to the conversational AI.

    Args:
        request: Chat request with message and optional context_id
        authorization: Optional Bearer token for authentication

    Returns:
        ChatResponse with AI response and any data artifacts
    """
    # In production, validate authorization header
    # For dev/mock mode, accept any request

    try:
        from agents.orchestrator.agent import query

        # Extract message from either simple or A2A format
        message_text = request.get_message_text()
        context_id = request.get_context_id()

        if not message_text:
            raise HTTPException(status_code=400, detail="No message provided")

        logger.info(f"Chat request: message='{message_text[:100]}...', context_id={context_id}")

        result = await query(message_text, context_id)

        return ChatResponse(
            text=result.get("text", ""),
            artifacts=result.get("artifacts", []),
            context_id=result.get("context_id"),
            sources=result.get("sources")
        )

    except Exception as e:
        logger.error(f"Error processing chat request: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/chat/stream")
async def chat_stream(
    request: ChatRequest,
    authorization: Optional[str] = Header(None)
):
    """
    Send a message and receive streaming response via Server-Sent Events.

    Streams events as the query is processed:
    - status: Processing status updates
    - routing: Agent routing decision
    - thinking: Agent is processing
    - complete: Final response with text and artifacts
    - error: Error occurred
    - cancelled: Request was cancelled
    """
    from fastapi.responses import StreamingResponse
    from agents.orchestrator.agent import query_streaming
    import json

    message_text = request.get_message_text()
    context_id = request.get_context_id()
    request_id = request.get_request_id()

    if not message_text:
        raise HTTPException(status_code=400, detail="No message provided")

    logger.info(f"Streaming chat request: message='{message_text[:100]}...', context_id={context_id}, request_id={request_id}")

    async def event_generator():
        """Generate Server-Sent Events from the streaming query."""
        try:
            async for event in query_streaming(message_text, context_id):
                # Check if request was cancelled
                if is_request_cancelled(request_id):
                    logger.info(f"Request {request_id} was cancelled")
                    cancelled_event = json.dumps({"type": "cancelled", "message": "Request cancelled by user"})
                    yield f"data: {cancelled_event}\n\n"
                    break

                # Format as SSE: data: {json}\n\n
                event_data = json.dumps(event)
                yield f"data: {event_data}\n\n"
        except Exception as e:
            logger.error(f"Error in streaming: {e}")
            error_event = json.dumps({"type": "error", "message": str(e)})
            yield f"data: {error_event}\n\n"
        finally:
            # Cleanup cancelled request tracking
            if request_id:
                clear_cancelled_request(request_id)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # Disable nginx buffering
        }
    )


@app.post("/api/chat/cancel/{request_id}")
async def cancel_chat(
    request_id: str,
    authorization: Optional[str] = Header(None)
):
    """
    Cancel an in-progress chat request.

    Args:
        request_id: The request ID to cancel

    Returns:
        Success status
    """
    logger.info(f"Cancelling request: {request_id}")
    success = cancel_request(request_id)
    return {"success": success, "request_id": request_id}


@app.get("/api/conversations/{context_id}")
async def get_conversation(
    context_id: str,
    authorization: Optional[str] = Header(None)
):
    """Get conversation history by context ID."""
    try:
        from agents.orchestrator.agent import get_orchestrator_agent

        agent = get_orchestrator_agent()
        history = agent.get_conversation_history(context_id)

        return {"messages": history}

    except Exception as e:
        logger.error(f"Error retrieving conversation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/conversations/{context_id}")
async def clear_conversation(
    context_id: str,
    authorization: Optional[str] = Header(None)
):
    """Clear a conversation context."""
    try:
        from agents.orchestrator.agent import get_orchestrator_agent

        agent = get_orchestrator_agent()
        success = agent.clear_conversation(context_id)

        return {"success": success}

    except Exception as e:
        logger.error(f"Error clearing conversation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8000)),
        reload=os.environ.get("RELOAD", "true").lower() == "true"
    )
