"""
Illuminate Conversational Intelligence - API Proxy Lambda

Thin proxy between the frontend and the Orchestrator AgentCore runtime.
No agent code runs here — all agent logic runs in Bedrock AgentCore runtimes.

Uses Lambda Web Adapter (LWA) to run FastAPI/uvicorn inside Lambda, enabling
real SSE streaming via RESPONSE_STREAM Function URL invoke mode. LWA proxies
incoming Lambda invocations to the local uvicorn server and streams bytes back.

Calls the orchestrator via boto3 invoke_agent_runtime (SigV4 auth). Streaming
requests use accept=text/event-stream to get real-time SSE events — tool calls
are mapped to user-friendly status messages so the frontend can show progress.

Request flow:
    Frontend -> Lambda Function URL (RESPONSE_STREAM) -> LWA -> uvicorn/FastAPI
        -> boto3 invoke_agent_runtime (SigV4) -> Orchestrator AgentCore (A2A)
        -> SQL, Analyst, Writer, Validator
"""
import os
import json
import logging
import re
import uuid
from typing import Optional

from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# JWT validation
from jose import jwt, JWTError
import requests as http_requests

# boto3 for AgentCore SDK calls (SigV4 auth handled automatically)
import boto3

# Configure logging
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("API-PROXY")


# =============================================================================
# Chart extraction from [CHART_CONFIG] text markers
# =============================================================================

_CHART_PATTERN = re.compile(r'\[CHART_CONFIG\]\s*(.*?)\s*\[/CHART_CONFIG\]', re.DOTALL)


def extract_chart_configs(text: str) -> tuple[str, list[dict]]:
    """Extract [CHART_CONFIG]{...}[/CHART_CONFIG] blocks from agent text.

    Returns (cleaned_text, list_of_frontend_chart_artifacts).
    """
    matches = list(_CHART_PATTERN.finditer(text))
    if not matches:
        return text, []

    charts = []
    for match in matches:
        try:
            config = json.loads(match.group(1))
            chart_type = config.get("chart_type", "bar")
            valid_types = ["bar", "line", "pie", "scatter", "histogram"]
            if chart_type not in valid_types:
                chart_type = "bar"

            chart_artifact = {
                "id": str(uuid.uuid4()),
                "type": "chart",
                "title": config.get("title", "Chart"),
                "data": {
                    "chart_type": chart_type,
                    "title": config.get("title", "Chart"),
                    "x_axis": config.get("x_axis", ""),
                    "y_axis": config.get("y_axis", ""),
                    "x_label": config.get("x_label", config.get("x_axis", "")),
                    "y_label": config.get("y_label", config.get("y_axis", "")),
                    "data": config.get("data", []),
                },
            }
            charts.append(chart_artifact)
            logger.info(f"Extracted chart: {chart_type} '{config.get('title')}' with {len(config.get('data', []))} points")
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning(f"Failed to parse chart config: {e}")

    # Remove markers from text and clean up whitespace
    cleaned = _CHART_PATTERN.sub('', text).strip()
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    return cleaned, charts


# =============================================================================
# Configuration from environment variables
# =============================================================================

ORCHESTRATOR_ARN = os.environ.get("ORCHESTRATOR_ARN", "")
USER_POOL_ID = os.environ.get("USER_POOL_ID", "")
USER_POOL_CLIENT_ID = os.environ.get("USER_POOL_CLIENT_ID", "")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
ACCOUNT_ID = os.environ.get("ACCOUNT_ID", "442606396405")
ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:5173")

# A2A protocol timeout (seconds) - agent queries can be slow
A2A_TIMEOUT = int(os.environ.get("A2A_TIMEOUT", "300"))


# =============================================================================
# JWT Token Validation (Cognito)
# =============================================================================

_jwks_cache: Optional[dict] = None
_jwks_cache_time: float = 0
JWKS_CACHE_TTL = 3600  # 1 hour


