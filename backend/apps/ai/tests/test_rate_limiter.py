"""Tests for per-tenant Redis rate limiter."""

from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings


@override_settings(AI_RATE_LIMIT_PER_HOUR=5)
class RateLimiterTest(TestCase):
    def setUp(self):
        cache.clear()

    def test_allows_under_limit(self):
        from apps.ai.rate_limiter import is_rate_limited

        for _ in range(4):
            self.assertFalse(is_rate_limited("test_tenant"))

    def test_blocks_at_limit(self):
        from apps.ai.rate_limiter import is_rate_limited

        # Fill up to limit
        cache.set("ai:rate:test_tenant", 5, timeout=3600)
        self.assertTrue(is_rate_limited("test_tenant"))

    def test_fails_open_on_redis_error(self):
        from apps.ai.rate_limiter import is_rate_limited

        with patch("apps.ai.rate_limiter.cache") as mock_cache:
            mock_cache.get.side_effect = Exception("Redis down")
            result = is_rate_limited("test_tenant")
        self.assertFalse(result)

    def test_rate_limit_is_per_tenant(self):
        from apps.ai.rate_limiter import is_rate_limited

        # Fill tenant A to limit
        cache.set("ai:rate:tenant_a", 5, timeout=3600)
        # Tenant B should not be affected
        self.assertTrue(is_rate_limited("tenant_a"))
        self.assertFalse(is_rate_limited("tenant_b"))
