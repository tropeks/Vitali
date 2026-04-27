"""Sprint 20 / S-090 — CRITICAL Appointment F-02 fail-open integration test.

Mirrors apps/hr/tests/test_integration_whatsapp_failopen.py (Sprint 18 T13).

Cornerstone test for the cascade architecture (locked decision 1B):
  - Appointment row persists even when EvolutionAPIGateway raises ConnectionError
    during the post-commit WhatsApp confirmation task.
  - AuditLog 'appointment_whatsapp_failed' is written on persistent failure.
  - AuditLog 'appointment_whatsapp_sent' is written on eventual success.
  - Full correlation_id chain: appointment_created → appointment_whatsapp_queued
    → appointment_whatsapp_failed/sent all share correlation_id (decision 2A).

Architecture invariant being proven:
  transaction.atomic() commits BEFORE transaction.on_commit() fires the
  Celery task. Any exception inside the task cannot roll back the committed
  Appointment row.

Test design:
  - @override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=False)
    runs the task inline synchronously within the test process.
  - captureOnCommitCallbacks(execute=True) fires on_commit hooks synchronously
    inside TenantTestCase's wrapping transaction (Django 4.1+).
  - apps.emr.tasks.get_gateway is patched to raise ConnectionError.
  - send_appointment_confirmation_whatsapp.retry is patched to raise
    MaxRetriesExceededError immediately (simulates retries-exhausted state in
    one call — same pattern as Sprint 18 T13).
  - For the success variant: gateway raises once then succeeds; no retry patch
    needed (real retry runs one more task iteration with succeeding gateway).
"""

from unittest.mock import MagicMock, patch

from celery.exceptions import MaxRetriesExceededError
from django.test import override_settings
from django.utils import timezone

from apps.core.models import AuditLog, User
from apps.emr.models import Appointment, Patient, Professional
from apps.emr.services.appointment_creation import AppointmentCreationService
from apps.emr.tasks import send_appointment_confirmation_whatsapp
from apps.test_utils import TenantTestCase
from apps.whatsapp.models import WhatsAppContact

# ── Patch targets ─────────────────────────────────────────────────────────────
# get_gateway is imported inside the task body via `from apps.whatsapp.gateway import get_gateway`,
# so we patch the canonical source location used at import time.
_GW_PATCH = "apps.whatsapp.gateway.get_gateway"

# ── Helpers ────────────────────────────────────────────────────────────────────

PHONE = "+5511988888888"


def _make_infra():
    """Create Patient + Professional + WhatsAppContact(opt_in=True)."""
    from datetime import date

    patient = Patient.objects.create(
        full_name="Paciente Teste",
        cpf="555.666.777-88",
        birth_date=date(1990, 7, 20),
        gender="F",
        whatsapp=PHONE,
    )
    contact = WhatsAppContact.objects.create(
        phone=PHONE,
        patient=patient,
        opt_in=True,
    )
    admin_user, _ = User.objects.get_or_create(
        email="admin_failopen@test.com",
        defaults={"full_name": "Admin Fail-Open", "is_staff": True},
    )
    prof_user, _ = User.objects.get_or_create(
        email="doc_failopen@test.com",
        defaults={"full_name": "Dr. Fail-Open"},
    )
    professional, _ = Professional.objects.get_or_create(
        user=prof_user,
        defaults={
            "council_type": "CRM",
            "council_number": "CRMFO1",
            "council_state": "SP",
        },
    )
    return patient, contact, professional, admin_user


def _make_appointment(patient, professional, offset_hours=2):
    from datetime import timedelta

    start = timezone.now() + timedelta(hours=offset_hours)
    end = start + timedelta(minutes=30)
    return Appointment.objects.create(
        patient=patient,
        professional=professional,
        start_time=start,
        end_time=end,
        status="scheduled",
    )


