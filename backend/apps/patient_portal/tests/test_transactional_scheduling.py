"""S5-T1 — self-service scheduling through the patient portal."""

from __future__ import annotations

from datetime import date, timedelta

from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import AuditLog, FeatureFlag, Role, User
from apps.emr.models import Appointment, Patient, Professional, ScheduleConfig
from apps.patient_portal.models import PatientPortalAccess, PortalConsent
from apps.patient_portal.transactional_models import PortalScheduleRequest
from apps.test_utils import TenantTestCase

SLOTS_URL = "/api/v1/portal/me/schedule/slots/"
BOOK_URL = "/api/v1/portal/me/appointments/book/"


def _reschedule_url(pk):
    return f"/api/v1/portal/me/appointments/{pk}/reschedule/"


def _cancel_url(pk):
    return f"/api/v1/portal/me/appointments/{pk}/cancel/"


def _make_user(*, role_name, perms, email, full_name):
    role, _ = Role.objects.get_or_create(name=role_name, defaults={"permissions": perms})
    role.permissions = perms
    role.save()
    return User.objects.create_user(email=email, password="pw", role=role, full_name=full_name)


class PortalSchedulingTest(TenantTestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key="patient_portal",
            defaults={"is_enabled": True},
        )
        self.admin = _make_user(
            role_name="sched_admin",
            perms=["users.read", "users.write"],
            email="admin_s@test.com",
            full_name="Admin",
        )
        self.patient = Patient.objects.create(
            full_name="Ana Souza", cpf="12345678909", birth_date=date(1985, 7, 14), gender="F"
        )
        self.patient_user = _make_user(
            role_name="sched_self",
            perms=["portal.self_access"],
            email="ana_s@test.com",
            full_name="Ana Souza",
        )
        self.other_patient = Patient.objects.create(
            full_name="Bruno Lima", cpf="98765432100", birth_date=date(1990, 3, 1), gender="M"
        )
        self.md_user = _make_user(
            role_name="md_s", perms=["users.read"], email="md_s@test.com", full_name="Dra Bia"
        )
        self.md = Professional.objects.create(
            user=self.md_user, council_type="CRM", council_number="700500", council_state="SP"
        )
        ScheduleConfig.objects.create(
            professional=self.md,
            slot_duration_minutes=30,
            working_days=[0, 1, 2, 3, 4, 5, 6],
            working_hours_start="08:00",
            working_hours_end="18:00",
            is_active=True,
        )
        # Activate portal access + grant LGPD scheduling consent.
        access = PatientPortalAccess.objects.create(
            user=self.patient_user, patient=self.patient, created_by=self.admin
        )
        access.activate()
        self.consent = PortalConsent.objects.create(
            patient=self.patient,
            granted_by=self.patient_user,
            purpose="portal_scheduling",
            policy_version="1.0",
        )
        self.client.force_authenticate(user=self.patient_user)

    def _first_slot_iso(self) -> str:
        resp = self.client.get(SLOTS_URL, {"professional": str(self.md.pk), "days": 3})
        self.assertEqual(resp.status_code, 200, resp.data)
        for _day, slots in resp.data["slots"].items():
            if slots:
                return slots[0]["start"]
        raise AssertionError("no available slot returned by slot engine")

    def _local_dt(self, days_ahead, hour):
        base = timezone.localtime(timezone.now()) + timedelta(days=days_ahead)
        return base.replace(hour=hour, minute=0, second=0, microsecond=0)

    # ── happy paths ────────────────────────────────────────────────────────────

    def test_slots_endpoint_lists_availability(self):
        resp = self.client.get(SLOTS_URL, {"professional": str(self.md.pk)})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["professional"], str(self.md.pk))
        self.assertTrue(any(resp.data["slots"].values()))

    def test_patient_books_available_slot(self):
        start = self._first_slot_iso()
        resp = self.client.post(
            BOOK_URL, {"professional": str(self.md.pk), "start_time": start}, format="json"
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data["patient"], str(self.patient.pk))
        self.assertEqual(resp.data["source"], "web")
        appt = Appointment.objects.get(pk=resp.data["id"])
        self.assertEqual(appt.patient_id, self.patient.pk)
        self.assertTrue(
            PortalScheduleRequest.objects.filter(appointment=appt, action="book").exists()
        )
        self.assertTrue(
            AuditLog.objects.filter(
                action="portal_appointment_book", resource_id=str(appt.pk)
            ).exists()
        )

    def test_patient_reschedules_own_appointment(self):
        start = self._first_slot_iso()
        booked = self.client.post(
            BOOK_URL, {"professional": str(self.md.pk), "start_time": start}, format="json"
        )
        appt_id = booked.data["id"]
        # Reschedule to another available slot.
        new_start = self._local_dt(2, 14).isoformat()
        resp = self.client.post(_reschedule_url(appt_id), {"start_time": new_start}, format="json")
        self.assertEqual(resp.status_code, 200, resp.data)
        appt = Appointment.objects.get(pk=appt_id)
        self.assertEqual(timezone.localtime(appt.start_time).hour, 14)
        self.assertTrue(
            PortalScheduleRequest.objects.filter(appointment=appt, action="reschedule").exists()
        )

    def test_patient_cancels_own_appointment(self):
        start = self._first_slot_iso()
        booked = self.client.post(
            BOOK_URL, {"professional": str(self.md.pk), "start_time": start}, format="json"
        )
        appt_id = booked.data["id"]
        resp = self.client.post(_cancel_url(appt_id), {"reason": "Imprevisto"}, format="json")
        self.assertEqual(resp.status_code, 200, resp.data)
        appt = Appointment.objects.get(pk=appt_id)
        self.assertEqual(appt.status, "cancelled")
        self.assertEqual(appt.cancelled_by_id, self.patient_user.pk)
        self.assertTrue(
            PortalScheduleRequest.objects.filter(appointment=appt, action="cancel").exists()
        )

    # ── guards ───────────────────────────────────────────────────────────────

    def test_cannot_book_unavailable_slot(self):
        # 05:00 local is before working hours → OUTSIDE_AVAILABILITY.
        start = self._local_dt(1, 5).isoformat()
        resp = self.client.post(
            BOOK_URL, {"professional": str(self.md.pk), "start_time": start}, format="json"
        )
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertFalse(Appointment.objects.filter(patient=self.patient).exists())

    def test_cannot_reschedule_other_patients_appointment(self):
        other_appt = Appointment.objects.create(
            patient=self.other_patient,
            professional=self.md,
            start_time=self._local_dt(1, 9),
            end_time=self._local_dt(1, 9) + timedelta(minutes=30),
            status="scheduled",
        )
        new_start = self._local_dt(2, 15).isoformat()
        resp = self.client.post(
            _reschedule_url(other_appt.pk), {"start_time": new_start}, format="json"
        )
        self.assertEqual(resp.status_code, 404)
        other_appt.refresh_from_db()
        self.assertEqual(other_appt.status, "scheduled")

    def test_cannot_cancel_other_patients_appointment(self):
        other_appt = Appointment.objects.create(
            patient=self.other_patient,
            professional=self.md,
            start_time=self._local_dt(1, 11),
            end_time=self._local_dt(1, 11) + timedelta(minutes=30),
            status="scheduled",
        )
        resp = self.client.post(_cancel_url(other_appt.pk), {}, format="json")
        self.assertEqual(resp.status_code, 404)
        other_appt.refresh_from_db()
        self.assertEqual(other_appt.status, "scheduled")

    def test_booking_requires_lgpd_consent(self):
        self.consent.revoked_at = timezone.now()
        self.consent.save(update_fields=["revoked_at"])
        start = self._first_slot_iso()
        resp = self.client.post(
            BOOK_URL, {"professional": str(self.md.pk), "start_time": start}, format="json"
        )
        self.assertEqual(resp.status_code, 403, resp.data)
