"""
Sprint 19 / S-081 — F-05 DPA-signed cascade integration tests.

Covers:
  - First-time DPA sign enables all 4 AI FeatureFlag rows
  - AuditLog correlation chain: dpa_signed + ai_feature_flag_enabled + dpa_admin_email_queued
    all share the same correlation_id (decision 2A)
  - Idempotency: second call returns already_signed=True, no double-flipped flags,
    no second email queued
  - Partial flag state: flags already enabled are NOT re-listed in flags_enabled
  - View-level: POST /api/v1/settings/dpa/sign/ enables flags in DB
  - CRITICAL fail-open: EmailService raises → DPA still signed + flags still enabled
    + dpa_admin_email_failed AuditLog written

Architecture invariant (decision 1B):
  transaction.atomic() commits BEFORE transaction.on_commit() fires the Celery task.
  Any exception inside the task cannot roll back committed DB rows.

Test patterns mirror Sprint 18 / T13 in apps/hr/tests/test_integration_whatsapp_failopen.py:
  - captureOnCommitCallbacks(execute=True) fires on_commit hooks synchronously
    inside TenantTestCase's wrapping transaction (Django 4.1+).
  - send_dpa_signed_admin_email.retry is patched to raise MaxRetriesExceededError
    immediately (simulates exhausted retries without 4x task re-runs).
  - @override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=False)
    ensures Celery tasks run inline without propagating exceptions to the caller.
"""

from unittest.mock import patch

from celery.exceptions import MaxRetriesExceededError
from django.test import override_settings
from rest_framework.test import APIClient

from apps.core.models import AIDPAStatus, AuditLog, FeatureFlag, Role, User
from apps.core.services.dpa import DPASigningService
from apps.core.tasks import send_dpa_signed_admin_email
from apps.test_utils import TenantTestCase

# ── Patch targets ─────────────────────────────────────────────────────────────
_EMAIL_PATCH = "apps.core.services.email.EmailService.send_dpa_signed_notification"


# ── Helpers ───────────────────────────────────────────────────────────────────

AI_MODULE_KEYS = ("ai_scribe", "ai_tuss", "ai_prescription_safety", "ai_cid10")


def _make_admin(email="admin_cascade@test.com"):
    """Create (or get) an admin user with ai.manage permission."""
    role, _ = Role.objects.get_or_create(
        name="admin_cascade",
        defaults={"permissions": ["ai.manage"], "is_system": True},
    )
    user, created = User.objects.get_or_create(
        email=email,
        defaults={"full_name": "Admin Cascade", "role": role},
    )
    if not created and user.role != role:
        user.role = role
        user.save(update_fields=["role"])
    return user


