"""
Tests for production system checks in apps/core/checks.py.

Covers check_tenant_enforcement_in_production:
  - ENVIRONMENT=production + ENFORCE_TENANT_MEMBERSHIP=False → Error core.E002
  - ENVIRONMENT=production + ENFORCE_TENANT_MEMBERSHIP=True  → no errors
  - ENVIRONMENT=development + ENFORCE_TENANT_MEMBERSHIP=False → no errors (dev safe)
  - ENVIRONMENT absent    + ENFORCE_TENANT_MEMBERSHIP=False → no errors (CI safe)
  - Error hint mentions ENFORCE_TENANT_MEMBERSHIP and backfill
"""

from __future__ import annotations

from django.test import SimpleTestCase, override_settings

from apps.core.checks import check_tenant_enforcement_in_production


class TenantEnforcementProductionCheckTests(SimpleTestCase):
    """Direct unit tests — call the check function, bypass the registry."""

    def _run(self, **settings_overrides):
        """Apply overrides and call the check function directly."""
        with override_settings(**settings_overrides):
            return check_tenant_enforcement_in_production(app_configs=None)

    # ─── Case 1: production + flag False → Error ──────────────────────────────
    def test_production_with_flag_false_returns_error(self):
        """ENVIRONMENT=production + ENFORCE_TENANT_MEMBERSHIP=False must return core.E002."""
        errors = self._run(ENVIRONMENT="production", ENFORCE_TENANT_MEMBERSHIP=False)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].id, "core.E002")

    # ─── Case 2: production + flag True → no errors ───────────────────────────
    def test_production_with_flag_true_returns_no_errors(self):
        """ENVIRONMENT=production + ENFORCE_TENANT_MEMBERSHIP=True must return empty list."""
        errors = self._run(ENVIRONMENT="production", ENFORCE_TENANT_MEMBERSHIP=True)
        self.assertEqual(errors, [])

    # ─── Case 3: development + flag False → no errors ─────────────────────────
    def test_development_with_flag_false_returns_no_errors(self):
        """ENVIRONMENT=development + flag False must not raise errors (dev/CI safe)."""
        errors = self._run(ENVIRONMENT="development", ENFORCE_TENANT_MEMBERSHIP=False)
        self.assertEqual(errors, [])

    # ─── Case 4: ENVIRONMENT absent + flag False → no errors ──────────────────
    def test_absent_environment_with_flag_false_returns_no_errors(self):
        """When ENVIRONMENT is not set, check must not raise errors."""
        # Use override_settings without ENVIRONMENT to simulate its absence.
        # We must explicitly delete it if present in base settings.
        with self.settings(ENFORCE_TENANT_MEMBERSHIP=False):
            # Temporarily remove ENVIRONMENT if it exists
            from django.conf import settings as dj_settings
            original = getattr(dj_settings, "ENVIRONMENT", None)
            had_environment = hasattr(dj_settings, "ENVIRONMENT")
            if had_environment:
                delattr(dj_settings, "ENVIRONMENT")
            try:
                errors = check_tenant_enforcement_in_production(app_configs=None)
            finally:
                if had_environment and original is not None:
                    dj_settings.ENVIRONMENT = original
        self.assertEqual(errors, [])

    # ─── Case 5: hint mentions key identifiers ─────────────────────────────────
    def test_error_hint_mentions_enforce_tenant_membership(self):
        """The Error hint must mention ENFORCE_TENANT_MEMBERSHIP."""
        errors = self._run(ENVIRONMENT="production", ENFORCE_TENANT_MEMBERSHIP=False)
        self.assertEqual(len(errors), 1)
        self.assertIn("ENFORCE_TENANT_MEMBERSHIP", errors[0].hint)

    def test_error_hint_mentions_backfill(self):
        """The Error hint must mention the backfill command."""
        errors = self._run(ENVIRONMENT="production", ENFORCE_TENANT_MEMBERSHIP=False)
        self.assertEqual(len(errors), 1)
        self.assertIn("backfill", errors[0].hint)
