from datetime import timedelta

from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import FeatureFlag, Role, User
from apps.emr.models import LabOrder, LabOrderItem, LabTest, Patient
from apps.patient_portal.models import PatientPortalAccess
from apps.signatures.models import DigitalSignature, LabReportArtifact
from apps.test_utils import TenantTestCase


class PortalLabResultsTest(TenantTestCase):
    def setUp(self):
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant, module_key="patient_portal", defaults={"is_enabled": True}
        )
        role = Role.objects.create(name="portal_lab", permissions=["portal.self_access"])
        self.user = User.objects.create_user(email="patient-lab@test.com", password="pw", role=role)
        self.signer = User.objects.create_user(email="signer-lab@test.com", password="pw")
        self.patient = Patient.objects.create(
            full_name="Paciente", birth_date="1990-01-01", gender="F", cpf="54444444444"
        )
        self.other = Patient.objects.create(
            full_name="Outro", birth_date="1991-01-01", gender="M", cpf="55555555555"
        )
        access = PatientPortalAccess.objects.create(user=self.user, patient=self.patient)
        access.status = PatientPortalAccess.STATUS_ACTIVE
        access.save(update_fields=["status"])
        test = LabTest.objects.create(code="PCR", name="PCR")
        self.own = self._released_order(self.patient, test, "own")
        self._released_order(self.other, test, "other")
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        self.client.force_authenticate(self.user)

    def _released_order(self, patient, test, suffix):
        order = LabOrder.objects.create(
            patient=patient,
            requested_by=self.signer,
            status=LabOrder.Status.COMPLETED,
            completed_at=timezone.now(),
        )
        LabOrderItem.objects.create(
            order=order,
            test=test,
            test_name=test.name,
            result_value=suffix,
            resulted_at=timezone.now(),
            validated_at=timezone.now(),
            validated_by=self.signer,
        )
        signature = DigitalSignature.objects.create(
            document_type="custom",
            document_id=str(order.id),
            signer=self.signer,
            signature=b"sig",
            document_hash_hex=suffix.ljust(64, "0"),
            cert_subject="CN=X",
            cert_serial_hex="01",
            cert_not_valid_after=timezone.now() + timedelta(days=1),
        )
        LabReportArtifact.objects.create(
            order=order, signature=signature, pdf=b"%PDF", released_by=self.signer
        )
        return order

    def test_lists_only_own_released_results_and_download_is_scoped(self):
        response = self.client.get("/api/v1/portal/me/lab-results/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["id"] for row in response.data], [str(self.own.id)])
        own_pdf = self.client.get(f"/api/v1/portal/me/lab-results/{self.own.id}/report/")
        self.assertEqual(own_pdf.status_code, 200)
        other = LabOrder.objects.exclude(pk=self.own.pk).get()
        self.assertEqual(
            self.client.get(f"/api/v1/portal/me/lab-results/{other.id}/report/").status_code, 404
        )
