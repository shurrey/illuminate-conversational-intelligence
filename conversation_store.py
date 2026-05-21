"""
DynamoDB-backed conversation memory.

Stores message history per context_id with automatic TTL expiry.
Replaces AgentCore STM memory at ~$0.25/month instead of AgentCore pricing.
"""
import json
import os
import time
import logging
from typing import Optional

import boto3
from boto3.dynamodb.conditions import Key

logger = logging.getLogger("API-PROXY")

_TABLE_NAME = os.environ.get("CONVERSATION_TABLE", "illuminate-conversations-dev")
_TTL_SECONDS = int(os.environ.get("CONVERSATION_TTL", str(30 * 24 * 3600)))  # 30 days
_MAX_MESSAGES = int(os.environ.get("CONVERSATION_MAX_MESSAGES", "50"))

_table = None


def _get_table():
    """Lazy-init DynamoDB Table resource."""
    global _table
    if _table is None:
        dynamodb = boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "us-east-1"))
        _table = dynamodb.Table(_TABLE_NAME)
    return _table


def load_history(context_id: str) -> list[dict]:
    """Load conversation messages for a context_id.

    Returns list of {"role": "user"|"assistant", "content": "..."} dicts,
    ordered chronologically. Returns empty list if no history.
    """
    if not context_id:
        return []
    try:
        table = _get_table()
        response = table.get_item(Key={"context_id": context_id})
        item = response.get("Item")
        if not item:
            return []
        messages = json.loads(item.get("messages", "[]"))
        return messages[-_MAX_MESSAGES:]
    except Exception as e:
        logger.warning(f"Failed to load conversation history: {e}")
        return []


def save_turn(context_id: str, user_message: str, assistant_message: str):
    """Append a user+assistant turn to conversation history.

    Creates the item if it doesn't exist, appends if it does.
    Trims to MAX_MESSAGES and sets TTL for automatic cleanup.
    """
    if not context_id:
        return
    try:
        history = load_history(context_id)
        history.append({"role": "user", "content": user_message})
        history.append({"role": "assistant", "content": assistant_message})
        # Trim to max
        history = history[-_MAX_MESSAGES:]

        table = _get_table()
        table.put_item(Item={
            "context_id": context_id,
            "messages": json.dumps(history),
            "updated_at": int(time.time()),
            "ttl": int(time.time()) + _TTL_SECONDS,
        })
    except Exception as e:
        logger.warning(f"Failed to save conversation history: {e}")


def clear_history(context_id: str):
    """Delete conversation history for a context_id."""
    if not context_id:
        return
    try:
        table = _get_table()
        table.delete_item(Key={"context_id": context_id})
    except Exception as e:
        logger.warning(f"Failed to clear conversation history: {e}")
