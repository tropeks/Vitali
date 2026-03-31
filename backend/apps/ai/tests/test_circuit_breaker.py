"""Tests for Redis circuit breaker."""
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase

from apps.ai.circuit_breaker import (
    COOLDOWN_S,
    FAILURE_KEY_TEMPLATE,
    OPEN_KEY_TEMPLATE,
    TRIP_THRESHOLD,
    is_open,
    record_failure,
    record_success,
)


class CircuitBreakerTest(TestCase):

    def setUp(self):
        cache.clear()

    def test_closed_by_default(self):
        """Circuit starts closed (no failures recorded)."""
        self.assertFalse(is_open("tenant_a"))

    def test_opens_after_trip_threshold_failures(self):
        """Circuit opens after TRIP_THRESHOLD consecutive failures."""
        for _ in range(TRIP_THRESHOLD):
            record_failure("tenant_a")
        self.assertTrue(is_open("tenant_a"))

    def test_does_not_open_before_threshold(self):
        """Circuit stays closed until threshold is reached."""
        for _ in range(TRIP_THRESHOLD - 1):
            record_failure("tenant_a")
        self.assertFalse(is_open("tenant_a"))

    def test_success_resets_failure_count(self):
        """record_success clears the failure counter, preventing a trip."""
        for _ in range(TRIP_THRESHOLD - 1):
            record_failure("tenant_a")
        record_success("tenant_a")
        # Now add TRIP_THRESHOLD - 1 more failures — should not open
        for _ in range(TRIP_THRESHOLD - 1):
            record_failure("tenant_a")
        self.assertFalse(is_open("tenant_a"))

    def test_tenant_isolation(self):
        """Failures on tenant_a must not open circuit for tenant_b."""
        for _ in range(TRIP_THRESHOLD):
            record_failure("tenant_a")
        self.assertTrue(is_open("tenant_a"))
        self.assertFalse(is_open("tenant_b"))

    def test_fail_open_on_redis_error(self):
        """If Redis is unavailable, is_open returns False (fail-open)."""
        with patch("apps.ai.circuit_breaker.cache.get", side_effect=Exception("Redis down")):
            self.assertFalse(is_open("tenant_a"))

    def test_record_failure_survives_redis_error(self):
        """record_failure does not raise when Redis is unavailable."""
        with patch("apps.ai.circuit_breaker.cache.incr", side_effect=Exception("Redis down")):
            try:
                record_failure("tenant_a")
            except Exception:
                self.fail("record_failure raised on Redis error")
