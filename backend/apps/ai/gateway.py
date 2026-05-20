"""
LLM Gateway — abstract interface + Claude implementation.
Decision B1: abstract class retained for future AI features (clinical notes, prescription safety).
"""

import logging
import threading
import time
from abc import ABC, abstractmethod
from typing import Any

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


# Module-level cache for the underlying `anthropic.Anthropic` client. The
# `ClaudeGateway` itself is instantiated per request (one per scribe / TUSS /
# glosa call), but the anthropic SDK opens a fresh HTTP connection pool every
# time `Anthropic(...)` is constructed — at >10 concurrent scribe sessions
# that is measurable overhead. Cache by (api_key, timeout) so concurrent
# tenants and overrides still get their own client; clear the cache when
# settings change in tests.
_client_cache: dict[tuple[str, float], Any] = {}
_client_cache_lock = threading.Lock()


def _get_anthropic_client(api_key: str, timeout: float) -> Any:
    """Return a cached `anthropic.Anthropic` client for the given credentials."""
    try:
        import anthropic
    except ImportError as err:
        raise LLMGatewayError(
            "anthropic SDK not installed. Add anthropic>=0.40 to requirements."
        ) from err

    key = (api_key, timeout)
    cached = _client_cache.get(key)
    if cached is not None:
        return cached
    with _client_cache_lock:
        cached = _client_cache.get(key)
        if cached is not None:
            return cached
        client = anthropic.Anthropic(api_key=api_key, timeout=timeout)
        _client_cache[key] = client
        return client


def reset_anthropic_client_cache() -> None:
    """Clear the module-level anthropic client cache (intended for tests)."""
    with _client_cache_lock:
        _client_cache.clear()


class ClaudeGateway(LLMGateway):
    """
    Anthropic Claude implementation.
    Uses claude-haiku-4-5-20251001 for cost efficiency on TUSS coding.

    The underlying `anthropic.Anthropic` client is cached at module level
    keyed by `(api_key, timeout)` so repeated gateway instantiations on the
    hot path do not rebuild the HTTP connection pool.
    """

    def __init__(
        self, api_key: str | None = None, model: str = MODEL_HAIKU, timeout: int | None = None
    ):
        self.model = model
        self.timeout: int = timeout or int(getattr(settings, "AI_SUGGEST_TIMEOUT_S", 5))
        self._api_key = api_key or getattr(settings, "ANTHROPIC_API_KEY", "")

    def complete(self, system: str, user: str, max_tokens: int = 512) -> tuple[str, int, int]:
        if not self._api_key:
            raise LLMGatewayError("ANTHROPIC_API_KEY not configured.")

        client = _get_anthropic_client(self._api_key, float(self.timeout))

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
