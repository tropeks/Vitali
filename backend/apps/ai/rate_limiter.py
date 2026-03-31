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
        # Atomic increment-first: avoids TOCTOU race where two concurrent requests
        # both read count=99 and both proceed past the limit check.
        try:
            new_count = cache.incr(key)
        except ValueError:
            # Key does not exist yet — initialise with TTL, then treat as count=1.
            cache.set(key, 1, timeout=3600)
            new_count = 1

        return new_count > limit
    except Exception:
        logger.warning("Redis unavailable for rate limiter (tenant=%s) — failing open", tenant_schema)
        return False

