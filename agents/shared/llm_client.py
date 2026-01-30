"""
LLM Client for Illuminate Conversational Intelligence

Provides a unified interface for invoking LLMs across all agents.
Supports both local (Anthropic API) and AWS Bedrock deployments.
"""

import os
import json
import logging
from typing import Optional
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger("LLM")


class ModelTier(Enum):
    """Model tiers for different agent roles."""
    ORCHESTRATOR = "orchestrator"  # Sonnet - routing and coordination
    VALIDATOR = "validator"        # Sonnet - validation and judgment
    WORKER = "worker"              # Opus - deep analysis and data work


@dataclass
class ModelConfig:
    """Configuration for LLM models."""
    # Anthropic API model IDs
    anthropic_orchestrator: str = "claude-sonnet-4-20250514"
    anthropic_validator: str = "claude-sonnet-4-20250514"
    anthropic_worker: str = "claude-opus-4-20250514"

    # AWS Bedrock model IDs
    bedrock_orchestrator: str = "anthropic.claude-sonnet-4-20250514-v1:0"
    bedrock_validator: str = "anthropic.claude-sonnet-4-20250514-v1:0"
    bedrock_worker: str = "anthropic.claude-opus-4-20250514-v1:0"

    # Inference settings
    max_tokens: int = 4096
    temperature_orchestrator: float = 0.3  # Lower for consistent routing
    temperature_validator: float = 0.1     # Very low for strict validation
    temperature_worker: float = 0.7        # Higher for analytical flexibility


# Global config instance
_config: Optional[ModelConfig] = None


def get_model_config() -> ModelConfig:
    """Get or create the model configuration."""
    global _config
    if _config is None:
        _config = ModelConfig(
            anthropic_orchestrator=os.environ.get('MODEL_ORCHESTRATOR', ModelConfig.anthropic_orchestrator),
            anthropic_validator=os.environ.get('MODEL_VALIDATOR', ModelConfig.anthropic_validator),
            anthropic_worker=os.environ.get('MODEL_WORKER', ModelConfig.anthropic_worker),
            bedrock_orchestrator=os.environ.get('BEDROCK_MODEL_ORCHESTRATOR', ModelConfig.bedrock_orchestrator),
            bedrock_validator=os.environ.get('BEDROCK_MODEL_VALIDATOR', ModelConfig.bedrock_validator),
            bedrock_worker=os.environ.get('BEDROCK_MODEL_WORKER', ModelConfig.bedrock_worker),
        )
    return _config