def _get_jwks() -> dict:
    """Get JWKS from Cognito (cached)."""
    global _jwks_cache, _jwks_cache_time
    import time

    if _jwks_cache and (time.time() - _jwks_cache_time) < JWKS_CACHE_TTL:
        return _jwks_cache

    jwks_url = f"https://cognito-idp.{AWS_REGION}.amazonaws.com/{USER_POOL_ID}/.well-known/jwks.json"
    response = http_requests.get(jwks_url, timeout=5)
    response.raise_for_status()

    _jwks_cache = response.json()
    _jwks_cache_time = time.time()
    return _jwks_cache


def _validate_token(token: str) -> Optional[dict]:
    """Validate a Cognito JWT token and return claims."""
    try:
        jwks = _get_jwks()
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header["kid"]

        key = None
        for jwk in jwks["keys"]:
            if jwk["kid"] == kid:
                key = jwk
                break

        if not key:
            return None

        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            issuer=f"https://cognito-idp.{AWS_REGION}.amazonaws.com/{USER_POOL_ID}",
            options={"verify_aud": False}
        )
        # Verify client_id for access tokens or aud for ID tokens
        token_client = claims.get("client_id") or claims.get("aud")
        if token_client != USER_POOL_CLIENT_ID:
            return None
        return claims

    except (JWTError, Exception):
        return None


def _get_user_from_token(authorization: Optional[str]) -> Optional[dict]:
    """Extract and validate user from Authorization header."""
    if not authorization:
        return None

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None

    return _validate_token(parts[1])


# =============================================================================
# Request/Response Models
# =============================================================================

class ChatRequest(BaseModel):
    """Chat request model - supports both simple and A2A formats."""
    message: Optional[str] = None
    context_id: Optional[str] = None
    request_id: Optional[str] = None
    jsonrpc: Optional[str] = None
    method: Optional[str] = None
    params: Optional[dict] = None
    id: Optional[str] = None

    def get_message_text(self) -> str:
        if self.message:
            return self.message
        if self.params and "message" in self.params:
            msg = self.params["message"]
            if "parts" in msg and msg["parts"]:
                for part in msg["parts"]:
                    if part.get("type") == "text":
                        return part.get("text", "")
        return ""

    def get_context_id(self) -> Optional[str]:
        if self.context_id:
            return self.context_id
        if self.params and "message" in self.params:
            return self.params["message"].get("contextId")
        return None

    def get_request_id(self) -> Optional[str]:
        if self.request_id:
            return self.request_id
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
    mode: str = "proxy"


# =============================================================================
# A2A Client for AgentCore Communication (boto3 / SigV4)
# =============================================================================

# Module-level boto3 client — created once per Lambda cold start.
# SigV4 auth is handled automatically by the Lambda execution role.
from botocore.config import Config as BotoConfig

_agentcore_boto3 = boto3.client(
    "bedrock-agentcore",
    region_name=AWS_REGION,
    config=BotoConfig(
        read_timeout=A2A_TIMEOUT,
        connect_timeout=10,
        retries={"max_attempts": 1},
    ),
)
logger.info(f"boto3 bedrock-agentcore client created (timeout={A2A_TIMEOUT}s)")


# Tool-name → user-friendly status message
_TOOL_STATUS = {
    "query_database": "Querying Snowflake database...",
    "list_objects": "Discovering database tables...",
    "describe_object": "Reading table schema...",
    "run_snowflake_query": "Executing SQL query...",
    "analyze_data": "Analyzing results...",
    "write_response": "Preparing response...",
    "validate_response": "Validating for compliance...",
}


def _build_a2a_request(method: str, message_text: str, context_id: Optional[str] = None) -> dict:
    """Build a JSON-RPC A2A request payload."""
    return {
        "jsonrpc": "2.0",
        "method": method,
        "params": {
            "message": {
                "role": "user",
                "parts": [{"kind": "text", "text": message_text}],
                "messageId": str(uuid.uuid4()),
                "contextId": context_id or str(uuid.uuid4()),
            }
        },
        "id": str(uuid.uuid4()),
    }


