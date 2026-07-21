"""
F-11 (E-013): No-show cascade — integration tests with a mocked WhatsApp gateway.

Covers the acceptance criteria:
  - Marking an appointment as no_show fires a re-engagement WhatsApp to the
    patient *only if* they have an opted-in WhatsApp contact.
  - The slot reopens (no_show is excluded from booked filters) and the waitlist
    is consulted — the first eligible entry transitions to ``notified``.
  - The PATCH /status endpoint triggers the cascade end-to-end.
  - The hourly ``mark_no_shows`` auto-marker also triggers the cascade.

Celery runs eager so the chained ``notify_next_waitlist_entry.delay`` executes
synchronously; the gateway is patched in both modules that resolve it.
"""

import datetime
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.db import connection
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.test_utils import TenantTestCase

GW_CASCADE = "apps.emr.services.no_show_cascade.get_gateway"
GW_WAITLIST = "apps.emr.tasks_waitlist.get_gateway"
# Under CELERY_TASK_ALWAYS_EAGER the countdown-scheduled expiry task would run
# immediately (eager ignores countdown), flipping the entry notified→expired.
# Patch it out so the test observes the real intermediate "notified" state.
EXPIRY_SCHEDULE = "apps.emr.tasks_waitlist.expire_single_waitlist_entry.apply_async"


def _make_infra():
    from django.contrib.auth import get_user_model

    from apps.core.models import Role
    from apps.core.permissions import DEFAULT_ROLES
    from apps.emr.models import Patient, Professional

    User = get_user_model()
    role = Role.objects.create(name="recep_ns", permissions=DEFAULT_ROLES["recepcionista"])
    user = User.objects.create_user(
        email="noshow_user@test.com",
        password="TestPass123!",
        full_name="Dra. Ana Souza",
        role=role,
    )
    professional = Professional.objects.create(
        user=user,
        council_type="CRM",
        council_number="990100",
        council_state="SP",
    )
    patient = Patient.objects.create(
        full_name="Paciente Faltante",
        birth_date=datetime.date(1990, 5, 15),
        gender="M",
        cpf="33333333333",
        phone="5511999990010",
        whatsapp="5511999990010",
    )
    return user, professional, patient


def _make_contact(patient, *, opt_in: bool):
    from apps.whatsapp.models import WhatsAppContact

    return WhatsAppContact.objects.create(
        phone=patient.whatsapp,
        patient=patient,
        opt_in=opt_in,
        opt_in_at=timezone.now() if opt_in else None,
    )


def _make_appointment(patient, professional, *, status="scheduled", hours_ahead=2, **extra):
    from apps.emr.models import Appointment

    start = timezone.now() + timedelta(hours=hours_ahead)
    end = start + timedelta(minutes=30)
    return Appointment.objects.create(
        patient=patient,
        professional=professional,
        start_time=start,
        end_time=end,
        status=status,
        **extra,
    )