# ── Service-level tests ───────────────────────────────────────────────────────


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=False)
class DPACascadeServiceTests(TenantTestCase):
    """
    Tests for DPASigningService.sign() — exercises the service directly,
    not via the HTTP endpoint.
    """

    def setUp(self):
        super().setUp()
        self.tenant = self.__class__.tenant
        self.admin = _make_admin()
        # Clean slate for each test
        AIDPAStatus.objects.filter(tenant=self.tenant).delete()
        FeatureFlag.objects.filter(tenant=self.tenant, module_key__in=AI_MODULE_KEYS).delete()

    # ── Test 1 ────────────────────────────────────────────────────────────────

    def test_sign_dpa_first_time_enables_all_ai_flags(self):
        """First-time DPA sign must enable all 4 AI FeatureFlag rows."""
        service = DPASigningService(requesting_user=self.admin)

        with self.captureOnCommitCallbacks(execute=True):
            with patch(_EMAIL_PATCH):
                result = service.sign(tenant=self.tenant, ip_address="127.0.0.1")

        self.assertFalse(result["already_signed"])
        self.assertEqual(set(result["flags_enabled"]), set(AI_MODULE_KEYS))

        for key in AI_MODULE_KEYS:
            flag = FeatureFlag.objects.get(tenant=self.tenant, module_key=key)
            self.assertTrue(
                flag.is_enabled,
                f"FeatureFlag '{key}' must be enabled after DPA sign",
            )

        dpa = AIDPAStatus.objects.get(tenant=self.tenant)
        self.assertTrue(dpa.is_signed)
        self.assertIsNotNone(dpa.dpa_signed_date)
        self.assertEqual(dpa.signed_by_user, self.admin)

    # ── Test 2 ────────────────────────────────────────────────────────────────

    def test_sign_dpa_writes_correlation_chain(self):
        """
        All AuditLog entries from a single sign() call must share the same
        correlation_id (decision 2A): dpa_signed + ai_feature_flag_enabled (×4)
        + dpa_admin_email_queued.
        """
        service = DPASigningService(requesting_user=self.admin)

        with self.captureOnCommitCallbacks(execute=True):
            with patch(_EMAIL_PATCH):
                service.sign(tenant=self.tenant)

        cid = service.correlation_id

        # dpa_signed carries correlation_id
        dpa_audit = AuditLog.objects.filter(action="dpa_signed").first()
        self.assertIsNotNone(dpa_audit, "AuditLog 'dpa_signed' must exist")
        self.assertEqual(dpa_audit.new_data.get("correlation_id"), cid)

        # ai_feature_flag_enabled entries (one per key) carry correlation_id
        flag_audits = AuditLog.objects.filter(action="ai_feature_flag_enabled")
        self.assertEqual(
            flag_audits.count(),
            len(AI_MODULE_KEYS),
            "Expected one ai_feature_flag_enabled AuditLog per AI module key",
        )
        for audit in flag_audits:
            self.assertEqual(
                audit.new_data.get("correlation_id"),
                cid,
                f"ai_feature_flag_enabled for {audit.new_data.get('module_key')} "
                f"must carry the service's correlation_id",
            )

        # dpa_admin_email_queued carries correlation_id
        queued_audit = AuditLog.objects.filter(action="dpa_admin_email_queued").first()
        self.assertIsNotNone(queued_audit, "AuditLog 'dpa_admin_email_queued' must exist")
        self.assertEqual(queued_audit.new_data.get("correlation_id"), cid)

    # ── Test 3 ────────────────────────────────────────────────────────────────

    def test_sign_dpa_idempotent(self):
        """
        Second call to sign() returns already_signed=True, does NOT re-flip
        flags, does NOT write a second set of AuditLogs or queue a second email.
        """
        service1 = DPASigningService(requesting_user=self.admin)
        service2 = DPASigningService(requesting_user=self.admin)

        with patch(_EMAIL_PATCH) as mock_email:
            with self.captureOnCommitCallbacks(execute=True):
                service1.sign(tenant=self.tenant)

        # First call: email called once
        self.assertEqual(mock_email.call_count, 1)

        email_queued_count_after_first = AuditLog.objects.filter(
            action="dpa_admin_email_queued"
        ).count()
        dpa_signed_count_after_first = AuditLog.objects.filter(action="dpa_signed").count()

        # Second call: no on_commit hooks fire (already_signed short-circuit)
        with self.captureOnCommitCallbacks(execute=True):
            with patch(_EMAIL_PATCH) as mock_email2:
                result2 = service2.sign(tenant=self.tenant)

        self.assertTrue(result2["already_signed"])
        self.assertEqual(result2["flags_enabled"], [])

        # Email not called again
        self.assertEqual(mock_email2.call_count, 0)

        # AuditLog counts unchanged (no second write)
        self.assertEqual(
            AuditLog.objects.filter(action="dpa_admin_email_queued").count(),
            email_queued_count_after_first,
        )
        self.assertEqual(
            AuditLog.objects.filter(action="dpa_signed").count(),
            dpa_signed_count_after_first,
        )

    # ── Test 4 ────────────────────────────────────────────────────────────────

    def test_sign_dpa_only_flips_disabled_flags(self):
        """
        flags_enabled return only includes newly-flipped flags.
        Pre-existing enabled flags are preserved but NOT listed.
        """
        # Pre-enable two flags
        FeatureFlag.objects.get_or_create(
            tenant=self.tenant,
            module_key="ai_scribe",
            defaults={"is_enabled": True},
        )
        FeatureFlag.objects.update_or_create(
            tenant=self.tenant,
            module_key="ai_scribe",
            defaults={"is_enabled": True},
        )
        FeatureFlag.objects.get_or_create(
            tenant=self.tenant,
            module_key="ai_tuss",
            defaults={"is_enabled": True},
        )
        FeatureFlag.objects.update_or_create(
            tenant=self.tenant,
            module_key="ai_tuss",
            defaults={"is_enabled": True},
        )

        service = DPASigningService(requesting_user=self.admin)

        with self.captureOnCommitCallbacks(execute=True):
            with patch(_EMAIL_PATCH):
                result = service.sign(tenant=self.tenant)

        # Only the two disabled ones should be in flags_enabled
        self.assertNotIn("ai_scribe", result["flags_enabled"])
        self.assertNotIn("ai_tuss", result["flags_enabled"])
        self.assertIn("ai_prescription_safety", result["flags_enabled"])
        self.assertIn("ai_cid10", result["flags_enabled"])
        self.assertEqual(len(result["flags_enabled"]), 2)

        # All 4 flags are now enabled in DB
        for key in AI_MODULE_KEYS:
            flag = FeatureFlag.objects.get(tenant=self.tenant, module_key=key)
            self.assertTrue(flag.is_enabled, f"Flag '{key}' must be enabled")