def _invoke_orchestrator_sync(message_text: str, context_id: Optional[str] = None) -> dict:
    """Invoke orchestrator via boto3 (synchronous, JSON response)."""
    payload = _build_a2a_request("message/send", message_text, context_id)
    response = _agentcore_boto3.invoke_agent_runtime(
        agentRuntimeArn=ORCHESTRATOR_ARN,
        contentType="application/json",
        accept="application/json",
        payload=json.dumps(payload).encode(),
    )
    body = json.loads(response["response"].read().decode())
    logger.info(f"AgentCore sync response keys: {list(body.keys())}")
    if "error" in body:
        raise Exception(body["error"].get("message", "AgentCore error"))
    return body.get("result", body)


def _invoke_orchestrator_stream(message_text: str, context_id: Optional[str] = None):
    """Invoke orchestrator via boto3 with SSE streaming. Yields raw SSE data strings."""
    payload = _build_a2a_request("message/stream", message_text, context_id)
    response = _agentcore_boto3.invoke_agent_runtime(
        agentRuntimeArn=ORCHESTRATOR_ARN,
        contentType="application/json",
        accept="text/event-stream",
        payload=json.dumps(payload).encode(),
    )

    # The response body is a botocore StreamingBody — read SSE lines incrementally
    stream = response["response"]
    buffer = ""
    while True:
        chunk = stream.read(4096)
        if not chunk:
            break
        buffer += chunk.decode("utf-8", errors="replace")
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            line = line.strip()
            if line.startswith("data:"):
                yield line[5:].strip()


def _extract_text_from_result(result: dict) -> str:
    """Extract text content from an A2A result dict."""
    text = ""
    for artifact in result.get("artifacts", []):
        for part in artifact.get("parts", []):
            if part.get("kind") == "text" and part.get("text"):
                text += part["text"]
    if not text:
        for msg in reversed(result.get("history", [])):
            if msg.get("role") == "agent":
                for part in msg.get("parts", []):
                    if part.get("kind") == "text":
                        text += part.get("text", "")
                if text:
                    break
    return text


async def send_message(message_text: str, context_id: Optional[str] = None) -> dict:
    """Send a message to the orchestrator (non-streaming) via boto3."""
    import asyncio
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, lambda: _invoke_orchestrator_sync(message_text, context_id)
    )