def _make_waitlist_entry(patient, professional, slot_date):
    from apps.emr.models import WaitlistEntry

    return WaitlistEntry.objects.create(
        patient=patient,
        professional=professional,
        preferred_date_from=slot_date,
        preferred_date_to=slot_date,
        status="waiting",
    )


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
class TestNoShowCascade(TenantTestCase):
    def setUp(self):
        from apps.emr.models import Patient

        self.user, self.professional, self.patient = _make_infra()
        # A second patient that sits on the waitlist for the same professional.
        self.waitlist_patient = Patient.objects.create(
            full_name="Paciente da Fila",
            birth_date=datetime.date(1992, 7, 10),
            gender="F",
            cpf="44444444444",
            phone="5511999990011",
            whatsapp="5511999990011",
        )

    def _client(self):
        c = APIClient()
        c.defaults["SERVER_NAME"] = self.__class__.domain.domain
        c.force_authenticate(user=self.user)
        return c

    # ── service-level cascade ────────────────────────────────────────────────

    def test_cascade_sends_reengagement_and_consults_waitlist(self):
        _make_contact(self.patient, opt_in=True)
        appt = _make_appointment(self.patient, self.professional)
        appt.status = "no_show"
        appt.save(update_fields=["status", "updated_at"])
        entry = _make_waitlist_entry(
            self.waitlist_patient, self.professional, appt.start_time.date()
        )

        from apps.emr.tasks_waitlist import cascade_no_show

        gateway = MagicMock()
        with (
            patch(GW_CASCADE, return_value=gateway),
            patch(GW_WAITLIST, return_value=gateway),
            patch(EXPIRY_SCHEDULE),
        ):
            cascade_no_show(str(appt.id))

        # Re-engagement WhatsApp went to the no-show patient.
        gateway.send_if_opted_in.assert_called_once()
        sent_contact, sent_text = gateway.send_if_opted_in.call_args[0]
        self.assertEqual(sent_contact.patient_id, self.patient.id)
        self.assertIn("REAGENDAR", sent_text)

        # Slot was offered to the first waitlist entry (waitlist consulted).
        entry.refresh_from_db()
        self.assertEqual(entry.status, "notified")
        self.assertIsNotNone(entry.offered_slot)
        gateway.send_text.assert_called_once()

    def test_cascade_skips_outreach_without_opt_in(self):
        # Contact exists but has NOT opted in → no re-engagement message.
        _make_contact(self.patient, opt_in=False)
        appt = _make_appointment(self.patient, self.professional)
        appt.status = "no_show"
        appt.save(update_fields=["status", "updated_at"])

        from apps.emr.tasks_waitlist import cascade_no_show

        gateway = MagicMock()
        with patch(GW_CASCADE, return_value=gateway), patch(GW_WAITLIST, return_value=gateway):
            cascade_no_show(str(appt.id))

        gateway.send_if_opted_in.assert_not_called()

    def test_cascade_noop_when_status_not_no_show(self):
        _make_contact(self.patient, opt_in=True)
        appt = _make_appointment(self.patient, self.professional)  # still 'scheduled'

        from apps.emr.tasks_waitlist import cascade_no_show

        gateway = MagicMock()
        with patch(GW_CASCADE, return_value=gateway), patch(GW_WAITLIST, return_value=gateway):
            cascade_no_show(str(appt.id))

        gateway.send_if_opted_in.assert_not_called()

    # ── view-triggered cascade (PATCH /status) ───────────────────────────────

    def test_status_patch_to_no_show_triggers_cascade(self):
        _make_contact(self.patient, opt_in=True)
        appt = _make_appointment(self.patient, self.professional)
        entry = _make_waitlist_entry(
            self.waitlist_patient, self.professional, appt.start_time.date()
        )

        gateway = MagicMock()
        client = self._client()
        with (
            patch(GW_CASCADE, return_value=gateway),
            patch(GW_WAITLIST, return_value=gateway),
            patch(EXPIRY_SCHEDULE),
        ):
            with self.captureOnCommitCallbacks(execute=True):
                resp = client.patch(
                    f"/api/v1/appointments/{appt.id}/status/",
                    {"status": "no_show"},
                    format="json",
                )

        self.assertEqual(resp.status_code, 200)
        appt.refresh_from_db()
        self.assertEqual(appt.status, "no_show")
        gateway.send_if_opted_in.assert_called_once()
        entry.refresh_from_db()
        self.assertEqual(entry.status, "notified")

    # ── auto-marker cascade (mark_no_shows) ──────────────────────────────────

    def test_mark_no_shows_triggers_cascade_per_appointment(self):
        from apps.whatsapp.tasks import _mark_no_shows_for_schema

        _make_contact(self.patient, opt_in=True)
        # Eligible for the auto-marker: reminder sent, unconfirmed, ended >30min ago.
        appt = _make_appointment(
            self.patient,
            self.professional,
            hours_ahead=-2,
            whatsapp_reminder_sent=True,
            whatsapp_confirmed=False,
        )

        with patch("apps.emr.tasks_waitlist.cascade_no_show.delay") as mock_delay:
            marked = _mark_no_shows_for_schema(connection.schema_name)

        self.assertEqual(marked, 1)
        appt.refresh_from_db()
        self.assertEqual(appt.status, "no_show")
        mock_delay.assert_called_once_with(str(appt.id))
