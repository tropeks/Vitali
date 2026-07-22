from datetime import date

from django.db import connection
from rest_framework.test import APIClient

from apps.core.models import AuditLog, Role, User
from apps.emr.models import DuplicatePatientCandidate, Patient, PatientIdentifier
from apps.test_utils import TenantTestCase


class MPITests(TenantTestCase):
    def setUp(self):
        self.role = Role.objects.create(name="mpi-reviewer", permissions=[])
        self.user = User.objects.create_user(
            email="mpi@test.com",
            password="TestPass123!",
            full_name="MPI Reviewer",
            role=self.role,
        )
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        self.client.force_authenticate(self.user)
        self.patient_a = self.make_patient("Maria da Silva", "123.456.789-00")
        self.patient_b = self.make_patient("Maria da Silva", "987.654.321-00")

    def make_patient(self, name, cpf):
        return Patient.objects.create(
            full_name=name,
            cpf=cpf,
            birth_date=date(1990, 5, 14),
            gender="F",
        )

    def grant(self, *permissions):
        self.role.permissions = list(permissions)
        self.role.save(update_fields=["permissions"])
        self.user.refresh_from_db()

    def test_identifier_is_encrypted_and_never_returned(self):
        self.grant("mpi.write")
        response = self.client.post(
            "/api/v1/patient-identifiers/",
            {
                "patient": str(self.patient_a.id),
                "system": "urn:br:cns",
                "issuer": "DATASUS",
                "value": "174598435280018",
                "use": "official",
            },
        )
        self.assertEqual(response.status_code, 201)
        self.assertNotIn("value", response.data)

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT value, value_digest FROM emr_patientidentifier WHERE id = %s",
                [response.data["id"]],
            )
            encrypted_value, digest = cursor.fetchone()
        self.assertNotIn("174598435280018", encrypted_value)
        self.assertNotIn("174598435280018", digest)

    def test_normalized_identifier_is_unique_inside_tenant(self):
        PatientIdentifier.objects.create(
            patient=self.patient_a,
            system="urn:br:cpf",
            issuer="rfb",
            value="123.456.789-00",
        )
        self.grant("mpi.write")
        response = self.client.post(
            "/api/v1/patient-identifiers/",
            {
                "patient": str(self.patient_b.id),
                "system": "URN:BR:CPF",
                "issuer": "RFB",
                "value": "12345678900",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("value", response.data)

    def test_detection_creates_review_only_candidate(self):
        self.grant("mpi.review")
        response = self.client.post(
            "/api/v1/mpi/duplicate-candidates/detect/",
            {"patient": str(self.patient_a.id)},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        candidate = DuplicatePatientCandidate.objects.get()
        self.assertEqual(candidate.reasons, ["name_and_birth_date"])
        self.patient_a.refresh_from_db()
        self.patient_b.refresh_from_db()
        self.assertTrue(self.patient_a.is_active)
        self.assertTrue(self.patient_b.is_active)

    def test_review_requires_permission_and_is_audited(self):
        candidate = DuplicatePatientCandidate.objects.create(
            patient_a=self.patient_a,
            patient_b=self.patient_b,
            score="0.8000",
            reasons=["name_and_birth_date"],
        )
        denied = self.client.post(
            f"/api/v1/mpi/duplicate-candidates/{candidate.id}/dismiss/", {"notes": "Homônimas"}
        )
        self.assertEqual(denied.status_code, 403)

        self.grant("mpi.review")
        allowed = self.client.post(
            f"/api/v1/mpi/duplicate-candidates/{candidate.id}/dismiss/", {"notes": "Homônimas"}
        )
        self.assertEqual(allowed.status_code, 200)
        candidate.refresh_from_db()
        self.assertEqual(candidate.status, "dismissed")
        self.assertEqual(candidate.reviewed_by, self.user)
        self.assertTrue(
            AuditLog.objects.filter(
                action="mpi_duplicate_reviewed", resource_id=str(candidate.id)
            ).exists()
        )