# ── View-level test ───────────────────────────────────────────────────────────


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=False)
class DPASignEndpointTests(TenantTestCase):
    """View-level test: POST /api/v1/settings/dpa/sign/ enables flags in DB."""

    def setUp(self):
        super().setUp()
        self.tenant = self.__class__.tenant
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        self.admin = _make_admin("admin_view@test.com")
        AIDPAStatus.objects.filter(tenant=self.tenant).delete()
        FeatureFlag.objects.filter(tenant=self.tenant, module_key__in=AI_MODULE_KEYS).delete()

    def test_dpa_sign_endpoint_uses_service(self):
        """
        POST /api/v1/settings/dpa/sign/ must:
          1. Return 200 with is_signed=True
          2. Enable all 4 AI FeatureFlag rows in the DB
          3. Write dpa_signed AuditLog with correlation_id
        """
        self.client.force_authenticate(user=self.admin)

        with self.captureOnCommitCallbacks(execute=True):
            with patch(_EMAIL_PATCH):
                resp = self.client.post("/api/v1/settings/dpa/sign/")

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["is_signed"])
        self.assertIsNotNone(data["signed_at"])
        self.assertEqual(data["signed_by_name"], self.admin.full_name)

        # All 4 AI flags enabled in DB
        for key in AI_MODULE_KEYS:
            flag = FeatureFlag.objects.filter(tenant=self.tenant, module_key=key).first()
            self.assertIsNotNone(flag, f"FeatureFlag '{key}' must exist after DPA sign")
            self.assertTrue(flag.is_enabled, f"FeatureFlag '{key}' must be enabled")

        # AuditLog written with correlation_id
        dpa_audit = AuditLog.objects.filter(
            action="dpa_signed", resource_type="ai_dpa_status"
        ).first()
        self.assertIsNotNone(dpa_audit, "AuditLog 'dpa_signed' must be written via endpoint")
        self.assertIn("correlation_id", dpa_audit.new_data)
        self.assertIn("signed_by_id", dpa_audit.new_data)
        self.assertIn("ip_address", dpa_audit.new_data)


