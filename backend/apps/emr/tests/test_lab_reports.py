import base64
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import Role, User
from apps.emr.models import LabOrder, LabOrderItem, LabTest, Patient
from apps.signatures.models import LabReportArtifact
from apps.test_utils import TenantTestCase


class LabReportViewsTest(TenantTestCase):
    def setUp(self):
        role = Role.objects.create(name="lab_reporter", permissions=["emr.read", "emr.write"])
        self.user = User.objects.create_user(email="report@test.com", password="pw", role=role)
        self.patient = Patient.objects.create(
            full_name="Paciente", birth_date="1990-01-01", gender="F", cpf="53333333333"
        )
        test = LabTest.objects.create(code="GLI", name="Glicose")
        self.order = LabOrder.objects.create(
            patient=self.patient,
            requested_by=self.user,
            status=LabOrder.Status.COMPLETED,
            completed_at=timezone.now(),
        )
        LabOrderItem.objects.create(
            order=self.order,
            test=test,
            test_name=test.name,
            result_value="90",
            resulted_at=timezone.now(),
            validated_at=timezone.now(),
            validated_by=self.user,
        )
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        self.client.force_authenticate(self.user)

    @patch("apps.emr.views_lab_report.render_lab_report_pdf", return_value=b"%PDF-report")
    @patch("apps.emr.views_lab_report.ICPBrasilSigner.sign")
    def test_completed_report_is_signed_stored_and_downloadable(self, signer, _render):
        signer.return_value = SimpleNamespace(
            signature=b"signed",
            algorithm="SHA256withRSA",
            document_hash_hex="a" * 64,
            cert_subject="CN=Doctor",
            cert_issuer="CN=CA",
            cert_serial_hex="01",
            cert_not_valid_before=timezone.now(),
            cert_not_valid_after=timezone.now() + timedelta(days=1),
            is_icp_brasil=True,
        )
        response = self.client.post(
            f"/api/v1/lab-orders/{self.order.id}/report/sign/",
            {"pkcs12_b64": base64.b64encode(b"pfx").decode(), "pkcs12_password": "pw"},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        artifact = LabReportArtifact.objects.get(order=self.order)
        self.assertEqual(bytes(artifact.pdf), b"%PDF-report")
        self.assertEqual(artifact.signature.document_hash_hex, "a" * 64)
        pdf = self.client.get(f"/api/v1/lab-orders/{self.order.id}/report/pdf/")
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(pdf.content, b"%PDF-report")
        self.assertEqual(pdf["X-Document-SHA256"], "a" * 64)

    def test_draft_report_cannot_be_released(self):
        self.order.status = LabOrder.Status.COLLECTED
        self.order.save(update_fields=["status"])
        response = self.client.post(
            f"/api/v1/lab-orders/{self.order.id}/report/sign/",
            {"pkcs12_b64": base64.b64encode(b"pfx").decode()},
            format="json",
        )
        self.assertEqual(response.status_code, 409)