class LLMClient:
    """
    Unified LLM client supporting Anthropic API and AWS Bedrock.
    """

    def __init__(self, tier: ModelTier = ModelTier.WORKER, caller: Optional[str] = None):
        """
        Initialize LLM client.

        Args:
            tier: The model tier to use (orchestrator, validator, or worker)
            caller: Optional name of the calling agent for logging context
        """
        self.tier = tier
        self.caller = caller or tier.value.upper()
        self.config = get_model_config()
        self._use_bedrock = os.environ.get('USE_BEDROCK', 'false').lower() == 'true'
        self._anthropic_client = None
        self._bedrock_client = None

    @property
    def model_id(self) -> str:
        """Get the appropriate model ID based on tier and deployment."""
        if self._use_bedrock:
            if self.tier == ModelTier.ORCHESTRATOR:
                return self.config.bedrock_orchestrator
            elif self.tier == ModelTier.VALIDATOR:
                return self.config.bedrock_validator
            else:
                return self.config.bedrock_worker
        else:
            if self.tier == ModelTier.ORCHESTRATOR:
                return self.config.anthropic_orchestrator
            elif self.tier == ModelTier.VALIDATOR:
                return self.config.anthropic_validator
            else:
                return self.config.anthropic_worker

    @property
    def temperature(self) -> float:
        """Get the appropriate temperature based on tier."""
        if self.tier == ModelTier.ORCHESTRATOR:
            return self.config.temperature_orchestrator
        elif self.tier == ModelTier.VALIDATOR:
            return self.config.temperature_validator
        else:
            return self.config.temperature_worker

    def _get_anthropic_client(self):
        """Get or create Anthropic client."""
        if self._anthropic_client is None:
            try:
                import anthropic
                self._anthropic_client = anthropic.Anthropic(
                    api_key=os.environ.get('ANTHROPIC_API_KEY')
                )
            except ImportError:
                raise ImportError("anthropic package required. Install with: pip install anthropic")
        return self._anthropic_client

    def _get_bedrock_client(self):
        """Get or create Bedrock client."""
        if self._bedrock_client is None:
            try:
                import boto3
                self._bedrock_client = boto3.client('bedrock-runtime')
            except ImportError:
                raise ImportError("boto3 package required. Install with: pip install boto3")
        return self._bedrock_client

    async def invoke(
        self,
        system_prompt: str,
        user_message: str,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None
    ) -> str:
        """
        Invoke the LLM with the given prompts.

        Args:
            system_prompt: The system prompt to set context
            user_message: The user message to process
            max_tokens: Optional override for max tokens
            temperature: Optional override for temperature

        Returns:
            The model's response text
        """
        max_tokens = max_tokens or self.config.max_tokens
        temperature = temperature if temperature is not None else self.temperature

        logger.info(f"[{self.caller}] Invoking LLM: tier={self.tier.value}, model={self.model_id}")

        if self._use_bedrock:
            return await self._invoke_bedrock(system_prompt, user_message, max_tokens, temperature)
        else:
            return await self._invoke_anthropic(system_prompt, user_message, max_tokens, temperature)

    async def _invoke_anthropic(
        self,
        system_prompt: str,
        user_message: str,
        max_tokens: int,
        temperature: float
    ) -> str:
        """Invoke using Anthropic API."""
        import asyncio

        client = self._get_anthropic_client()

        # Run in executor since anthropic client is sync
        def _call():
            response = client.messages.create(
                model=self.model_id,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": user_message}
                ]
            )
            return response.content[0].text

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _call)

    async def _invoke_bedrock(
        self,
        system_prompt: str,
        user_message: str,
        max_tokens: int,
        temperature: float
    ) -> str:
        """Invoke using AWS Bedrock."""
        import asyncio

        client = self._get_bedrock_client()

        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system_prompt,
            "messages": [
                {"role": "user", "content": user_message}
            ]
        })

        def _call():
            response = client.invoke_model(
                modelId=self.model_id,
                body=body,
                contentType="application/json",
                accept="application/json"
            )
            response_body = json.loads(response['body'].read())
            return response_body['content'][0]['text']

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _call)

    async def invoke_with_json_response(
        self,
        system_prompt: str,
        user_message: str,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None
    ) -> dict:
        """
        Invoke LLM and parse JSON response.

        Args:
            system_prompt: System prompt (should instruct JSON output)
            user_message: User message
            max_tokens: Optional max tokens
            temperature: Optional temperature

        Returns:
            Parsed JSON response as dict
        """
        response = await self.invoke(system_prompt, user_message, max_tokens, temperature)

        # Extract JSON from response (handle markdown code blocks)
        text = response.strip()
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]

        try:
            return json.loads(text.strip())
        except json.JSONDecodeError as e:
            logger.error(f"[{self.caller}] Failed to parse JSON response: {e}")
            logger.debug(f"[{self.caller}] Raw response: {response}")
            raise ValueError(f"LLM did not return valid JSON: {e}")


# Convenience functions for creating clients
def get_orchestrator_llm(caller: Optional[str] = "ORCHESTRATOR") -> LLMClient:
    """Get LLM client configured for orchestrator (Sonnet)."""
    return LLMClient(ModelTier.ORCHESTRATOR, caller=caller)


def get_validator_llm(caller: Optional[str] = "VALIDATOR") -> LLMClient:
    """Get LLM client configured for validator (Sonnet)."""
    return LLMClient(ModelTier.VALIDATOR, caller=caller)


def get_worker_llm(caller: Optional[str] = None) -> LLMClient:
    """Get LLM client configured for worker agents (Opus)."""
    return LLMClient(ModelTier.WORKER, caller=caller)