# ── Test class ─────────────────────────────────────────────────────────────────


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=False)
class AppointmentFailOpenIntegrationTests(TenantTestCase):
    """
    Integration tests for the fail-open Appointment WhatsApp cascade (decision 1B).

    These tests exercise the full stack:
      AppointmentCreationService → transaction.on_commit → Celery task (eager)
      → EvolutionAPIGateway (mocked) → AuditLog

    The Appointment row must ALWAYS persist regardless of what the task does.
    """

    def setUp(self):
        super().setUp()
        self.patient, self.contact, self.professional, self.admin = _make_infra()

    # ── Test 1: persistent gateway failure → appointment persists + failure log ─

    def test_whatsapp_failure_does_not_roll_back_appointment(self):
        """
        CORNERSTONE TEST — locked decision 1B.

        When EvolutionAPIGateway.send_text raises ConnectionError and all retries
        are exhausted (MaxRetriesExceededError), the cascade must:
          1. Commit the Appointment row to the DB (atomic block done).
          2. Fire the on_commit task (eagerly, synchronously).
          3. Write AuditLog 'appointment_whatsapp_failed'.
          4. NOT raise or propagate the exception to the caller.

        Full correlation_id chain: appointment_created → appointment_whatsapp_queued
        → appointment_whatsapp_failed all share the same correlation_id (decision 2A).
        """
        appt = _make_appointment(self.patient, self.professional, offset_hours=10)
        service = AppointmentCreationService(requesting_user=self.admin)

        with (
            patch(_GW_PATCH) as mock_get_gw,
            patch.object(
                send_appointment_confirmation_whatsapp,
                "retry",
                side_effect=MaxRetriesExceededError(),
            ) as mock_retry,
        ):
            mock_gw = MagicMock()
            mock_gw.send_text.side_effect = ConnectionError("Evolution API down")
            mock_get_gw.return_value = mock_gw

            # captureOnCommitCallbacks(execute=True) fires on_commit hooks when
            # the inner context exits — still inside the patch context, so all
            # mocks are active when the task runs.
            with self.captureOnCommitCallbacks(execute=True):
                service.create(appt)

        # ── 1. Appointment row persists ───────────────────────────────────────
        self.assertTrue(
            Appointment.objects.filter(pk=appt.pk).exists(),
            "Appointment row must persist after WhatsApp gateway failure",
        )

        # ── 2. appointment_whatsapp_failed AuditLog written ───────────────────
        failed_audit = AuditLog.objects.filter(
            action="appointment_whatsapp_failed",
            resource_type="appointment",
            resource_id=str(appt.id),
        ).first()
        self.assertIsNotNone(
            failed_audit,
            "AuditLog 'appointment_whatsapp_failed' must be written when gateway raises persistently",
        )
        self.assertEqual(
            failed_audit.new_data.get("reason"),
            "max_retries_exceeded",
            "appointment_whatsapp_failed AuditLog must record reason=max_retries_exceeded",
        )
        self.assertIn(
            "error",
            failed_audit.new_data,
            "appointment_whatsapp_failed AuditLog must record the error string",
        )

        # ── 3. appointment_created AuditLog carries correlation_id ────────────
        created_audit = AuditLog.objects.filter(
            action="appointment_created",
            resource_type="appointment",
            resource_id=str(appt.id),
        ).first()
        self.assertIsNotNone(created_audit, "AuditLog 'appointment_created' must exist")
        self.assertIn("correlation_id", created_audit.new_data)
        self.assertEqual(
            created_audit.new_data["correlation_id"],
            service.correlation_id,
            "appointment_created correlation_id must match service's correlation_id",
        )

        # ── 4. Full cascade chain: failure audit shares correlation_id ─────────
        self.assertIn(
            "correlation_id",
            failed_audit.new_data,
            "appointment_whatsapp_failed must carry correlation_id (decision 2A)",
        )
        self.assertEqual(
            failed_audit.new_data["correlation_id"],
            created_audit.new_data["correlation_id"],
            "appointment_whatsapp_failed correlation_id must match appointment_created — "
            "full cascade audit chain integrity across service → task boundary",
        )

        # ── 5. Gateway was actually called (task reached send_text) ───────────
        self.assertTrue(
            mock_gw.send_text.called,
            "send_text must have been called — task must not skip at opt-in guard",
        )
        self.assertTrue(
            mock_retry.called,
            "self.retry must have been called when send_text raised ConnectionError",
        )

    # ── Test 2: intermittent failure → succeeds on retry ─────────────────────

    def test_whatsapp_intermittent_then_succeeds(self):
        """
        Intermittent gateway failure with eventual success (decision 1B variant).

        Gateway raises ConnectionError on the first send_text call, succeeds on
        the second (retry run). In eager mode, self.retry() re-runs the task
        recursively. The second run's gateway call succeeds, writing
        'appointment_whatsapp_sent'.

        side_effect list for send_text across all task invocations:
          call 1 (initial run):  raises ConnectionError → self.retry() called
          call 2 (retry 1):      returns None → success path
        """
        appt = _make_appointment(self.patient, self.professional, offset_hours=11)
        service = AppointmentCreationService(requesting_user=self.admin)

        with patch(_GW_PATCH) as mock_get_gw:
            mock_gw = MagicMock()
            mock_gw.send_text.side_effect = [
                ConnectionError("transient"),
                None,  # success on retry
            ]
            mock_get_gw.return_value = mock_gw

            with self.captureOnCommitCallbacks(execute=True):
                service.create(appt)

        # ── 1. Appointment row persists ───────────────────────────────────────
        self.assertTrue(Appointment.objects.filter(pk=appt.pk).exists())

        # ── 2. appointment_whatsapp_sent AuditLog written ─────────────────────
        sent_audit = AuditLog.objects.filter(
            action="appointment_whatsapp_sent",
            resource_type="appointment",
            resource_id=str(appt.id),
        ).first()
        self.assertIsNotNone(
            sent_audit,
            "AuditLog 'appointment_whatsapp_sent' must be written on eventual success",
        )
        self.assertEqual(
            sent_audit.new_data.get("correlation_id"),
            service.correlation_id,
            "appointment_whatsapp_sent correlation_id must match service's correlation_id",
        )

        # ── 3. No failure AuditLog ────────────────────────────────────────────
        self.assertFalse(
            AuditLog.objects.filter(
                action="appointment_whatsapp_failed",
                resource_type="appointment",
                resource_id=str(appt.id),
            ).exists(),
            "AuditLog 'appointment_whatsapp_failed' must NOT be written when gateway eventually succeeds",
        )

        # ── 4. Gateway called at least twice ──────────────────────────────────
        self.assertGreaterEqual(
            mock_gw.send_text.call_count,
            2,
            "send_text must be called at least twice: 1 failure + 1 success",
        )
