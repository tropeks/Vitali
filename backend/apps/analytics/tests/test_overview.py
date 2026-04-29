"""
Clinic Ops / Overview API tests — S-068.

Exercises OverviewView with ?period=today|week|month and the non-billing
permission relaxation on AppointmentsByStatusView, PatientsByMonthView,
and WaitingTimeView.

Run: python manage.py test apps.analytics.tests.test_overview
"""

import datetime

from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import Role, User
from apps.emr.models import Appointment, Patient, Professional
from apps.test_utils import TenantTestCase


class OverviewBaseCase(TenantTestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain

        role = Role.objects.create(
            name="recepcao",
            permissions=[],
            is_system=True,
        )
        self.user = User.objects.create_user(
            email="recepcao@ops.test",
            full_name="Recepção Ops",
            password="Str0ng!Pass#2024",
            role=role,
        )
        prof_user = User.objects.create_user(
            email="dr@ops.test",
            full_name="Dr. Ops",
            password="Str0ng!Pass#2024",
            role=role,
        )
        self.professional = Professional.objects.create(
            user=prof_user,
            council_type="CRM",
            council_number="99999",
            council_state="SP",
        )
        self.patient = Patient.objects.create(
            full_name="Paciente Ops",
            cpf="222.222.222-22",
            birth_date=datetime.date(1985, 3, 10),
            gender="F",
        )
        self.client.force_authenticate(user=self.user)

    def _make_appt(self, *, status: str):
        """Create an Appointment today in a unique time slot with the given status."""
        # Use localtime so 08:00 is anchored to TIME_ZONE; timezone.now() returns UTC,
        # and after ~21:00 BRT its date is already "tomorrow" local, which mismatches
        # OverviewView's start_time__date=today filter.
        base = timezone.localtime().replace(hour=8, minute=0, second=0, microsecond=0)
        offset_minutes = Appointment.objects.count() * 45
        start = base + datetime.timedelta(minutes=offset_minutes)
        return Appointment.objects.create(
            patient=self.patient,
            professional=self.professional,
            start_time=start,
            end_time=start + datetime.timedelta(minutes=30),
            status=status,
        )


class OverviewAppointmentCountsTests(OverviewBaseCase):
    def test_returns_confirmed_and_no_show_counts(self):
        self._make_appt(status="confirmed")
        self._make_appt(status="confirmed")
        self._make_appt(status="no_show")
        self._make_appt(status="completed")
        self._make_appt(status="cancelled")

        resp = self.client.get("/api/v1/analytics/overview/?period=today")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        self.assertEqual(data["appointments_total"], 5)
        self.assertEqual(data["appointments_confirmed"], 2)
        self.assertEqual(data["appointments_no_show"], 1)
        self.assertEqual(data["appointments_completed"], 1)
        self.assertEqual(data["appointments_cancelled"], 1)

    def test_no_show_rate_uses_confirmed_denominator(self):
        self._make_appt(status="confirmed")
        self._make_appt(status="confirmed")
        self._make_appt(status="no_show")

        resp = self.client.get("/api/v1/analytics/overview/?period=today")
        data = resp.json()
        self.assertEqual(data["appointments_confirmed"], 2)
        self.assertEqual(data["appointments_no_show"], 1)
        self.assertEqual(data["no_show_rate"], 50.0)

    def test_no_show_rate_zero_when_no_confirmed(self):
        self._make_appt(status="no_show")
        resp = self.client.get("/api/v1/analytics/overview/?period=today")
        data = resp.json()
        self.assertEqual(data["no_show_rate"], 0.0)

    def test_empty_state_returns_zeros(self):
        resp = self.client.get("/api/v1/analytics/overview/?period=today")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["appointments_total"], 0)
        self.assertEqual(data["appointments_confirmed"], 0)
        self.assertEqual(data["appointments_no_show"], 0)
        self.assertEqual(data["no_show_rate"], 0.0)
        self.assertEqual(data["cancellation_rate"], 0.0)

    def test_invalid_period_falls_back_to_month(self):
        resp = self.client.get("/api/v1/analytics/overview/?period=garbage")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["period"], "month")


class AnalyticsPermissionRelaxationTests(OverviewBaseCase):
    """CP-1: dashboard analytics endpoints must be reachable without the
    billing module — pilots without billing still need their KPIs."""

    def test_appointments_by_status_reachable_without_billing_module(self):
        resp = self.client.get("/api/v1/analytics/appointments-by-status/")
        self.assertEqual(resp.status_code, 200)

    def test_patients_by_month_reachable_without_billing_module(self):
        resp = self.client.get("/api/v1/analytics/patients-by-month/")
        self.assertEqual(resp.status_code, 200)

    def test_waiting_time_reachable_without_billing_module(self):
        resp = self.client.get("/api/v1/analytics/waiting-time/")
        self.assertEqual(resp.status_code, 200)

    def test_unauthenticated_returns_401(self):
        self.client.force_authenticate(user=None)
        resp = self.client.get("/api/v1/analytics/appointments-by-status/")
        self.assertEqual(resp.status_code, 401)
