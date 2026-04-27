"""Sprint 18 / E-013 — CRITICAL WhatsApp fail-open integration test.

Cornerstone test for the cascade architecture (locked decision 1B):
  - Employee + User + Professional rows persist even when EvolutionAPIGateway
    raises ConnectionError during the post-commit WhatsApp task.
  - AuditLog `whatsapp_setup_failed` is written on persistent failure.
  - AuditLog `whatsapp_channel_created` is written on eventual success.

Architecture invariant being proven:
  transaction.atomic() commits BEFORE transaction.on_commit() fires the
  Celery task. Any exception inside the task cannot roll back committed rows.

Architectural notes:

  1. **correlation_id chain (decision 2A)**: As of the post-Sprint-18 follow-up,
     the service-layer correlation_id IS propagated through to the task. Both
     `whatsapp_channel_created` and `whatsapp_setup_failed` AuditLog entries
     carry the same correlation_id as the service's `employee_created` /
     `user_created` audits — full cross-boundary cascade tracing.

  2. **Phone is transient in Sprint 18**: `phone` is set as a Python attribute
     on the User instance by `EmployeeOnboardingService._create_user()` but is
     NOT persisted to the DB. After the atomic block commits, the User ORM
     instance is discarded; when the task fetches the user from the DB, `phone`
     is gone. The task's phone guard fires and the task skips silently. Sprint 18
     knows this — the task is intentionally a no-op when phone is absent. A future
     migration adding `User.phone` as a real column will make the full path live.

  3. **Eager retry behavior**: With CELERY_TASK_ALWAYS_EAGER=True, `self.retry()`
     re-runs the task inline recursively rather than raising MaxRetriesExceededError
     directly at the caller's level. The `except MaxRetriesExceededError:` block
     inside the task body executes correctly on the FINAL recursive invocation,
     but only when the task's max_retries counter is exhausted by real re-runs.
     To test the failure AuditLog path deterministically (without 4x task runs
     and real retry delays), we patch `self.retry` to raise MaxRetriesExceededError
     immediately — the same pattern used by test_tasks.py unit tests.

Test design:
  - `captureOnCommitCallbacks(execute=True)` fires on_commit hooks synchronously
    inside TenantTestCase's wrapping transaction (Django 4.1+).
  - `apps.hr.tasks.User` is patched to inject .phone so the task does not skip.
  - `apps.hr.tasks.get_gateway` is patched to raise ConnectionError.
  - `setup_staff_whatsapp_channel.retry` is patched to raise MaxRetriesExceededError,
    simulating retries-exhausted state in one call (no recursive eager re-runs).
  - For the success variant, gateway raises then succeeds; retry patch is NOT needed
    because the task succeeds on the 2nd gateway call (within the first task run).
"""

from unittest.mock import MagicMock, patch

from celery.exceptions import MaxRetriesExceededError
from django.test import override_settings

from apps.core.models import AuditLog, FeatureFlag, Role, User
from apps.emr.models import Professional
from apps.hr.models import Employee
from apps.hr.tasks import setup_staff_whatsapp_channel
from apps.test_utils import TenantTestCase

# ── Patch targets (confirmed from apps/hr/tests/test_tasks.py) ───────────────
_GW_PATCH = "apps.hr.tasks.get_gateway"
_USER_PATCH = "apps.hr.tasks.User"

# ── Helpers ───────────────────────────────────────────────────────────────────

PHONE = "+5511999999999"


def _mock_user_with_phone(real_user: User) -> MagicMock:
    """
    Build a MagicMock that quacks like User with .phone injected.

    The task fetches User from DB after commit, at which point the transient
    .phone attribute (set by EmployeeOnboardingService._create_user) is gone.
    This mock bridges that gap so the task proceeds past the phone guard and
    reaches the gateway call — proving the gateway is what fails, not the guard.
    """
    m = MagicMock(spec=User)
    m.id = real_user.id
    m.full_name = real_user.full_name
    m.phone = PHONE
    return m


def _clinical_onboard_payload(email: str) -> dict:
    """Build a valid clinical (medico) payload with setup_whatsapp=True."""
    return {
        "full_name": "Dr. Test Whatsapp",
        "email": email,
        "cpf": "111.111.111-11",
        "phone": PHONE,
        "role": "medico",
        "hire_date": "2026-04-26",
        "contract_type": "clt",
        "employment_status": "active",
        "council_type": "CRM",
        "council_number": "12345",
        "council_state": "SP",
        "specialty": "Clínica Médica",
        "auth_mode": "random_password",
        "password": "GeneratedTest123!",
        "setup_whatsapp": True,
    }


