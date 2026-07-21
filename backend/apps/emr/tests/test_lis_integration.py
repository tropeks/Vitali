from django.test import override_settings
from rest_framework.test import APIClient

from apps.core.models import AuditLog, Role, User
from apps.emr.models import LabIntegrationMessage, LabOrder, LabOrderItem, LabTest, Patient
from apps.test_utils import TenantTestCase


@override_settings(LIS_INBOUND_SECRET="lis-test-secret")
class LISIntegrationTests(TenantTestCase):
    def setUp(self):
        role = Role.objects.create(name="lis_operator", permissions=["emr.read", "emr.write"])
        self.user = User.objects.create_user(email="lis@example.com", password="pw", role=role)
        self.patient = Patient.objects.create(
            full_name="Paciente LIS", birth_date="1990-01-01", gender="F", cpf="53333333333"
        )
        self.test = LabTest.objects.create(code="HB", name="Hemoglobina", loinc_code="718-7")
        self.order = LabOrder.objects.create(
            patient=self.patient,
            requested_by=self.user,
            accession_number="ACC-001",
            status=LabOrder.Status.COLLECTED,
        )
        self.item = LabOrderItem.objects.create(
            order=self.order,
            test=self.test,
            test_name=self.test.name,
            loinc_code=self.test.loinc_code,
        )

    def api_client(self, *, authenticated=False, secret="lis-test-secret"):
        client = APIClient()
        client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        if authenticated:
            client.force_authenticate(self.user)
        if secret is not None:
            client.credentials(
                HTTP_X_VITALI_LIS_SECRET=secret, HTTP_X_VITALI_LIS_SOURCE="analyzer-1"
            )
        return client

    def payload(self, **changes):
        payload = {
            "message_id": "MSG-1",
            "accession_number": "ACC-001",
            "results": [{"code": "718-7", "value": "13.2", "unit": "g/dL"}],
        }
        payload.update(changes)
        return {"format": "canonical", "payload": payload}

    def test_inbound_requires_configured_constant_time_secret(self):
        response = self.api_client(secret="wrong").post(
            "/api/v1/lab-integrations/inbound/", self.payload(), format="json"
        )
        self.assertEqual(response.status_code, 401)
        self.assertFalse(LabIntegrationMessage.objects.exists())

    def test_inbound_is_idempotent_and_detects_message_id_collision(self):
        client = self.api_client()
        first = client.post("/api/v1/lab-integrations/inbound/", self.payload(), format="json")
        duplicate = client.post("/api/v1/lab-integrations/inbound/", self.payload(), format="json")
        collision = client.post(
            "/api/v1/lab-integrations/inbound/",
            self.payload(results=[{"code": "718-7", "value": "99"}]),
            format="json",
        )
        self.assertEqual(first.status_code, 202, first.content)
        self.assertEqual(duplicate.status_code, 200, duplicate.content)
        self.assertTrue(duplicate.data["duplicate"])
        self.assertEqual(collision.status_code, 409)
        self.assertEqual(LabIntegrationMessage.objects.count(), 1)

    def test_invalid_payload_is_rejected_and_audited_without_storage(self):
        response = self.api_client().post(
            "/api/v1/lab-integrations/inbound/",
            {"format": "canonical", "payload": {"message_id": "BAD"}},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(LabIntegrationMessage.objects.exists())
        self.assertTrue(AuditLog.objects.filter(action="lis_message_reject").exists())

    def test_hl7_oru_is_normalized_then_operator_applies_result(self):
        hl7 = (
            "MSH|^~\\&|LIS|LAB|VITALI|CLINIC|202607211200||ORU^R01|HL7-1|P|2.5.1\r"
            "OBR|1||ACC-001|718-7^Hemoglobina^LN\r"
            "OBX|1|NM|718-7^Hemoglobina^LN||13.4|g/dL|12-16|N\r"
        )
        received = self.api_client().post(
            "/api/v1/lab-integrations/inbound/",
            {"format": "hl7_v2", "payload": hl7},
            format="json",
        )
        self.assertEqual(received.status_code, 202, received.content)
        message = LabIntegrationMessage.objects.get()
        applied = self.api_client(authenticated=True, secret=None).post(
            f"/api/v1/lab-integrations/{message.id}/apply/", {}, format="json"
        )
        self.assertEqual(applied.status_code, 200, applied.content)
        self.item.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(self.item.result_value, "13.4")
        self.assertEqual(self.order.status, LabOrder.Status.IN_PROGRESS)
        self.assertEqual(message.canonical_payload["accession_number"], "ACC-001")

    def test_apply_rejects_unknown_code_atomically(self):
        received = self.api_client().post(
            "/api/v1/lab-integrations/inbound/",
            self.payload(results=[{"code": "UNKNOWN", "value": "1"}]),
            format="json",
        )
        message = LabIntegrationMessage.objects.get(pk=received.data["id"])
        applied = self.api_client(authenticated=True, secret=None).post(
            f"/api/v1/lab-integrations/{message.id}/apply/", {}, format="json"
        )
        self.assertEqual(applied.status_code, 409)
        message.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual(message.status, LabIntegrationMessage.Status.REJECTED)
        self.assertEqual(self.item.result_value, "")

    def test_orm_export_requires_rbac_and_contains_no_patient_name(self):
        response = self.api_client(authenticated=True, secret=None).get(
            f"/api/v1/lab-orders/{self.order.id}/orm/"
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIn("ORM^O01", response.data["payload"])
        self.assertIn("ACC-001", response.data["payload"])
        self.assertNotIn(self.patient.full_name, response.data["payload"])
