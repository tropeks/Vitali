"""
LLM Gateway — abstract interface + Claude implementation.
Decision B1: abstract class retained for future AI features (clinical notes, prescription safety).
"""

import logging
import time
from abc import ABC, abstractmethod

from django.conf import settings

logger = logging.getLogger(__name__)

MODEL_HAIKU = "claude-haiku-4-5-20251001"


class LLMGatewayError(Exception):
    """Raised when an LLM call fails unrecoverably."""

    pass


class LLMGateway(ABC):
    """Abstract interface for LLM completions."""

    @abstractmethod
    def complete(self, system: str, user: str, max_tokens: int = 512) -> tuple[str, int, int]:
        """
        Returns (response_text, tokens_in, tokens_out).
        Raises LLMGatewayError on non-recoverable failure.
        """
        raise NotImplementedError


class ClaudeGateway(LLMGateway):
    """
    Anthropic Claude implementation.
    Uses claude-haiku-4-5-20251001 for cost efficiency on TUSS coding.
    """

    def __init__(
        self, api_key: str | None = None, model: str = MODEL_HAIKU, timeout: int | None = None
    ):
        self.model = model
        self.timeout: int = timeout or int(getattr(settings, "AI_SUGGEST_TIMEOUT_S", 5))
        self._api_key = api_key or getattr(settings, "ANTHROPIC_API_KEY", "")

    def complete(self, system: str, user: str, max_tokens: int = 512) -> tuple[str, int, int]:
        try:
            import anthropic
        except ImportError as err:
            raise LLMGatewayError(
                "anthropic SDK not installed. Add anthropic>=0.40 to requirements."
            ) from err

        if not self._api_key:
            raise LLMGatewayError("ANTHROPIC_API_KEY not configured.")

        client = anthropic.Anthropic(api_key=self._api_key, timeout=float(self.timeout))

        try:
            t0 = time.time()
            message = client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            elapsed = int((time.time() - t0) * 1000)
            logger.debug(
                "Claude call: %dms, in=%d out=%d",
                elapsed,
                message.usage.input_tokens,
                message.usage.output_tokens,
            )
            # Anthropic content blocks are a union; we only expect TextBlock in
            # plain completion responses (no tool use / thinking was requested).
            text = ""
            if message.content:
                first = message.content[0]
                text = getattr(first, "text", "") or ""
            return text, message.usage.input_tokens, message.usage.output_tokens
        except Exception as exc:
            raise LLMGatewayError(f"Claude API error: {exc}") from exc
