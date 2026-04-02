"""
Tests for TenantAIConfig model and get_tenant_ai_config() service helper (S-033).
"""
from django.core.cache import cache
from django.db import connection
from django.test import override_settings
from django_tenants.test.cases import TenantTestCase

from apps.ai.services import TENANT_AI_CONFIG_CACHE_TTL, get_tenant_ai_config
from apps.core.models import TenantAIConfig


class TenantAIConfigServiceTest(TenantTestCase):
    """get_tenant_ai_config() caches and returns per-tenant config."""

    def setUp(self):
        cache.clear()

    def test_returns_config_for_existing_tenant(self):
        # Signal may have already created a row on tenant setup; use update_or_create to ensure
        # the desired values are set regardless.
        TenantAIConfig.objects.using("default").update_or_create(
            tenant=self.tenant,
            defaults={"ai_tuss_enabled": True, "rate_limit_per_hour": 200},
        )
        result = get_tenant_ai_config(self.tenant.schema_name)
        self.assertEqual(result.ai_tuss_enabled, True)
        self.assertEqual(result.rate_limit_per_hour, 200)

    def test_returns_default_config_for_missing_tenant(self):
        """No TenantAIConfig row → returns unsaved default (all disabled)."""
        # Ensure no row exists for a fake schema
        result = get_tenant_ai_config("nonexistent_schema_xyz")
        self.assertFalse(result.ai_tuss_enabled)
        self.assertFalse(result.ai_glosa_prediction_enabled)
        self.assertEqual(result.rate_limit_per_hour, 500)

    def test_caches_result(self):
        TenantAIConfig.objects.using("default").update_or_create(tenant=self.tenant, defaults={})
        # First call populates cache
        result1 = get_tenant_ai_config(self.tenant.schema_name)
        # Second call should hit cache, not DB (0 queries)
        with self.assertNumQueries(0):
            result2 = get_tenant_ai_config(self.tenant.schema_name)
        self.assertEqual(result1.pk, result2.pk)

    def test_auto_create_on_new_tenant(self):
        """Signal creates TenantAIConfig with defaults on new tenant."""
        from django_tenants.utils import get_tenant_model
        from apps.core.models import Domain
        TenantModel = get_tenant_model()
        # Tenant creation must happen in public schema
        connection.set_schema_to_public()
        try:
            new_tenant = TenantModel(schema_name="test_signal_schema", slug="test-signal-schema", name="Signal Test Clinic")
            new_tenant.save()
            try:
                Domain.objects.create(domain="signaltest.localhost", tenant=new_tenant, is_primary=True)
                cfg = TenantAIConfig.objects.using("default").get(tenant=new_tenant)
                self.assertFalse(cfg.ai_tuss_enabled)
                self.assertFalse(cfg.ai_glosa_prediction_enabled)
                self.assertEqual(cfg.rate_limit_per_hour, 500)
            finally:
                new_tenant.delete(force_drop=True)
        finally:
            connection.set_tenant(self.tenant)
