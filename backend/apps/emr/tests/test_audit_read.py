"""CFM Res. 1.821 — clinical record READ access must be audited (view_record)."""

import datetime

from rest_framework.test import APIRequestFactory, force_authenticate

from apps.test_utils import TenantTestCase


class TestAuditReadLogging(TenantTestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model

        from apps.emr.models import Patient

        User = get_user_model()
        # Superuser so HasPermission("emr.read") passes without role wiring.
        self.user = User.objects.create_user(
            email="auditor@clinic.test",
            password="TestPass123!",
            full_name="Auditor",
            is_staff=True,
            is_superuser=True,
        )
        self.patient = Patient.objects.create(
            full_name="Paciente Auditado",
            cpf="99999999901",
            birth_date=datetime.date(1990, 1, 1),
            gender="F",
        )

    def test_retrieve_patient_writes_view_record_audit(self):
        from apps.core.models import AuditLog
        from apps.emr.views import PatientViewSet

        request = APIRequestFactory().get(f"/api/v1/patients/{self.patient.id}/")
        force_authenticate(request, user=self.user)
        response = PatientViewSet.as_view({"get": "retrieve"})(request, pk=str(self.patient.id))

        self.assertEqual(response.status_code, 200)
        logs = AuditLog.objects.filter(
            action="view_record",
            resource_type="Patient",
            resource_id=str(self.patient.id),
        )
        self.assertEqual(logs.count(), 1)
        self.assertEqual(logs.first().user, self.user)

    def test_list_does_not_write_view_record_audit(self):
        from apps.core.models import AuditLog
        from apps.emr.views import PatientViewSet

        request = APIRequestFactory().get("/api/v1/patients/")
        force_authenticate(request, user=self.user)
        response = PatientViewSet.as_view({"get": "list"})(request)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(AuditLog.objects.filter(action="view_record").exists())
