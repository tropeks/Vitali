"""
Tests for DEPLOYMENT_PROFILE setting and the core.E003 production system check.

Covers:
  - assert_deployment_profile validator: valid choices pass, invalid raise
  - settings.DEPLOYMENT_PROFILE default ("pool") and IS_DEDICATED_INSTANCE helper
  - check_deployment_profile_in_production: E003 on invalid profile in production,
    no errors for valid profiles, prod-gated (development = silent)
"""

from __future__ import annotations

from django.test import SimpleTestCase, override_settings

# ─── Validator unit tests ─────────────────────────────────────────────────────


class DeploymentProfileValidatorTests(SimpleTestCase):
    """Unit tests for the assert_deployment_profile validator in _security_checks."""

    def setUp(self):
        from vitali.settings._security_checks import (
            DEPLOYMENT_PROFILE_CHOICES,
            assert_deployment_profile,
        )

        self.assert_profile = assert_deployment_profile
        self.choices = DEPLOYMENT_PROFILE_CHOICES

    # ─── Valid choices ─────────────────────────────────────────────────────────
    def test_pool_is_valid(self):
        """assert_deployment_profile('pool') must not raise."""
        self.assert_profile("pool")  # must not raise

    def test_dedicated_is_valid(self):
        """assert_deployment_profile('dedicated') must not raise."""
        self.assert_profile("dedicated")  # must not raise

    # ─── Invalid choices raise ImproperlyConfigured ────────────────────────────
    def test_airgap_raises(self):
        """assert_deployment_profile('airgap') must raise ImproperlyConfigured."""
        from django.core.exceptions import ImproperlyConfigured

        with self.assertRaises(ImproperlyConfigured):
            self.assert_profile("airgap")

    def test_empty_string_raises(self):
        """assert_deployment_profile('') must raise ImproperlyConfigured."""
        from django.core.exceptions import ImproperlyConfigured

        with self.assertRaises(ImproperlyConfigured):
            self.assert_profile("")

    # ─── Error message mentions both valid choices ─────────────────────────────
    def test_error_message_mentions_pool(self):
        """The error message must name 'pool' so operators know what to set."""
        from django.core.exceptions import ImproperlyConfigured

        with self.assertRaises(ImproperlyConfigured) as ctx:
            self.assert_profile("bogus")
        self.assertIn("pool", str(ctx.exception))

    def test_error_message_mentions_dedicated(self):
        """The error message must name 'dedicated' so operators know what to set."""
        from django.core.exceptions import ImproperlyConfigured

        with self.assertRaises(ImproperlyConfigured) as ctx:
            self.assert_profile("bogus")
        self.assertIn("dedicated", str(ctx.exception))

    # ─── DEPLOYMENT_PROFILE_CHOICES is correct ─────────────────────────────────
    def test_choices_contains_pool_and_dedicated(self):
        """DEPLOYMENT_PROFILE_CHOICES must contain exactly 'pool' and 'dedicated'."""
        self.assertIn("pool", self.choices)
        self.assertIn("dedicated", self.choices)
        self.assertNotIn("airgap", self.choices)


# ─── Settings default tests ───────────────────────────────────────────────────


class DeploymentProfileSettingTests(SimpleTestCase):
    """Assert that DEPLOYMENT_PROFILE and IS_DEDICATED_INSTANCE are wired correctly."""

    def test_default_deployment_profile_is_pool(self):
        """Under dev settings, DEPLOYMENT_PROFILE must default to 'pool'."""
        from django.conf import settings

        self.assertEqual(settings.DEPLOYMENT_PROFILE, "pool")

    def test_is_dedicated_instance_reflects_profile(self):
        """IS_DEDICATED_INSTANCE must be True iff DEPLOYMENT_PROFILE == 'dedicated'."""
        from django.conf import settings

        expected = settings.DEPLOYMENT_PROFILE == "dedicated"
        self.assertEqual(settings.IS_DEDICATED_INSTANCE, expected)

    def test_is_dedicated_instance_false_for_pool(self):
        """IS_DEDICATED_INSTANCE must be False when DEPLOYMENT_PROFILE is 'pool'."""
        with override_settings(DEPLOYMENT_PROFILE="pool", IS_DEDICATED_INSTANCE=False):
            from django.conf import settings

            self.assertFalse(settings.IS_DEDICATED_INSTANCE)

    def test_is_dedicated_instance_true_for_dedicated(self):
        """IS_DEDICATED_INSTANCE must be True when DEPLOYMENT_PROFILE is 'dedicated'."""
        with override_settings(
            DEPLOYMENT_PROFILE="dedicated", IS_DEDICATED_INSTANCE=True
        ):
            from django.conf import settings

            self.assertTrue(settings.IS_DEDICATED_INSTANCE)


# ─── Production system check tests ───────────────────────────────────────────


class DeploymentProfileProductionCheckTests(SimpleTestCase):
    """Direct unit tests — call the check function, bypass the registry.

    Mirrors test_production_checks.py (TenantEnforcementProductionCheckTests).
    """

    def _run(self, **settings_overrides):
        """Apply overrides and call the check function directly."""
        from apps.core.checks import check_deployment_profile_in_production

        with override_settings(**settings_overrides):
            return check_deployment_profile_in_production(app_configs=None)

    # ─── Case 1: production + valid "pool" → no errors ────────────────────────
    def test_production_with_pool_returns_no_errors(self):
        """ENVIRONMENT=production + DEPLOYMENT_PROFILE='pool' must return no errors."""
        errors = self._run(ENVIRONMENT="production", DEPLOYMENT_PROFILE="pool")
        self.assertEqual(errors, [])

    # ─── Case 2: production + valid "dedicated" → no errors ───────────────────
    def test_production_with_dedicated_returns_no_errors(self):
        """ENVIRONMENT=production + DEPLOYMENT_PROFILE='dedicated' must return no errors."""
        errors = self._run(ENVIRONMENT="production", DEPLOYMENT_PROFILE="dedicated")
        self.assertEqual(errors, [])

    # ─── Case 3: production + invalid → exactly one Error with core.E003 ──────
    def test_production_with_bogus_profile_returns_e003(self):
        """ENVIRONMENT=production + DEPLOYMENT_PROFILE='bogus' must return core.E003."""
        errors = self._run(ENVIRONMENT="production", DEPLOYMENT_PROFILE="bogus")
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].id, "core.E003")

    # ─── Case 4: development + invalid → no errors (prod-gated) ──────────────
    def test_development_with_bogus_profile_returns_no_errors(self):
        """ENVIRONMENT=development + invalid profile must return no errors (dev/CI safe)."""
        errors = self._run(ENVIRONMENT="development", DEPLOYMENT_PROFILE="bogus")
        self.assertEqual(errors, [])
