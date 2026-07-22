from datetime import date, timedelta

from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import AuditLog, Role, User
from apps.hr.models import Employee, OccupationalHealthExam, TimeEntry
from apps.hr.services import AttendanceService
from apps.test_utils import TenantTestCase


class HROperationsTests(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.role = Role.objects.create(name="hr_ops", permissions=["hr.manage"])
        self.admin = User.objects.create_user(
            email="rh@hospital.test", password="secret-pass", full_name="Gestora RH", role=self.role
        )
        employee_user = User.objects.create_user(
            email="worker@hospital.test", password="secret-pass", full_name="Trabalhador"
        )
        self.employee = Employee.objects.create(
            user=employee_user, hire_date=date(2026, 1, 1), contract_type="clt"
        )
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain

    def test_attendance_is_sequenced_idempotent_and_audited(self):
        occurred_at = timezone.now()
        first, created = AttendanceService.record(
            employee=self.employee,
            actor=self.employee.user,
            event_type="in",
            occurred_at=occurred_at,
            source="device",
            external_id="clock-42",
        )
        replay, replay_created = AttendanceService.record(
            employee=self.employee,
            actor=self.employee.user,
            event_type="in",
            occurred_at=occurred_at,
            source="device",
            external_id="clock-42",
        )
        exit_entry, _ = AttendanceService.record(
            employee=self.employee,
            actor=self.employee.user,
            event_type="out",
            occurred_at=occurred_at + timedelta(hours=8),
        )

        self.assertTrue(created)
        self.assertFalse(replay_created)
        self.assertEqual(replay.pk, first.pk)
        self.assertEqual(TimeEntry.objects.count(), 2)
        self.assertEqual(exit_entry.event_type, "out")
        self.assertEqual(
            AuditLog.objects.filter(
                action="attendance_recorded", resource_id=str(first.id)
            ).count(),
            1,
        )

    def test_employee_cannot_clock_for_someone_else(self):
        other_user = User.objects.create_user(
            email="other@hospital.test", password="secret-pass", full_name="Outro"
        )
        other = Employee.objects.create(
            user=other_user, hire_date=date(2026, 1, 1), contract_type="clt"
        )
        self.client.force_authenticate(self.employee.user)
        response = self.client.post(
            "/api/v1/hr/time-entries/",
            {
                "employee": str(other.id),
                "event_type": "in",
                "occurred_at": timezone.now().isoformat(),
                "source": "web",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_hr_can_record_aso_with_audit_trail(self):
        self.client.force_authenticate(self.admin)
        response = self.client.post(
            "/api/v1/hr/occupational-health-exams/",
            {
                "employee": str(self.employee.id),
                "exam_type": "periodic",
                "performed_on": "2026-07-22",
                "expires_on": "2027-07-22",
                "result": "fit",
                "provider_name": "Clínica Ocupacional",
                "certificate_reference": "ASO-2026-1",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        exam = OccupationalHealthExam.objects.get()
        self.assertEqual(exam.recorded_by, self.admin)
        self.assertTrue(
            AuditLog.objects.filter(
                action="occupational_health_exam_recorded", resource_id=str(exam.id)
            ).exists()
        )
