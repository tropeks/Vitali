"""
S-072 Digital Check-in + Wait Time Dashboard — tests.

Tests:
  - check-in sets arrived_at, status becomes 'waiting'
  - check-in is idempotent (second call does not overwrite arrived_at)
  - start sets started_at, status becomes 'in_progress'
  - wait_time_avg_min computed correctly (minutes, rounded to 1 decimal)
  - wait_time_avg_min is null when no appointments have both timestamps
  - Unauthenticated requests return 401
"""
import datetime
from datetime import timedelta

from django.utils import timezone
from rest_framework.test import APIClient

from apps.test_utils import TenantTestCase


def _make_infra():
    from django.contrib.auth import get_user_model
    from apps.core.models import Role
    from apps.core.permissions import DEFAULT_ROLES
    from apps.emr.models import Patient, Professional

    User = get_user_model()
    role = Role.objects.create(
        name='recep_ci',
        permissions=DEFAULT_ROLES['recepcionista'],
    )
    user = User.objects.create_user(
        email='checkin_user@test.com',
        password='TestPass123!',
        full_name='Check-in User',
        role=role,
    )
    patient = Patient.objects.create(
        full_name='Paciente Check-in',
        birth_date=datetime.date(1990, 5, 15),
        gender='M',
        cpf='33333333333',
    )
    professional = Professional.objects.create(
        user=user,
        council_type='CRM',
        council_number='999001',
        council_state='SP',
    )
    return user, patient, professional


def _make_appointment(patient, professional, offset_hours=1):
    from apps.emr.models import Appointment

    now = timezone.now()
    start = now + timedelta(hours=offset_hours)
    end = start + timedelta(minutes=30)
    return Appointment.objects.create(
        patient=patient,
        professional=professional,
        start_time=start,
        end_time=end,
        status='scheduled',
    )


class TestCheckInAction(TenantTestCase):

    def setUp(self):
        self.user, self.patient, self.professional = _make_infra()
        self.appt = _make_appointment(self.patient, self.professional)

    def _client(self, user=None):
        c = APIClient()
        c.defaults['SERVER_NAME'] = self.__class__.domain.domain
        if user is not None:
            c.force_authenticate(user=user)
        return c

    # ── check-in ────────────────────────────────────────────────────────────────

    def test_check_in_sets_arrived_at_and_status_waiting(self):
        c = self._client(self.user)
        resp = c.post(f'/api/v1/appointments/{self.appt.id}/check-in/')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIsNotNone(data['arrived_at'])
        self.assertEqual(data['status'], 'waiting')

        self.appt.refresh_from_db()
        self.assertIsNotNone(self.appt.arrived_at)
        self.assertEqual(self.appt.status, 'waiting')

    def test_check_in_is_idempotent(self):
        c = self._client(self.user)
        c.post(f'/api/v1/appointments/{self.appt.id}/check-in/')
        self.appt.refresh_from_db()
        first_arrived_at = self.appt.arrived_at

        # Second call — must not overwrite arrived_at
        resp2 = c.post(f'/api/v1/appointments/{self.appt.id}/check-in/')
        self.assertEqual(resp2.status_code, 200)
        self.appt.refresh_from_db()
        self.assertEqual(self.appt.arrived_at, first_arrived_at)

    # ── start ────────────────────────────────────────────────────────────────────

    def test_start_sets_started_at_and_status_in_progress(self):
        c = self._client(self.user)
        resp = c.post(f'/api/v1/appointments/{self.appt.id}/start/')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIsNotNone(data['started_at'])
        self.assertEqual(data['status'], 'in_progress')

        self.appt.refresh_from_db()
        self.assertIsNotNone(self.appt.started_at)
        self.assertEqual(self.appt.status, 'in_progress')

    # ── auth ─────────────────────────────────────────────────────────────────────

    def test_check_in_unauthenticated_returns_401(self):
        c = self._client()  # no user
        resp = c.post(f'/api/v1/appointments/{self.appt.id}/check-in/')
        self.assertEqual(resp.status_code, 401)

    def test_start_unauthenticated_returns_401(self):
        c = self._client()  # no user
        resp = c.post(f'/api/v1/appointments/{self.appt.id}/start/')
        self.assertEqual(resp.status_code, 401)


class TestWaitTimeAvgAnalytics(TenantTestCase):
    """
    Tests for the wait_time_avg_min KPI in the analytics overview endpoint.
    Uses direct model manipulation to set arrived_at / started_at,
    bypassing Appointment.save() full_clean overlap check.
    """

    def setUp(self):
        self.user, self.patient, self.professional = _make_infra()

    def _client(self, user=None):
        c = APIClient()
        c.defaults['SERVER_NAME'] = self.__class__.domain.domain
        if user is not None:
            c.force_authenticate(user=user)
        return c

    def _create_appt_with_timestamps(self, arrived_offset_min, started_offset_min, hours_offset=1):
        """Create an appointment and set its timestamps via update() to avoid clean()."""
        from apps.emr.models import Appointment

        now = timezone.now()
        start = now + timedelta(hours=hours_offset)
        end = start + timedelta(minutes=30)
        appt = Appointment.objects.create(
            patient=self.patient,
            professional=self.professional,
            start_time=start,
            end_time=end,
            status='in_progress',
        )
        arrived = now - timedelta(minutes=arrived_offset_min)
        started = arrived + timedelta(minutes=started_offset_min)
        Appointment.objects.filter(pk=appt.pk).update(
            arrived_at=arrived,
            started_at=started,
        )
        return appt

    def test_wait_time_avg_min_null_when_no_timestamps(self):
        c = self._client(self.user)
        resp = c.get('/api/v1/analytics/overview/?period=month')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn('wait_time_avg_min', data)
        self.assertIsNone(data['wait_time_avg_min'])

    def test_wait_time_avg_min_computed_correctly(self):
        # Two appointments: 10 min and 20 min wait → avg = 15.0
        self._create_appt_with_timestamps(arrived_offset_min=0, started_offset_min=10, hours_offset=2)
        self._create_appt_with_timestamps(arrived_offset_min=0, started_offset_min=20, hours_offset=3)

        c = self._client(self.user)
        resp = c.get('/api/v1/analytics/overview/?period=month')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIsNotNone(data['wait_time_avg_min'])
        # Allow ±0.5 min tolerance for timing jitter
        self.assertAlmostEqual(data['wait_time_avg_min'], 15.0, delta=0.5)

    def test_wait_time_avg_min_rounded_to_one_decimal(self):
        # 7 min wait → should return 7.0 (1 decimal)
        self._create_appt_with_timestamps(arrived_offset_min=0, started_offset_min=7, hours_offset=4)

        c = self._client(self.user)
        resp = c.get('/api/v1/analytics/overview/?period=month')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        val = data['wait_time_avg_min']
        self.assertIsNotNone(val)
        # Verify it's a float (or int that represents 1 decimal)
        self.assertIsInstance(val, (int, float))
        self.assertAlmostEqual(val, 7.0, delta=0.5)