async def send_message_streaming(message_text: str, context_id: Optional[str] = None):
    """Stream A2A events from the orchestrator via boto3, yielding frontend events.

    Yields events in the format expected by the frontend:
    - {type: "status", message: "..."}
    - {type: "complete", data: {text, artifacts, contextId}}
    - {type: "error", message: "..."}
    """
    import asyncio
    import queue

    yield {"type": "status", "message": "Routing to orchestrator..."}

    full_text = ""
    result_context_id = None
    got_result = False
    loop = asyncio.get_event_loop()

    try:
        # Stream SSE events from boto3 in a background thread via queue
        event_queue: queue.Queue = queue.Queue()

        def _stream_to_queue():
            try:
                for data_str in _invoke_orchestrator_stream(message_text, context_id):
                    event_queue.put(data_str)
            except Exception as e:
                event_queue.put(json.dumps({"error": {"message": str(e)}}))
            finally:
                event_queue.put(None)  # sentinel

        loop.run_in_executor(None, _stream_to_queue)

        while True:
            try:
                data_str = await asyncio.wait_for(
                    loop.run_in_executor(None, lambda: event_queue.get(timeout=0.5)),
                    timeout=1.0,
                )
            except (asyncio.TimeoutError, Exception):
                continue

            if data_str is None:
                break

            try:
                event = json.loads(data_str)
            except json.JSONDecodeError:
                continue

            result = event.get("result", {})
            if not isinstance(result, dict):
                continue

            kind = result.get("kind", "")
            result_context_id = result.get("contextId") or result_context_id

            if kind == "status-update":
                status = result.get("status", {})
                state = status.get("state", "")

                if state == "working":
                    # Token-by-token text chunks from the orchestrator
                    msg = status.get("message", {})
                    if isinstance(msg, dict):
                        for part in msg.get("parts", []):
                            chunk = part.get("text", "")
                            if chunk:
                                # Check for tool name mentions (from orchestrator's internal logging)
                                for tool_name, friendly_msg in _TOOL_STATUS.items():
                                    if tool_name in chunk.lower():
                                        yield {"type": "status", "message": friendly_msg}
                                        break

                elif state in ("completed", "failed"):
                    got_result = True

            elif kind == "artifact-update":
                # Full response text arrives in artifact-update event
                artifact = result.get("artifact", {})
                for part in artifact.get("parts", []):
                    if part.get("kind") == "text" and part.get("text"):
                        full_text += part["text"]

            # Check for JSON-RPC error
            if "error" in event:
                error_msg = event["error"]
                if isinstance(error_msg, dict):
                    error_msg = error_msg.get("message", "AgentCore error")
                yield {"type": "error", "message": str(error_msg)}
                return

    except Exception as e:
        logger.error(f"Streaming failed, falling back to synchronous: {e}")
        yield {"type": "status", "message": "Processing request..."}
        try:
            result = await loop.run_in_executor(
                None, lambda: _invoke_orchestrator_sync(message_text, context_id)
            )
            if isinstance(result, dict):
                full_text = _extract_text_from_result(result)
                result_context_id = result.get("contextId")
                got_result = True
        except Exception as fallback_err:
            yield {"type": "error", "message": str(fallback_err)}
            return

    if not full_text and not got_result:
        yield {"type": "error", "message": "Empty response from AgentCore"}
        return

    cleaned_text, chart_artifacts = extract_chart_configs(full_text)
    artifacts = chart_artifacts if chart_artifacts else []
    if chart_artifacts:
        logger.info(f"Injected {len(chart_artifacts)} chart artifact(s) into streaming response")

    yield {
        "type": "complete",
        "data": {
            "text": cleaned_text,
            "artifacts": artifacts,
            "contextId": result_context_id,
        },
    }


# =============================================================================
# FastAPI Application
# =============================================================================

app = FastAPI(
    title="Illuminate Conversational Intelligence - API Proxy",
    description="Thin proxy Lambda forwarding requests to AgentCore Orchestrator",
    version="0.2.0"
)

