"""
Tests for Celery tasks — reminder sending, no-show marking, satisfaction surveys.
"""

from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.utils import timezone

from apps.core.models import Role, User
from apps.test_utils import TenantTestCase
from apps.whatsapp.models import ScheduledReminder, WhatsAppContact


def _make_patient_with_contact(phone="5511900000200", opt_in=True):
    from apps.emr.models import Patient

    patient = Patient.objects.create(
        full_name="Teste Reminder",
        cpf="52998224725",
        birth_date="1990-01-01",
        gender="N",
        whatsapp=phone,
    )
    contact, _ = WhatsAppContact.objects.get_or_create(phone=phone, defaults={"patient": patient})
    contact.patient = patient
    if opt_in:
        contact.do_opt_in()
    else:
        contact.save()
    return patient, contact


def _make_professional():
    from apps.emr.models import Professional, ScheduleConfig

    role, _ = Role.objects.get_or_create(name="medico", defaults={"permissions": []})
    user = User.objects.create_user(
        email=f"pro{timezone.now().timestamp()}@test.com",
        password="pw",
        role=role,
        full_name="Dr. Test",
    )
    pro = Professional.objects.create(
        user=user,
        council_type="CRM",
        council_number="99999",
        council_state="SP",
        specialty="Clínica Geral",
    )
    ScheduleConfig.objects.create(
        professional=pro,
        slot_duration_minutes=30,
        working_days=[0, 1, 2, 3, 4],
        working_hours_start="08:00",
        working_hours_end="18:00",
    )
    return pro


def _make_appointment(patient, professional, start_offset_hours=25, status="scheduled"):
    from datetime import timedelta

    from apps.emr.models import Appointment

    start = timezone.now() + timedelta(hours=start_offset_hours)
    end = start + timedelta(minutes=30)
    return Appointment.objects.create(
        patient=patient,
        professional=professional,
        start_time=start,
        end_time=end,
        status=status,
        source="whatsapp",
    )


class ReminderIdempotencyTests(TenantTestCase):
    def test_status_pending_to_sent_transition(self):
        patient, contact = _make_patient_with_contact()
        pro = _make_professional()
        appt = _make_appointment(patient, pro, start_offset_hours=24)

        reminder = ScheduledReminder.objects.create(
            appointment=appt,
            reminder_type="24h",
            status="pending",
        )
        with patch("apps.whatsapp.tasks.get_gateway") as mock_gw:
            mock_gw.return_value.send_if_opted_in = MagicMock()
            from apps.whatsapp.tasks import _send_reminder

            _send_reminder(mock_gw.return_value, reminder)

        reminder.refresh_from_db()
        self.assertEqual(reminder.status, "sent")
        self.assertIsNotNone(reminder.sent_at)

    def test_unique_together_prevents_duplicate_reminder_rows(self):
        patient, contact = _make_patient_with_contact(phone="5511900000201")
        pro = _make_professional()
        appt = _make_appointment(patient, pro)

        ScheduledReminder.objects.create(appointment=appt, reminder_type="24h", status="pending")
        # get_or_create should return existing row, not create a second
        reminder, created = ScheduledReminder.objects.get_or_create(
            appointment=appt,
            reminder_type="24h",
            defaults={"status": "pending"},
        )
        self.assertFalse(created)

    def test_failed_reminder_records_failed_status(self):
        patient, contact = _make_patient_with_contact(phone="5511900000202")
        pro = _make_professional()
        appt = _make_appointment(patient, pro)
        reminder = ScheduledReminder.objects.create(
            appointment=appt, reminder_type="2h", status="pending"
        )
        gateway = MagicMock()
        gateway.send_if_opted_in.side_effect = RuntimeError("network error")
        from apps.whatsapp.tasks import _send_reminder

        _send_reminder(gateway, reminder)
        reminder.refresh_from_db()
        self.assertEqual(reminder.status, "failed")


class NoShowTrackingTests(TenantTestCase):
    def test_appointment_past_without_confirmation_marked_no_show(self):
        from apps.emr.models import Appointment
        from apps.whatsapp.tasks import mark_no_shows

        patient, contact = _make_patient_with_contact(phone="5511900000203")
        pro = _make_professional()

        past_start = timezone.now() - timedelta(hours=2)
        past_end = past_start + timedelta(minutes=30)
        appt = Appointment.objects.create(
            patient=patient,
            professional=pro,
            start_time=past_start,
            end_time=past_end,
            status="scheduled",
            whatsapp_reminder_sent=True,
            whatsapp_confirmed=False,
        )
        mark_no_shows()
        appt.refresh_from_db()
        self.assertEqual(appt.status, "no_show")

    def test_confirmed_appointment_not_marked_no_show(self):
        from apps.emr.models import Appointment
        from apps.whatsapp.tasks import mark_no_shows

        patient, contact = _make_patient_with_contact(phone="5511900000204")
        pro = _make_professional()

        past_start = timezone.now() - timedelta(hours=2)
        past_end = past_start + timedelta(minutes=30)
        appt = Appointment.objects.create(
            patient=patient,
            professional=pro,
            start_time=past_start,
            end_time=past_end,
            status="scheduled",
            whatsapp_reminder_sent=True,
            whatsapp_confirmed=True,
        )
        mark_no_shows()
        appt.refresh_from_db()
        self.assertNotEqual(appt.status, "no_show")


class SatisfactionSurveyTests(TenantTestCase):
    def test_survey_not_sent_twice(self):
        patient, contact = _make_patient_with_contact(phone="5511900000205")
        pro = _make_professional()
        appt = _make_appointment(patient, pro, start_offset_hours=-3, status="completed")

        # Pre-create sent reminder
        ScheduledReminder.objects.create(
            appointment=appt, reminder_type="satisfaction", status="sent"
        )

        with patch("apps.whatsapp.tasks.get_gateway") as mock_gw:
            from apps.whatsapp.tasks import send_satisfaction_surveys

            send_satisfaction_surveys()

        mock_gw.return_value.send_if_opted_in.assert_not_called()

    def test_survey_not_sent_without_optin(self):
        patient, contact = _make_patient_with_contact(phone="5511900000206", opt_in=False)
        pro = _make_professional()
        _make_appointment(patient, pro, start_offset_hours=-3, status="completed")

        with patch("apps.whatsapp.tasks.get_gateway") as mock_gw:
            from apps.whatsapp.tasks import send_satisfaction_surveys

            send_satisfaction_surveys()

        mock_gw.return_value.send_if_opted_in.assert_not_called()
