"""Sprint 21 / S-100 — CRITICAL Encounter F-03 fail-open integration test.

Mirrors apps/hr/tests/test_integration_whatsapp_failopen.py (Sprint 18 T13)
and apps/emr/tests/test_integration_appointment_failopen.py (Sprint 20 S-090).

Cornerstone test for the cascade architecture (locked decision 1B):
  - Encounter row (status='signed', signed_at, signed_by) persists even when
    EvolutionAPIGateway raises ConnectionError during the post-commit
    WhatsApp follow-up task.
  - AuditLog 'followup_failed' is written on persistent failure.
  - Full correlation_id chain: encounter_signed → followup_scheduled →
    followup_failed all share the same correlation_id (decision 2A).

Architecture invariant being proven:
  transaction.atomic() commits BEFORE transaction.on_commit() fires the
  Celery task. Any exception inside the task cannot roll back the committed
  Encounter row.

Test design:
  - @override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=False)
    runs the task inline synchronously within the test process.
  - captureOnCommitCallbacks(execute=True) fires on_commit hooks synchronously
    inside TenantTestCase's wrapping transaction (Django 4.1+).
  - apps.whatsapp.gateway.get_gateway is patched to raise ConnectionError.
  - send_post_visit_followup_whatsapp.retry is patched to raise
    MaxRetriesExceededError immediately (simulates retries-exhausted state in
    one call — same pattern as Sprint 18 T13 and Sprint 20 S-090).

Note on apply_async with countdown in eager mode:
  CELERY_TASK_ALWAYS_EAGER=True causes apply_async to execute the task
  synchronously, ignoring the countdown. This means the 24h delay is
  effectively 0 in tests — the task runs immediately inside
  captureOnCommitCallbacks. We patch the gateway and retry to control
  exactly what the task does.
"""

from datetime import date
from unittest.mock import MagicMock, patch

from celery.exceptions import MaxRetriesExceededError
from django.test import override_settings

from apps.core.models import AuditLog, User
from apps.emr.models import Encounter, Patient, Professional
from apps.emr.services.encounter_signing import EncounterSigningService
from apps.emr.tasks import send_post_visit_followup_whatsapp
from apps.test_utils import TenantTestCase
from apps.whatsapp.models import WhatsAppContact

# ── Patch targets ─────────────────────────────────────────────────────────────
# get_gateway is imported inside the task body via `from apps.whatsapp.gateway import get_gateway`,
# so we patch the canonical source location used at import time.
_GW_PATCH = "apps.whatsapp.gateway.get_gateway"

# ── Helpers ───────────────────────────────────────────────────────────────────

PHONE = "+5511977777777"


def _make_infra():
    """Create Patient + Professional + WhatsAppContact(opt_in=True) + admin User."""
    patient = Patient.objects.create(
        full_name="Paciente Followup",
        cpf="123.456.789-00",
        birth_date=date(1985, 6, 15),
        gender="M",
        whatsapp=PHONE,
    )
    contact = WhatsAppContact.objects.create(
        phone=PHONE,
        patient=patient,
        opt_in=True,
    )
    admin_user, _ = User.objects.get_or_create(
        email="admin_enc_failopen@test.com",
        defaults={"full_name": "Admin Enc Fail-Open", "is_staff": True},
    )
    prof_user, _ = User.objects.get_or_create(
        email="doc_enc_failopen@test.com",
        defaults={"full_name": "Dr. Enc Fail-Open"},
    )
    professional, _ = Professional.objects.get_or_create(
        user=prof_user,
        defaults={
            "council_type": "CRM",
            "council_number": "CRMEF1",
            "council_state": "SP",
        },
    )
    return patient, contact, professional, admin_user


def _make_encounter(patient, professional):
    return Encounter.objects.create(
        patient=patient,
        professional=professional,
        status="open",
        chief_complaint="Consulta de rotina",
    )


