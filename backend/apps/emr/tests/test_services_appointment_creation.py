"""Sprint 20 / S-090 — AppointmentCreationService unit tests.

Covers:
  - AuditLog written with correlation_id (decision 2A)
  - Opted-in contact → task enqueued + appointment_whatsapp_queued audit
  - Opted-out contact → no task + appointment_whatsapp_skipped audit
  - No contact at all → no task + appointment_whatsapp_skipped audit
  - correlation_id propagated to Celery task call args
"""

from datetime import date
from unittest.mock import MagicMock, patch

from django.utils import timezone

from apps.core.models import AuditLog, User
from apps.emr.models import Appointment, Patient, Professional
from apps.emr.services.appointment_creation import AppointmentCreationService
from apps.test_utils import TenantTestCase
from apps.whatsapp.models import WhatsAppContact

# ── Helpers ────────────────────────────────────────────────────────────────────

_TASK_PATCH = "apps.emr.services.appointment_creation.send_appointment_confirmation_whatsapp"


def _requesting_user():
    user, _ = User.objects.get_or_create(
        email="scheduler@example.com",
        defaults={"full_name": "Scheduler", "is_staff": True},
    )
    return user


def _make_patient(full_name="João Silva", cpf="111.222.333-00", whatsapp=""):
    return Patient.objects.create(
        full_name=full_name,
        cpf=cpf,
        birth_date=date(1985, 3, 10),
        gender="M",
        whatsapp=whatsapp,
    )


def _make_professional(email="doc@clinic.com", suffix="001"):
    user, _ = User.objects.get_or_create(
        email=email,
        defaults={"full_name": f"Dr. Test {suffix}"},
    )
    prof, _ = Professional.objects.get_or_create(
        user=user,
        defaults={
            "council_type": "CRM",
            "council_number": f"CRM{suffix}",
            "council_state": "SP",
        },
    )
    return prof


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


# ── Test Cases ─────────────────────────────────────────────────────────────────


class TestAppointmentCreationService(TenantTestCase):
    def setUp(self):
        self.requester = _requesting_user()
        self.patient = _make_patient()
        self.professional = _make_professional()

    # ── 1. AuditLog with correlation_id ────────────────────────────────────────

    def test_create_writes_audit_log_with_correlation_id(self):
        """appointment_created AuditLog is written with the service's correlation_id."""
        appt = _make_appointment(self.patient, self.professional)
        service = AppointmentCreationService(requesting_user=self.requester)

        with patch(_TASK_PATCH):
            service.create(appt)

        logs = AuditLog.objects.filter(
            action="appointment_created",
            resource_type="appointment",
            resource_id=str(appt.id),
        )
        self.assertEqual(logs.count(), 1)
        log = logs.first()
        self.assertIn("correlation_id", log.new_data)
        self.assertEqual(log.new_data["correlation_id"], service.correlation_id)
        self.assertEqual(log.new_data["patient_id"], str(appt.patient_id))
        self.assertEqual(log.new_data["professional_id"], str(appt.professional_id))

    # ── 2. Opted-in contact → task enqueued + queued audit ────────────────────

    def test_create_with_opted_in_contact_queues_task(self):
        """Patient with opt_in=True → task.delay() is called + appointment_whatsapp_queued audit."""
        WhatsAppContact.objects.create(
            phone="+5511911111111",
            patient=self.patient,
            opt_in=True,
        )
        appt = _make_appointment(self.patient, self.professional, offset_hours=3)
        service = AppointmentCreationService(requesting_user=self.requester)

        mock_task = MagicMock()
        with patch(_TASK_PATCH, mock_task):
            # No captureOnCommitCallbacks here — we just check .delay was set up.
            # on_commit fires when the atomic block exits in a non-test transaction;
            # unit tests use a wrapping transaction so on_commit does NOT fire here.
            # We verify the lambda was registered by running the atomic block and then
            # manually calling on_commit callbacks via captureOnCommitCallbacks.
            with self.captureOnCommitCallbacks(execute=True):
                service.create(appt)

        mock_task.delay.assert_called_once_with(str(appt.id), service.correlation_id)

        # appointment_whatsapp_queued audit written
        queued_audit = AuditLog.objects.filter(
            action="appointment_whatsapp_queued",
            resource_type="appointment",
            resource_id=str(appt.id),
        ).first()
        self.assertIsNotNone(queued_audit)
        self.assertEqual(queued_audit.new_data["correlation_id"], service.correlation_id)

    # ── 3. Opted-out contact → skip ───────────────────────────────────────────

    def test_create_without_opted_in_contact_skips_task(self):
        """Patient with opt_in=False → no task enqueue + appointment_whatsapp_skipped audit."""
        WhatsAppContact.objects.create(
            phone="+5511922222222",
            patient=self.patient,
            opt_in=False,
        )
        appt = _make_appointment(self.patient, self.professional, offset_hours=4)
        service = AppointmentCreationService(requesting_user=self.requester)

        mock_task = MagicMock()
        with patch(_TASK_PATCH, mock_task):
            service.create(appt)

        mock_task.delay.assert_not_called()

        skipped_audit = AuditLog.objects.filter(
            action="appointment_whatsapp_skipped",
            resource_type="appointment",
            resource_id=str(appt.id),
        ).first()
        self.assertIsNotNone(skipped_audit)
        self.assertEqual(skipped_audit.new_data["reason"], "no_opted_in_contact")

    # ── 4. No contact at all → skip ───────────────────────────────────────────

    def test_create_with_no_contact_skips_task(self):
        """Patient with no WhatsAppContact at all → same skip behavior as opted-out."""
        # No WhatsAppContact created for this patient
        patient2 = _make_patient(full_name="Sem Contato", cpf="999.888.777-00")
        appt = _make_appointment(patient2, self.professional, offset_hours=5)
        service = AppointmentCreationService(requesting_user=self.requester)

        mock_task = MagicMock()
        with patch(_TASK_PATCH, mock_task):
            service.create(appt)

        mock_task.delay.assert_not_called()

        skipped_audit = AuditLog.objects.filter(
            action="appointment_whatsapp_skipped",
            resource_type="appointment",
            resource_id=str(appt.id),
        ).first()
        self.assertIsNotNone(skipped_audit)
        self.assertEqual(skipped_audit.new_data["reason"], "no_opted_in_contact")

    # ── 5. correlation_id propagates to task ──────────────────────────────────

    def test_create_correlation_id_propagates_to_task(self):
        """Task is called with the service's correlation_id as the second positional arg."""
        WhatsAppContact.objects.create(
            phone="+5511933333333",
            patient=self.patient,
            opt_in=True,
        )
        appt = _make_appointment(self.patient, self.professional, offset_hours=6)
        service = AppointmentCreationService(requesting_user=self.requester)

        mock_task = MagicMock()
        with patch(_TASK_PATCH, mock_task):
            with self.captureOnCommitCallbacks(execute=True):
                service.create(appt)

        # Verify the exact args passed to delay()
        call_args = mock_task.delay.call_args
        self.assertIsNotNone(call_args)
        positional_args = call_args[0]  # positional args tuple
        self.assertEqual(positional_args[0], str(appt.id))
        self.assertEqual(positional_args[1], service.correlation_id)
