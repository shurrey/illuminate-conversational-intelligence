"""
Illuminate Conversational Intelligence - API Proxy Lambda

Thin proxy between the frontend and the Orchestrator AgentCore runtime.
No agent code runs here — all agent logic runs in Bedrock AgentCore runtimes.

Uses Lambda Web Adapter (LWA) to run FastAPI/uvicorn inside Lambda, enabling
real SSE streaming via RESPONSE_STREAM Function URL invoke mode. LWA proxies
incoming Lambda invocations to the local uvicorn server and streams bytes back.

Request flow:
    Frontend -> Lambda Function URL (RESPONSE_STREAM) -> LWA -> uvicorn/FastAPI
        -> Orchestrator AgentCore (A2A) -> SQL, Analyst, Writer, Validator
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

ORCHESTRATOR_ENDPOINT_URL = os.environ.get("ORCHESTRATOR_ENDPOINT_URL", "")
USER_POOL_ID = os.environ.get("USER_POOL_ID", "")
USER_POOL_CLIENT_ID = os.environ.get("USER_POOL_CLIENT_ID", "")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
ACCOUNT_ID = os.environ.get("ACCOUNT_ID", "442606396405")
ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:5173")

# A2A protocol timeout (seconds) - agent queries can be slow
A2A_TIMEOUT = float(os.environ.get("A2A_TIMEOUT", "300"))


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
# A2A Client for AgentCore Communication
# =============================================================================

class AgentCoreA2AClient:
    """
    Lightweight A2A client for forwarding requests to the Orchestrator
    AgentCore runtime endpoint.

    When agents are configured with OAuth authorization, the AWS SDK cannot be
    used for invoke_agent_runtime.  Instead we make direct HTTPS POST requests
    and pass the user's JWT in the Authorization header.
    """

    def __init__(self, endpoint_url: str, timeout: float = 300.0):
        self.timeout = timeout
        # Ensure the endpoint URL ends with /invocations
        self._endpoint_url = endpoint_url.rstrip("/")
        if not self._endpoint_url.endswith("/invocations"):
            self._endpoint_url += "/invocations"
        # OAuth HTTPS calls require accountId as a query parameter
        self._endpoint_url += f"?accountId={ACCOUNT_ID}&qualifier=DEFAULT"
        logger.info(f"AgentCore client initialized with URL: {self._endpoint_url}")

    def _build_a2a_request(self, method: str, message_text: str, context_id: Optional[str] = None) -> dict:
        return {
            "jsonrpc": "2.0",
            "method": method,
            "params": {
                "message": {
                    "role": "user",
                    "parts": [{"kind": "text", "text": message_text}],
                    "messageId": str(uuid.uuid4()),
                    "contextId": context_id or str(uuid.uuid4())
                }
            },
            "id": str(uuid.uuid4())
        }

    def _invoke_https(self, payload: bytes, auth_token: Optional[str] = None) -> bytes:
        """Make a direct HTTPS POST to the AgentCore runtime endpoint."""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"

        resp = http_requests.post(
            self._endpoint_url,
            data=payload,
            headers=headers,
            timeout=self.timeout,
        )

        logger.info(f"AgentCore response status={resp.status_code}, body={resp.text[:1000]}")

        if resp.status_code >= 400:
            raise Exception(f"AgentCore returned {resp.status_code}: {resp.text[:500]}")

        return resp.content

    async def send_message(
        self,
        message_text: str,
        context_id: Optional[str] = None,
        auth_token: Optional[str] = None
    ) -> dict:
        """Send a message to the Orchestrator via HTTPS."""
        import asyncio

        a2a_request = self._build_a2a_request("message/send", message_text, context_id)
        payload = json.dumps(a2a_request).encode('utf-8')

        logger.info(f"Invoking AgentCore runtime: {self._endpoint_url}")

        loop = asyncio.get_event_loop()
        response_body = await loop.run_in_executor(
            None, lambda: self._invoke_https(payload, auth_token)
        )

        logger.info(f"AgentCore response length: {len(response_body)}")

        result = json.loads(response_body.decode('utf-8'))
        logger.info(f"AgentCore response keys: {list(result.keys())}")

        if "error" in result:
            error = result["error"]
            raise Exception(error.get("message", "AgentCore error"))

        return result.get("result", result)

    async def send_message_streaming(
        self,
        message_text: str,
        context_id: Optional[str] = None,
        auth_token: Optional[str] = None
    ):
        """Send a message and stream response events from AgentCore.

        Yields events in the format expected by the frontend:
        - {type: "status", message: "..."}
        - {type: "complete", data: {text, artifacts, contextId}}
        - {type: "error", message: "..."}
        """
        import asyncio

        # Emit a status event so the frontend shows progress
        yield {"type": "status", "message": "Querying agents..."}

        a2a_request = self._build_a2a_request("message/send", message_text, context_id)
        payload = json.dumps(a2a_request).encode('utf-8')

        logger.info(f"Invoking AgentCore runtime (streaming): {self._endpoint_url}")

        loop = asyncio.get_event_loop()
        response_body = await loop.run_in_executor(
            None, lambda: self._invoke_https(payload, auth_token)
        )

        if response_body:
            result = json.loads(response_body.decode('utf-8'))
            a2a_result = result.get("result", result)

            if "error" in result:
                yield {"type": "error", "message": result["error"].get("message", "AgentCore error")}
                return

            # Extract text from A2A response
            text = ""
            if isinstance(a2a_result, dict):
                # Try artifacts first
                for artifact in a2a_result.get("artifacts", []):
                    for part in artifact.get("parts", []):
                        if part.get("kind") == "text" or part.get("type") == "text":
                            text += part.get("text", "")
                # Fallback to history
                if not text:
                    for msg in reversed(a2a_result.get("history", [])):
                        if msg.get("role") == "agent":
                            for part in msg.get("parts", []):
                                if part.get("kind") == "text":
                                    text += part.get("text", "")
                            if text:
                                break

            # Extract chart markers from text and create frontend-format artifacts
            cleaned_text, chart_artifacts = extract_chart_configs(text)
            # Only include frontend-format artifacts (with 'type' field), not raw A2A artifacts
            artifacts = chart_artifacts if chart_artifacts else []
            if chart_artifacts:
                logger.info(f"Injected {len(chart_artifacts)} chart artifact(s) into streaming response")

            # Emit the complete event in the format the frontend expects
            yield {
                "type": "complete",
                "data": {
                    "text": cleaned_text,
                    "artifacts": artifacts,
                    "contextId": a2a_result.get("contextId") if isinstance(a2a_result, dict) else None,
                }
            }
        else:
            yield {"type": "error", "message": "Empty response from AgentCore"}


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

# A2A client singleton
_a2a_client: Optional[AgentCoreA2AClient] = None


def _get_a2a_client() -> AgentCoreA2AClient:
    """Get or create the A2A client for AgentCore communication."""
    global _a2a_client
    if _a2a_client is None:
        if not ORCHESTRATOR_ENDPOINT_URL:
            raise RuntimeError(
                "ORCHESTRATOR_ENDPOINT_URL environment variable is not set. "
                "Cannot forward requests to AgentCore."
            )
        _a2a_client = AgentCoreA2AClient(
            endpoint_url=ORCHESTRATOR_ENDPOINT_URL,
            timeout=A2A_TIMEOUT
        )
    return _a2a_client


def _extract_bearer_token(authorization: str) -> Optional[str]:
    """Extract the raw token from Authorization header."""
    parts = authorization.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return None


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
        client = _get_a2a_client()
        token = _extract_bearer_token(authorization)

        result = await client.send_message(
            message_text=message_text,
            context_id=context_id,
            auth_token=token
        )

        # Extract text from A2A response format
        text = result.get("text", "")
        if not text and "artifacts" in result:
            for artifact in result["artifacts"]:
                for part in artifact.get("parts", []):
                    if part.get("kind") == "text" or part.get("type") == "text":
                        text += part.get("text", "")

        # Extract chart markers from text and create frontend-format artifacts
        cleaned_text, chart_artifacts = extract_chart_configs(text)
        # Only include frontend-format artifacts (with 'type' field), not raw A2A artifacts
        artifacts = chart_artifacts if chart_artifacts else []
        if chart_artifacts:
            logger.info(f"Injected {len(chart_artifacts)} chart artifact(s) into response")

        return ChatResponse(
            text=cleaned_text,
            artifacts=artifacts,
            context_id=result.get("contextId", result.get("context_id", context_id)),
            sources=result.get("sources")
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
            client = _get_a2a_client()
            token = _extract_bearer_token(authorization)

            async for event in client.send_message_streaming(
                message_text=message_text,
                context_id=context_id,
                auth_token=token
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