# ── Test class ────────────────────────────────────────────────────────────────


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=False)
class EncounterSignedFailOpenIntegrationTests(TenantTestCase):
    """
    Integration tests for the fail-open Encounter WhatsApp follow-up cascade
    (decision 1B).

    These tests exercise the full stack:
      EncounterSigningService → transaction.on_commit → Celery task (eager)
      → EvolutionAPIGateway (mocked) → AuditLog

    The Encounter row must ALWAYS persist (status='signed', signed_at set)
    regardless of what the follow-up task does.
    """

    def setUp(self):
        super().setUp()
        self.patient, self.contact, self.professional, self.admin = _make_infra()

    # ── Test 1: persistent gateway failure → encounter persists + failure log ──

    def test_followup_failure_does_not_roll_back_encounter(self):
        """
        CORNERSTONE TEST — locked decision 1B.

        When EvolutionAPIGateway.send_text raises ConnectionError and all retries
        are exhausted (MaxRetriesExceededError), the cascade must:
          1. Commit the Encounter row as status='signed' with signed_at and signed_by.
          2. Fire the on_commit task (eagerly, synchronously via apply_async).
          3. Write AuditLog 'followup_failed'.
          4. NOT raise or propagate the exception to the caller.

        Full correlation_id chain: encounter_signed → followup_scheduled →
        followup_failed all share the same correlation_id (decision 2A).
        """
        encounter = _make_encounter(self.patient, self.professional)
        service = EncounterSigningService(requesting_user=self.admin)

        with (
            patch(_GW_PATCH) as mock_get_gw,
            patch.object(
                send_post_visit_followup_whatsapp,
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
            # In eager mode, apply_async(countdown=86400) runs the task
            # synchronously, ignoring the countdown.
            with self.captureOnCommitCallbacks(execute=True):
                result = service.sign(encounter)

        # ── 1. Encounter row persists as signed ───────────────────────────────
        self.assertIsNotNone(result, "sign() must return the Encounter even after task failure")
        encounter.refresh_from_db()
        self.assertEqual(
            encounter.status,
            "signed",
            "Encounter.status must be 'signed' even after WhatsApp follow-up failure",
        )
        self.assertIsNotNone(
            encounter.signed_at,
            "Encounter.signed_at must be set even after WhatsApp follow-up failure",
        )
        self.assertEqual(
            encounter.signed_by_id,
            self.admin.id,
            "Encounter.signed_by must be the requesting user",
        )

        # ── 2. followup_failed AuditLog written ───────────────────────────────
        failed_audit = AuditLog.objects.filter(
            action="followup_failed",
            resource_type="encounter",
            resource_id=str(encounter.id),
        ).first()
        self.assertIsNotNone(
            failed_audit,
            "AuditLog 'followup_failed' must be written when gateway raises persistently",
        )
        self.assertEqual(
            failed_audit.new_data.get("reason"),
            "max_retries_exceeded",
            "followup_failed AuditLog must record reason=max_retries_exceeded",
        )
        self.assertIn(
            "error",
            failed_audit.new_data,
            "followup_failed AuditLog must record the error string",
        )

        # ── 3. encounter_signed AuditLog carries correlation_id ───────────────
        signed_audit = AuditLog.objects.filter(
            action="encounter_signed",
            resource_type="encounter",
            resource_id=str(encounter.id),
        ).first()
        self.assertIsNotNone(signed_audit, "AuditLog 'encounter_signed' must exist")
        self.assertIn("correlation_id", signed_audit.new_data)
        self.assertEqual(
            signed_audit.new_data["correlation_id"],
            service.correlation_id,
            "encounter_signed correlation_id must match the service's correlation_id",
        )

        # ── 4. Full cascade chain: failure audit shares correlation_id ─────────
        self.assertIn(
            "correlation_id",
            failed_audit.new_data,
            "followup_failed must carry correlation_id (decision 2A)",
        )
        self.assertEqual(
            failed_audit.new_data["correlation_id"],
            signed_audit.new_data["correlation_id"],
            "followup_failed correlation_id must match encounter_signed — "
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

    def test_followup_intermittent_then_succeeds(self):
        """
        Intermittent gateway failure with eventual success (decision 1B variant).

        Gateway raises ConnectionError on the first send_text call, succeeds on
        the second (retry run). In eager mode, self.retry() re-runs the task
        recursively. The second run's gateway call succeeds, writing 'followup_sent'.

        side_effect list for send_text across all task invocations:
          call 1 (initial run):  raises ConnectionError → self.retry() called
          call 2 (retry 1):      returns None → success path
        """
        encounter = _make_encounter(self.patient, self.professional)
        service = EncounterSigningService(requesting_user=self.admin)

        with patch(_GW_PATCH) as mock_get_gw:
            mock_gw = MagicMock()
            mock_gw.send_text.side_effect = [
                ConnectionError("transient"),
                None,  # success on retry
            ]
            mock_get_gw.return_value = mock_gw

            with self.captureOnCommitCallbacks(execute=True):
                service.sign(encounter)

        # ── 1. Encounter row persists as signed ───────────────────────────────
        encounter.refresh_from_db()
        self.assertEqual(encounter.status, "signed")
        self.assertIsNotNone(encounter.signed_at)

        # ── 2. followup_sent AuditLog written + carries correlation_id ────────
        sent_audit = AuditLog.objects.filter(
            action="followup_sent",
            resource_type="encounter",
            resource_id=str(encounter.id),
        ).first()
        self.assertIsNotNone(
            sent_audit,
            "AuditLog 'followup_sent' must be written on eventual success",
        )
        self.assertEqual(
            sent_audit.new_data.get("correlation_id"),
            service.correlation_id,
            "followup_sent correlation_id must match the service's correlation_id",
        )

        # ── 3. No failure AuditLog ────────────────────────────────────────────
        self.assertFalse(
            AuditLog.objects.filter(
                action="followup_failed",
                resource_type="encounter",
                resource_id=str(encounter.id),
            ).exists(),
            "AuditLog 'followup_failed' must NOT be written when gateway eventually succeeds",
        )

        # ── 4. Gateway called at least twice ──────────────────────────────────
        self.assertGreaterEqual(
            mock_gw.send_text.call_count,
            2,
            "send_text must be called at least twice: 1 failure + 1 success",
        )
