"""
Redis-backed circuit breaker for Claude API calls.
State: closed (normal) → open (tripped) → half-open (probe after cooldown)
Trip: 3 consecutive failures within 60s
Cooldown: 5 minutes before allowing one probe call
Fail-open pattern: if Redis is unavailable, circuit stays closed.
"""
import logging

from django.core.cache import cache

logger = logging.getLogger(__name__)

FAILURE_KEY_TEMPLATE = "ai:cb:failures:{tenant}"
OPEN_KEY_TEMPLATE = "ai:cb:open:{tenant}"

TRIP_THRESHOLD = 3       # failures before opening
FAILURE_WINDOW_S = 60    # seconds to count failures
COOLDOWN_S = 300         # seconds circuit stays open


def is_open(tenant_schema: str) -> bool:
    """Returns True if the circuit is open (AI calls should be skipped)."""
    key = OPEN_KEY_TEMPLATE.format(tenant=tenant_schema)
    try:
        return bool(cache.get(key))
    except Exception:
        return False


def record_failure(tenant_schema: str) -> None:
    """Record a failure. Opens the circuit after TRIP_THRESHOLD failures."""
    failure_key = FAILURE_KEY_TEMPLATE.format(tenant=tenant_schema)
    open_key = OPEN_KEY_TEMPLATE.format(tenant=tenant_schema)
    try:
        try:
            count = cache.incr(failure_key)
        except ValueError:
            # Key doesn't exist yet — create with TTL so the window resets automatically.
            # cache.expire() is not part of standard Django Redis API; set timeout here.
            cache.set(failure_key, 1, timeout=FAILURE_WINDOW_S)
            count = 1

        if count >= TRIP_THRESHOLD:
            cache.set(open_key, 1, timeout=COOLDOWN_S)
            cache.delete(failure_key)
            logger.warning(
                "AI circuit breaker OPEN for tenant=%s after %d failures. "
                "Will re-probe in %ds.",
                tenant_schema, count, COOLDOWN_S,
            )
    except Exception:
        logger.warning("Redis unavailable — circuit breaker state not updated for %s", tenant_schema)


def record_success(tenant_schema: str) -> None:
    """Reset failure counter on success."""
    failure_key = FAILURE_KEY_TEMPLATE.format(tenant=tenant_schema)
    try:
        cache.delete(failure_key)
    except Exception:
        pass