# ── Test class ────────────────────────────────────────────────────────────────


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=False)
class WhatsAppFailOpenIntegrationTests(TenantTestCase):
    """
    Integration tests for the fail-open WhatsApp cascade (decision 1B).

    These tests exercise the full stack:
      EmployeeOnboardingService → transaction.on_commit → Celery task (eager)
      → EvolutionAPIGateway (mocked) → AuditLog

    The DB rows (Employee, User, Professional) must ALWAYS persist regardless
    of what the WhatsApp task does.

    Gateway and User.objects.get are mocked so the task reaches the gateway
    call — the key architectural boundary being tested.
    """

    def setUp(self):
        super().setUp()
        # Enable WhatsApp module for tenant
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key="whatsapp",
            defaults={"is_enabled": True},
        )
        # Admin user (acts as requesting_user)
        self.admin, _ = User.objects.get_or_create(
            email="admin@test.com",
            defaults={"full_name": "Admin User", "is_staff": True},
        )
        if not self.admin.is_staff:
            self.admin.is_staff = True
            self.admin.save(update_fields=["is_staff"])
        # Ensure 'medico' role exists
        Role.objects.get_or_create(
            name="medico",
            defaults={"permissions": ["emr.read", "emr.write"]},
        )

    # ── Test 1: persistent gateway failure → rows persist + failure AuditLog ──

    def test_whatsapp_failure_does_not_roll_back_employee(self):
        """
        CORNERSTONE TEST — locked decision 1B.

        When EvolutionAPIGateway.send_text raises ConnectionError and all retries
        are exhausted (MaxRetriesExceededError), the cascade must:
          1. Commit Employee + User + Professional to the DB (atomic block done).
          2. Fire the on_commit task (eagerly, synchronously).
          3. Write AuditLog `whatsapp_setup_failed`.
          4. NOT raise or propagate the exception to the caller.

        Gateway mock: raises ConnectionError.
        Retry mock: raises MaxRetriesExceededError immediately (simulates exhausted
          retries without 4x task re-runs — same pattern as test_tasks.py unit tests).

        The employee AuditLog carries correlation_id from the service layer.
        The task's failure AuditLog now also carries correlation_id —
        post-Sprint-18 follow-up bridging the service → task boundary. We assert
        the full chain integrity below.
        """
        from apps.hr.services import EmployeeOnboardingService

        email = "doctor.failopen@test.com"
        payload = _clinical_onboard_payload(email)
        service = EmployeeOnboardingService(requesting_user=self.admin)

        with (
            patch(_GW_PATCH) as mock_get_gw,
            patch(_USER_PATCH) as MockUser,
            patch.object(
                setup_staff_whatsapp_channel,
                "retry",
                side_effect=MaxRetriesExceededError(),
            ) as mock_retry,
        ):
            mock_gw = MagicMock()
            mock_gw.send_text.side_effect = ConnectionError("Evolution API down")
            mock_get_gw.return_value = mock_gw

            MockUser.DoesNotExist = User.DoesNotExist
            # MockUser.objects.get is configured after onboard() so we have the
            # real user's ID — we use a side_effect callable for this.
            created_users: list[User] = []

            def _get_user_side_effect(id):
                # Return the real created user with phone injected.
                # Called by the task after commit; real User.objects.get would
                # return the user WITHOUT phone (transient attribute, not a column).
                real = User.objects.using("default").get(id=id)
                return _mock_user_with_phone(real)

            MockUser.objects.get.side_effect = _get_user_side_effect

            # captureOnCommitCallbacks(execute=True) fires on_commit hooks when
            # the inner context exits — still inside the patch context, so
            # all mocks are active when the task runs.
            with self.captureOnCommitCallbacks(execute=True):
                employee = service.onboard(payload)

            _ = created_users  # unused var — suppress linter

        # ── 1. All DB rows persist ────────────────────────────────────────────
        self.assertIsNotNone(
            employee,
            "onboard() must return an Employee even after WhatsApp failure",
        )
        self.assertTrue(
            Employee.objects.filter(user__email=email).exists(),
            "Employee row must persist after WhatsApp gateway failure",
        )
        self.assertTrue(
            User.objects.filter(email=email).exists(),
            "User row must persist after WhatsApp gateway failure",
        )
        self.assertTrue(
            Professional.objects.filter(user__email=email).exists(),
            "Professional row must persist after WhatsApp gateway failure",
        )

        # ── 2. whatsapp_setup_failed AuditLog written ─────────────────────────
        failed_audit = AuditLog.objects.filter(action="whatsapp_setup_failed").first()
        self.assertIsNotNone(
            failed_audit,
            "AuditLog 'whatsapp_setup_failed' must be written when gateway raises persistently",
        )
        self.assertEqual(
            failed_audit.new_data.get("reason"),
            "max_retries_exceeded",
            "whatsapp_setup_failed AuditLog must record reason=max_retries_exceeded",
        )
        self.assertIn(
            "error",
            failed_audit.new_data,
            "whatsapp_setup_failed AuditLog must record the error string",
        )

        # ── 3. employee_created AuditLog carries correlation_id ───────────────
        employee_audit = AuditLog.objects.filter(action="employee_created").first()
        self.assertIsNotNone(
            employee_audit,
            "AuditLog 'employee_created' must exist (written inside atomic block)",
        )
        self.assertIn(
            "correlation_id",
            employee_audit.new_data,
            "employee_created AuditLog must carry correlation_id (decision 2A)",
        )
        # Correlation_id matches the service instance (chain integrity within service)
        self.assertEqual(
            employee_audit.new_data["correlation_id"],
            service.correlation_id,
            "employee_created correlation_id must match the service's correlation_id",
        )

        # ── 3b. Full cascade chain: failure audit shares correlation_id ───────
        self.assertIn(
            "correlation_id",
            failed_audit.new_data,
            "whatsapp_setup_failed AuditLog must carry correlation_id (decision 2A)",
        )
        self.assertEqual(
            failed_audit.new_data["correlation_id"],
            employee_audit.new_data["correlation_id"],
            "whatsapp_setup_failed correlation_id must match employee_created — "
            "this proves the cascade audit chain is intact across the service → task boundary",
        )

        # ── 4. Gateway was actually called (task ran past phone guard) ─────────
        self.assertTrue(
            mock_gw.send_text.called,
            "send_text must have been called — task must not skip silently at phone guard",
        )
        # Retry was called (confirming the failure path triggered retry logic)
        self.assertTrue(
            mock_retry.called,
            "self.retry must have been called when send_text raised ConnectionError",
        )

    # ── Test 2: intermittent failure → succeeds on retry ──────────────────────

    def test_whatsapp_intermittent_then_succeeds(self):
        """
        Intermittent gateway failure with eventual success (decision 1B variant).

        Gateway raises ConnectionError on the first call, succeeds on the second.
        The retry mechanism calls the task again (in this test we simulate the
        success by having gateway.send_text raise once then return None).

        Note: In eager mode, `self.retry()` re-runs the task recursively. The
        second run's gateway call succeeds, writing `whatsapp_channel_created`.
        We do NOT patch `self.retry` here — we let the real retry run one more
        task iteration with the succeeding gateway.

        side_effect list for send_text across all task invocations:
          call 1 (initial run):  raises ConnectionError → self.retry() called
          call 2 (retry 1):      returns None → success
        """
        from apps.hr.services import EmployeeOnboardingService

        email = "doctor.intermittent@test.com"
        payload = _clinical_onboard_payload(email)
        service = EmployeeOnboardingService(requesting_user=self.admin)

        with (
            patch(_GW_PATCH) as mock_get_gw,
            patch(_USER_PATCH) as MockUser,
        ):
            mock_gw = MagicMock()
            # First call raises, second call succeeds
            mock_gw.send_text.side_effect = [
                ConnectionError("transient"),
                None,  # success on retry
            ]
            mock_get_gw.return_value = mock_gw

            MockUser.DoesNotExist = User.DoesNotExist

            def _get_user_side_effect(id):
                real = User.objects.using("default").get(id=id)
                return _mock_user_with_phone(real)

            MockUser.objects.get.side_effect = _get_user_side_effect

            with self.captureOnCommitCallbacks(execute=True):
                employee = service.onboard(payload)

        # ── 1. DB rows persist ────────────────────────────────────────────────
        self.assertIsNotNone(employee)
        self.assertTrue(Employee.objects.filter(user__email=email).exists())
        self.assertTrue(User.objects.filter(email=email).exists())
        self.assertTrue(Professional.objects.filter(user__email=email).exists())

        # ── 2. Success AuditLog written + carries correlation_id ──────────────
        success_audit = AuditLog.objects.filter(
            action="whatsapp_channel_created",
            resource_type="user",
        ).first()
        self.assertIsNotNone(
            success_audit,
            "AuditLog 'whatsapp_channel_created' must be written on eventual success",
        )
        self.assertEqual(
            success_audit.new_data.get("correlation_id"),
            service.correlation_id,
            "whatsapp_channel_created correlation_id must match the service's correlation_id",
        )

        # ── 3. No failure AuditLog ────────────────────────────────────────────
        self.assertFalse(
            AuditLog.objects.filter(action="whatsapp_setup_failed").exists(),
            "AuditLog 'whatsapp_setup_failed' must NOT be written when gateway eventually succeeds",
        )

        # ── 4. Gateway called at least twice (1 fail + 1 success) ─────────────
        self.assertGreaterEqual(
            mock_gw.send_text.call_count,
            2,
            "send_text must be called at least twice: 1 failure + 1 success",
        )