# CORS middleware
origins = [o.strip() for o in ALLOWED_ORIGINS.split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

def _ensure_orchestrator_configured():
    """Fail fast if ORCHESTRATOR_ARN is not set."""
    if not ORCHESTRATOR_ARN:
        raise RuntimeError(
            "ORCHESTRATOR_ARN environment variable is not set. "
            "Cannot forward requests to AgentCore."
        )


# Track cancelled request IDs
_cancelled_requests: set[str] = set()


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    return HealthResponse(
        status="healthy",
        version="0.2.0",
        mode="proxy"
    )


@app.post("/api/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    authorization: str = Header(...)
):
    """
    Send a message to the Orchestrator AgentCore runtime.

    The request is forwarded via A2A protocol to the Orchestrator endpoint
    running in Bedrock AgentCore. All agent coordination happens there.
    """
    user = _get_user_from_token(authorization)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    logger.info(f"Authenticated user: {user.get('email', user.get('sub', 'unknown'))}")

    message_text = request.get_message_text()
    context_id = request.get_context_id()

    if not message_text:
        raise HTTPException(status_code=400, detail="No message provided")

    logger.info(f"Chat request: message='{message_text[:100]}...', context_id={context_id}")

    try:
        _ensure_orchestrator_configured()

        result = await send_message(
            message_text=message_text,
            context_id=context_id,
        )

        # Extract text from A2A response format
        text = _extract_text_from_result(result) if isinstance(result, dict) else ""

        # Extract chart markers from text and create frontend-format artifacts
        cleaned_text, chart_artifacts = extract_chart_configs(text)
        artifacts = chart_artifacts if chart_artifacts else []
        if chart_artifacts:
            logger.info(f"Injected {len(chart_artifacts)} chart artifact(s) into response")

        return ChatResponse(
            text=cleaned_text,
            artifacts=artifacts,
            context_id=result.get("contextId", result.get("context_id", context_id)) if isinstance(result, dict) else context_id,
            sources=result.get("sources") if isinstance(result, dict) else None,
        )

    except Exception as e:
        logger.error(f"Error forwarding to AgentCore: {e}")
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/api/chat/stream")
async def chat_stream(
    request: ChatRequest,
    authorization: str = Header(...)
):
    """
    Send a message and receive streaming response via Server-Sent Events.

    The request is forwarded to the Orchestrator AgentCore runtime, and
    streaming events are relayed back to the frontend.
    """
    user = _get_user_from_token(authorization)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    message_text = request.get_message_text()
    context_id = request.get_context_id()
    request_id = request.get_request_id()

    if not message_text:
        raise HTTPException(status_code=400, detail="No message provided")

    logger.info(
        f"Streaming chat request: message='{message_text[:100]}...', "
        f"context_id={context_id}, request_id={request_id}"
    )

    async def event_generator():
        """Relay SSE events from AgentCore to the frontend."""
        try:
            _ensure_orchestrator_configured()

            async for event in send_message_streaming(
                message_text=message_text,
                context_id=context_id,
            ):
                # Check if request was cancelled
                if request_id and request_id in _cancelled_requests:
                    logger.info(f"Request {request_id} was cancelled")
                    cancelled_event = json.dumps({
                        "type": "cancelled",
                        "message": "Request cancelled by user"
                    })
                    yield f"data: {cancelled_event}\n\n"
                    _cancelled_requests.discard(request_id)
                    break

                event_data = json.dumps(event)
                yield f"data: {event_data}\n\n"

        except Exception as e:
            logger.error(f"Error in streaming relay: {e}")
            error_event = json.dumps({
                "type": "error",
                "message": str(e)
            })
            yield f"data: {error_event}\n\n"
        finally:
            if request_id:
                _cancelled_requests.discard(request_id)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@app.post("/api/chat/cancel/{request_id}")
async def cancel_chat(
    request_id: str,
    authorization: Optional[str] = Header(None)
):
    """Cancel an in-progress chat request."""
    logger.info(f"Cancelling request: {request_id}")
    _cancelled_requests.add(request_id)
    return {"success": True, "request_id": request_id}


@app.get("/api/conversations/{context_id}")
async def get_conversation(
    context_id: str,
    authorization: str = Header(...)
):
    """
    Get conversation history by context ID.

    In proxy mode, conversation history is managed by AgentCore's memory
    system. This endpoint queries AgentCore for the conversation.
    """
    user = _get_user_from_token(authorization)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    # AgentCore manages conversation memory via STM
    # For now, return empty - conversation state is in AgentCore memory
    logger.info(f"Conversation history requested for context: {context_id}")
    return {"messages": []}


@app.delete("/api/conversations/{context_id}")
async def clear_conversation(
    context_id: str,
    authorization: str = Header(...)
):
    """Clear a conversation context."""
    user = _get_user_from_token(authorization)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    logger.info(f"Clear conversation requested for context: {context_id}")
    return {"success": True}


# =============================================================================
# Lambda Web Adapter entry point
# =============================================================================
# When run as __main__ (via run.sh), start uvicorn.  LWA handles proxying
# Lambda invocations to the local HTTP server and streaming responses back.

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8080"))
    logger.info(f"Starting uvicorn on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
