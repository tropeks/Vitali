"""
Per-tenant Redis rate limiter for AI calls.
Key: ai:rate:{tenant_schema}
Window: 1 hour (sliding, using Redis INCR + EXPIRE)
Fail-open: if Redis is unavailable, allow the request (Decision 6 / P5 Explicit).
"""
import logging

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)


def is_rate_limited(tenant_schema: str) -> bool:
    """
    Returns True if the tenant has exceeded AI_RATE_LIMIT_PER_HOUR.
    Fail-open on Redis errors.
    """
    limit = getattr(settings, 'AI_RATE_LIMIT_PER_HOUR', 100)
    key = f"ai:rate:{tenant_schema}"

    try:
        count = cache.get(key, 0)
        if count >= limit:
            return True

        # Increment with 1-hour TTL (only set TTL on first increment)
        new_count = cache.get_or_set(key, 0, timeout=3600)
        cache.incr(key)
        return False
    except Exception:
        logger.warning("Redis unavailable for rate limiter (tenant=%s) — failing open", tenant_schema)
        return False


def increment_usage(tenant_schema: str) -> None:
    """Increment usage counter. Called after a successful LLM call."""
    key = f"ai:rate:{tenant_schema}"
    try:
        try:
            cache.incr(key)
        except ValueError:
            cache.set(key, 1, timeout=3600)
    except Exception:
        logger.warning("Redis unavailable — could not increment AI usage counter for %s", tenant_schema)