# ── Fail-open integration test ────────────────────────────────────────────────


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=False)
class DPAEmailFailOpenIntegrationTests(TenantTestCase):
    """
    CRITICAL fail-open test for the DPA cascade (locked decision 1B).

    When EmailService.send_dpa_signed_notification raises and all retries are
    exhausted (MaxRetriesExceededError), the cascade must:
      1. Commit AIDPAStatus.dpa_signed_date (DPA still signed)
      2. Commit all 4 AI FeatureFlag rows as is_enabled=True (flags still live)
      3. Write AuditLog 'dpa_admin_email_failed' (failure recorded)
      4. NOT raise or propagate the exception to the caller

    Architecture invariant being proven:
      transaction.atomic() commits BEFORE transaction.on_commit() fires the
      Celery task. Any exception inside the task cannot roll back committed rows.
    """

    def setUp(self):
        super().setUp()
        self.tenant = self.__class__.tenant
        self.admin = _make_admin("admin_failopen@test.com")
        AIDPAStatus.objects.filter(tenant=self.tenant).delete()
        FeatureFlag.objects.filter(tenant=self.tenant, module_key__in=AI_MODULE_KEYS).delete()

    def test_email_failure_does_not_roll_back_dpa(self):
        """
        CORNERSTONE TEST — locked decision 1B.

        EmailService.send_dpa_signed_notification raises → all retries exhausted
        → dpa_admin_email_failed AuditLog written.
        DPA row and FeatureFlag rows MUST remain committed.
        """
        service = DPASigningService(requesting_user=self.admin)

        with (
            patch(_EMAIL_PATCH, side_effect=ConnectionError("SMTP server down")),
            patch.object(
                send_dpa_signed_admin_email,
                "retry",
                side_effect=MaxRetriesExceededError(),
            ) as mock_retry,
        ):
            # captureOnCommitCallbacks(execute=True) fires on_commit hooks when
            # the inner context exits — still inside the patch context, so
            # all mocks are active when the Celery task runs.
            with self.captureOnCommitCallbacks(execute=True):
                result = service.sign(tenant=self.tenant, ip_address="10.0.0.1")

        # ── 1. DPA is still signed ────────────────────────────────────────────
        self.assertFalse(
            result["already_signed"],
            "sign() must not return already_signed=True on first call",
        )
        dpa = AIDPAStatus.objects.get(tenant=self.tenant)
        self.assertTrue(
            dpa.is_signed,
            "AIDPAStatus must be signed even after email task failure",
        )
        self.assertIsNotNone(
            dpa.dpa_signed_date,
            "dpa_signed_date must be set even after email task failure",
        )

        # ── 2. All AI FeatureFlag rows still enabled ──────────────────────────
        for key in AI_MODULE_KEYS:
            flag = FeatureFlag.objects.filter(tenant=self.tenant, module_key=key).first()
            self.assertIsNotNone(flag, f"FeatureFlag '{key}' must exist")
            self.assertTrue(
                flag.is_enabled,
                f"FeatureFlag '{key}' must remain enabled after email task failure",
            )

        # ── 3. dpa_admin_email_failed AuditLog written ────────────────────────
        failed_audit = AuditLog.objects.filter(action="dpa_admin_email_failed").first()
        self.assertIsNotNone(
            failed_audit,
            "AuditLog 'dpa_admin_email_failed' must be written when email raises persistently",
        )
        self.assertEqual(
            failed_audit.new_data.get("reason"),
            "max_retries_exceeded",
            "dpa_admin_email_failed AuditLog must record reason=max_retries_exceeded",
        )
        self.assertIn("error", failed_audit.new_data)
        self.assertIn("flags_enabled", failed_audit.new_data)

        # ── 4. Failure AuditLog carries correlation_id (cascade chain intact) ──
        dpa_audit = AuditLog.objects.filter(action="dpa_signed").first()
        self.assertIsNotNone(dpa_audit)
        self.assertEqual(
            failed_audit.new_data.get("correlation_id"),
            dpa_audit.new_data.get("correlation_id"),
            "dpa_admin_email_failed correlation_id must match dpa_signed — "
            "proves the cascade audit chain is intact across the service → task boundary",
        )

        # ── 5. Retry was called (confirming the failure path triggered retry) ──
        self.assertTrue(
            mock_retry.called,
            "self.retry must have been called when EmailService raised",
        )
