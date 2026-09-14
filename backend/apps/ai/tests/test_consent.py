"""
Tests for apps.ai.consent.requires_ai_consent (Onda 3 / 3.2).
"""

from unittest.mock import patch

from django.conf import settings
from django.core.cache import cache
from django.test import override_settings

from apps.ai.consent import requires_ai_consent
from apps.core.models import AIDPAStatus, TenantAIConfig
from apps.test_utils import TenantTestCase


class RequiresAIConsentTest(TenantTestCase):
    def setUp(self):
        # get_tenant_ai_config() caches TenantAIConfig for 5 minutes keyed by
        # schema_name — the fast_test schema is reused across test methods
        # (see apps/test_utils.py), so a stale config from an earlier test
        # would otherwise leak in here.
        cache.clear()
        self.schema = self.tenant.schema_name

    def _sign_dpa(self):
        import datetime

        AIDPAStatus.objects.using("default").update_or_create(
            tenant=self.tenant, defaults={"dpa_signed_date": datetime.date.today()}
        )

    @override_settings(FEATURE_AI_GLOSA=False)
    def test_global_flag_off_blocks(self):
        result = requires_ai_consent("glosa", self.schema)
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "feature_disabled_global")

    @override_settings(FEATURE_AI_GLOSA=True)
    def test_dpa_missing_row_blocks_fail_closed(self):
        """No AIDPAStatus row at all for this tenant — must block, not allow."""
        AIDPAStatus.objects.using("default").filter(tenant=self.tenant).delete()
        result = requires_ai_consent("glosa", self.schema)
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "dpa_not_signed")

    @override_settings(FEATURE_AI_GLOSA=True)
    def test_dpa_unsigned_row_blocks(self):
        AIDPAStatus.objects.using("default").update_or_create(
            tenant=self.tenant, defaults={"dpa_signed_date": None}
        )
        result = requires_ai_consent("glosa", self.schema)
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "dpa_not_signed")

    @override_settings(FEATURE_AI_GLOSA=True)
    def test_dpa_lookup_error_fails_closed(self):
        """
        If the DPA status can't even be determined (DB error, tenant lookup
        failing) the call must be BLOCKED, never allowed — this is the
        deliberate asymmetry vs. the Redis-backed guardrails (see
        apps/ai/consent.py module docstring).
        """
        self._sign_dpa()
        with patch("apps.core.models.Tenant.objects.get", side_effect=Exception("DB unavailable")):
            result = requires_ai_consent("glosa", self.schema)
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "dpa_not_signed")

    @override_settings(FEATURE_AI_GLOSA=True)
    def test_dpa_signed_but_tenant_flag_off_blocks(self):
        self._sign_dpa()
        TenantAIConfig.objects.using("default").update_or_create(
            tenant=self.tenant, defaults={"ai_glosa_prediction_enabled": False}
        )
        result = requires_ai_consent("glosa", self.schema)
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "feature_disabled_tenant")

    @override_settings(FEATURE_AI_GLOSA=True)
    def test_all_gates_pass_allows(self):
        self._sign_dpa()
        TenantAIConfig.objects.using("default").update_or_create(
            tenant=self.tenant, defaults={"ai_glosa_prediction_enabled": True}
        )
        result = requires_ai_consent("glosa", self.schema)
        self.assertTrue(result.allowed)

    @override_settings(FEATURE_AI_SCRIBE=True)
    def test_feature_without_tenant_flag_skips_that_gate(self):
        """scribe/whisper have no per-tenant TenantAIConfig field — only
        global flag + DPA + ceiling apply."""
        self._sign_dpa()
        result = requires_ai_consent("scribe", self.schema)
        self.assertTrue(result.allowed)

    def test_unknown_feature_raises(self):
        with self.assertRaises(ValueError):
            requires_ai_consent("not_a_real_feature", self.schema)

    def test_glosa_flag_absent_defaults_to_blocked(self):
        """FEATURE_AI_GLOSA entirely unset on settings (not just False) must
        still block — requires_ai_consent uses getattr(..., default=False)."""
        had_attr = hasattr(settings, "FEATURE_AI_GLOSA")
        original = getattr(settings, "FEATURE_AI_GLOSA", None)
        try:
            if had_attr:
                delattr(settings, "FEATURE_AI_GLOSA")
            result = requires_ai_consent("glosa", self.schema)
        finally:
            if had_attr:
                settings.FEATURE_AI_GLOSA = original
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "feature_disabled_global")
