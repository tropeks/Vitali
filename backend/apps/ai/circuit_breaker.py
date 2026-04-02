"""
Redis-backed circuit breaker for Claude API calls.
State: closed (normal) → open (tripped) → half-open (probe after cooldown)
Trip: 3 consecutive failures within 60s
Cooldown: 5 minutes before allowing one probe call
Fail-open pattern: if Redis is unavailable, circuit stays closed.

feature_key isolates TUSS and Glosa circuits so failures in one don't trip the other.
"""
import logging

from django.core.cache import cache

logger = logging.getLogger(__name__)

FAILURE_KEY_TEMPLATE = "ai:cb:failures:{tenant}:{feature}"
OPEN_KEY_TEMPLATE = "ai:cb:open:{tenant}:{feature}"

TRIP_THRESHOLD = 3       # failures before opening
FAILURE_WINDOW_S = 60    # seconds to count failures
COOLDOWN_S = 300         # seconds circuit stays open


def is_open(tenant_schema: str, feature: str = "tuss") -> bool:
    """Returns True if the circuit is open (AI calls should be skipped)."""
    key = OPEN_KEY_TEMPLATE.format(tenant=tenant_schema, feature=feature)
    try:
        return bool(cache.get(key))
    except Exception:
        return False


def record_failure(tenant_schema: str, feature: str = "tuss") -> None:
    """Record a failure. Opens the circuit after TRIP_THRESHOLD failures."""
    failure_key = FAILURE_KEY_TEMPLATE.format(tenant=tenant_schema, feature=feature)
    open_key = OPEN_KEY_TEMPLATE.format(tenant=tenant_schema, feature=feature)
    try:
        try:
            count = cache.incr(failure_key)
        except ValueError:
            # Key doesn't exist yet — create with TTL so the window resets automatically.
            cache.set(failure_key, 1, timeout=FAILURE_WINDOW_S)
            count = 1

        if count >= TRIP_THRESHOLD:
            cache.set(open_key, 1, timeout=COOLDOWN_S)
            cache.delete(failure_key)
            logger.warning(
                "AI circuit breaker OPEN for tenant=%s feature=%s after %d failures. "
                "Will re-probe in %ds.",
                tenant_schema, feature, count, COOLDOWN_S,
            )
    except Exception:
        logger.warning(
            "Redis unavailable — circuit breaker state not updated for %s/%s",
            tenant_schema, feature,
        )


def record_success(tenant_schema: str, feature: str = "tuss") -> None:
    """Reset failure counter on success."""
    failure_key = FAILURE_KEY_TEMPLATE.format(tenant=tenant_schema, feature=feature)
    try:
        cache.delete(failure_key)
    except Exception:
        pass
