"""Laboratory workflow invariants, permissions, and API contract."""

from django.db import IntegrityError, transaction
from rest_framework.test import APIClient

from apps.core.models import Role, User
from apps.emr.models import Encounter, LabOrder, LabOrderItem, LabTest, Patient, Professional
from apps.test_utils import TenantTestCase


class LaboratoryTestCase(TenantTestCase):
    def setUp(self):
        self.writer_role = Role.objects.create(
            name="lab_writer", permissions=["emr.read", "emr.write"]
        )
        self.reader_role = Role.objects.create(name="lab_reader", permissions=["emr.read"])
        self.writer = User.objects.create_user(
            email="lab-writer@example.com", password="pw", role=self.writer_role
        )
        self.reader = User.objects.create_user(
            email="lab-reader@example.com", password="pw", role=self.reader_role
        )
        self.professional = Professional.objects.create(
            user=self.writer,
            council_type="CRM",
            council_number="LAB-1",
            council_state="SP",
        )
        self.patient = Patient.objects.create(
            full_name="Paciente Laboratório",
            birth_date="1990-01-01",
            gender="F",
            cpf="51111111111",
        )
        self.other_patient = Patient.objects.create(
            full_name="Outro Paciente",
            birth_date="1991-01-01",
            gender="M",
            cpf="52222222222",
        )
        self.encounter = Encounter.objects.create(
            patient=self.patient, professional=self.professional
        )
        self.other_encounter = Encounter.objects.create(
            patient=self.other_patient, professional=self.professional
        )
        self.test = LabTest.objects.create(
            code="HB", name="Hemoglobina", unit="g/dL", reference_range="12–16"
        )

    def client_for(self, user):
        client = APIClient()
        client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        client.force_authenticate(user=user)
        return client

    def create_order(self, *, extra_tests=()):
        response = self.client_for(self.writer).post(
            "/api/v1/lab-orders/",
            {
                "patient": str(self.patient.id),
                "encounter": str(self.encounter.id),
                "clinical_indication": "Controle",
                "test_ids": [str(self.test.id), *(str(item.id) for item in extra_tests)],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        return LabOrder.objects.get(pk=response.data["id"])

    def post_action(self, user, path, data=None):
        return self.client_for(user).post(path, data or {}, format="json")

    def test_create_snapshots_catalog_and_assigns_requesting_user(self):
        order = self.create_order()
        item = order.items.get()
        self.assertEqual(order.requested_by, self.writer)
        self.assertEqual(order.status, LabOrder.Status.ORDERED)
        self.assertEqual(item.test_name, "Hemoglobina")
        self.assertEqual(item.unit, "g/dL")
        self.assertEqual(item.reference_range, "12–16")

    def test_create_snapshots_structured_catalog_metadata(self):
        self.test.category = LabTest.Category.HEMATOLOGY
        self.test.result_type = LabTest.ResultType.PANEL
        self.test.method = "Impedância"
        self.test.loinc_code = "58410-2"
        self.test.specimen_type = "Sangue total"
        self.test.components = [{"code": "RBC", "name": "Hemácias"}]
        self.test.reference_ranges = [{"sex": "F", "lower": "12", "upper": "16"}]
        self.test.save()
        item = self.create_order().items.get()
        self.assertEqual(item.category, LabTest.Category.HEMATOLOGY)
        self.assertEqual(item.result_type, LabTest.ResultType.PANEL)
        self.assertEqual(item.loinc_code, "58410-2")
        self.assertEqual(item.components[0]["code"], "RBC")
        self.assertEqual(item.reference_ranges[0]["sex"], "F")

    def test_catalog_validates_panel_and_reference_range_structure(self):
        client = self.client_for(self.writer)
        missing_components = client.post(
            "/api/v1/lab-tests/",
            {"code": "PANEL", "name": "Painel", "result_type": "panel"},
            format="json",
        )
        bad_range = client.post(
            "/api/v1/lab-tests/",
            {
                "code": "RANGE",
                "name": "Faixa",
                "reference_ranges": [{"diagnosis": "qualquer", "lower": 1}],
            },
            format="json",
        )
        self.assertEqual(missing_components.status_code, 400)
        self.assertEqual(bad_range.status_code, 400)

    def test_collect_records_structured_specimen_and_collector(self):
        order = self.create_order()
        response = self.post_action(
            self.writer,
            f"/api/v1/lab-orders/{order.id}/collect/",
            {
                "accession_number": "ACC-100",
                "collection_notes": "Jejum informado",
                "specimen_details": [
                    {"identifier": "TUBE-1", "type": "blood", "container": "EDTA"}
                ],
            },
        )
        self.assertEqual(response.status_code, 200, response.content)
        order.refresh_from_db()
        self.assertEqual(order.collected_by, self.writer)
        self.assertEqual(order.accession_number, "ACC-100")
        self.assertEqual(order.specimen_details[0]["container"], "EDTA")

    def test_structured_panel_result_can_be_validated_without_text_value(self):
        self.test.result_type = LabTest.ResultType.PANEL
        self.test.components = [{"code": "HB", "name": "Hemoglobina"}]
        self.test.save()
        order = self.create_order()
        item = order.items.get()
        self.post_action(self.writer, f"/api/v1/lab-orders/{order.id}/collect/")
        result = self.post_action(
            self.writer,
            f"/api/v1/lab-orders/{order.id}/items/{item.id}/result/",
            {"result_data": {"components": [{"code": "HB", "value": "13.2"}]}},
        )
        self.assertEqual(result.status_code, 200, result.content)
        validated = self.post_action(
            self.writer, f"/api/v1/lab-orders/{order.id}/items/{item.id}/validate/"
        )
        self.assertEqual(validated.status_code, 200, validated.content)

    def test_microbiology_requires_structured_antibiogram(self):
        order = self.create_order()
        item = order.items.get()
        self.post_action(self.writer, f"/api/v1/lab-orders/{order.id}/collect/")
        invalid = self.post_action(
            self.writer,
            f"/api/v1/lab-orders/{order.id}/items/{item.id}/result/",
            {"microbiology": {"organisms": [{"name": "E. coli", "antibiogram": [{}]}]}},
        )
        valid = self.post_action(
            self.writer,
            f"/api/v1/lab-orders/{order.id}/items/{item.id}/result/",
            {
                "microbiology": {
                    "organisms": [
                        {
                            "name": "E. coli",
                            "antibiogram": [
                                {"antimicrobial": "Ciprofloxacino", "interpretation": "S"}
                            ],
                        }
                    ]
                }
            },
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(valid.status_code, 200, valid.content)

    def test_create_rejects_encounter_from_another_patient(self):
        response = self.client_for(self.writer).post(
            "/api/v1/lab-orders/",
            {
                "patient": str(self.patient.id),
                "encounter": str(self.other_encounter.id),
                "test_ids": [str(self.test.id)],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(LabOrder.objects.exists())

    def test_create_rejects_duplicate_tests_without_server_error(self):
        response = self.client_for(self.writer).post(
            "/api/v1/lab-orders/",
            {
                "patient": str(self.patient.id),
                "test_ids": [str(self.test.id), str(self.test.id)],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(LabOrder.objects.exists())

    def test_reader_can_read_but_cannot_mutate_catalog_or_orders(self):
        self.assertEqual(self.client_for(self.reader).get("/api/v1/lab-tests/").status_code, 200)
        create = self.client_for(self.reader).post(
            "/api/v1/lab-orders/",
            {"patient": str(self.patient.id), "test_ids": [str(self.test.id)]},
            format="json",
        )
        self.assertEqual(create.status_code, 403)
        catalog = self.client_for(self.reader).post(
            "/api/v1/lab-tests/", {"code": "CR", "name": "Creatinina"}, format="json"
        )
        self.assertEqual(catalog.status_code, 403)

    def test_patch_cannot_reassign_patient_or_encounter(self):
        order = self.create_order()
        response = self.client_for(self.writer).patch(
            f"/api/v1/lab-orders/{order.id}/",
            {"patient": str(self.other_patient.id)},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        order.refresh_from_db()
        self.assertEqual(order.patient, self.patient)

    def test_result_requires_collection(self):
        order = self.create_order()
        item = order.items.get()
        response = self.post_action(
            self.writer,
            f"/api/v1/lab-orders/{order.id}/items/{item.id}/result/",
            {"result_value": "13.2", "abnormal_flag": "normal"},
        )
        self.assertEqual(response.status_code, 409)
        item.refresh_from_db()
        self.assertIsNone(item.resulted_at)

    def test_result_rejects_empty_value(self):
        order = self.create_order()
        item = order.items.get()
        self.post_action(self.writer, f"/api/v1/lab-orders/{order.id}/collect/")
        response = self.post_action(
            self.writer,
            f"/api/v1/lab-orders/{order.id}/items/{item.id}/result/",
            {"result_value": "   ", "abnormal_flag": "normal"},
        )
        self.assertEqual(response.status_code, 400)
        item.refresh_from_db()
        self.assertIsNone(item.resulted_at)

    def test_happy_path_collect_result_validate_completes_order(self):
        order = self.create_order()
        item = order.items.get()
        collect = self.post_action(self.writer, f"/api/v1/lab-orders/{order.id}/collect/")
        self.assertEqual(collect.status_code, 200)
        result = self.post_action(
            self.writer,
            f"/api/v1/lab-orders/{order.id}/items/{item.id}/result/",
            {"result_value": " 13.2 ", "abnormal_flag": "normal"},
        )
        self.assertEqual(result.status_code, 200)
        validate = self.post_action(
            self.writer, f"/api/v1/lab-orders/{order.id}/items/{item.id}/validate/"
        )
        self.assertEqual(validate.status_code, 200)
        order.refresh_from_db()
        item.refresh_from_db()
        self.assertEqual(order.status, LabOrder.Status.COMPLETED)
        self.assertIsNotNone(order.completed_at)
        self.assertEqual(item.result_value, "13.2")
        self.assertEqual(item.validated_by, self.writer)

    def test_validated_item_cannot_be_overwritten_while_order_remains_open(self):
        second = LabTest.objects.create(code="CR", name="Creatinina", unit="mg/dL")
        order = self.create_order(extra_tests=(second,))
        first = order.items.get(test=self.test)
        self.post_action(self.writer, f"/api/v1/lab-orders/{order.id}/collect/")
        self.post_action(
            self.writer,
            f"/api/v1/lab-orders/{order.id}/items/{first.id}/result/",
            {"result_value": "13.2"},
        )
        self.post_action(self.writer, f"/api/v1/lab-orders/{order.id}/items/{first.id}/validate/")
        response = self.post_action(
            self.writer,
            f"/api/v1/lab-orders/{order.id}/items/{first.id}/result/",
            {"result_value": "99"},
        )
        self.assertEqual(response.status_code, 409)
        first.refresh_from_db()
        self.assertEqual(first.result_value, "13.2")

    def test_repeated_validation_and_cancellation_are_conflicts(self):
        order = self.create_order()
        item = order.items.get()
        self.post_action(self.writer, f"/api/v1/lab-orders/{order.id}/collect/")
        self.post_action(
            self.writer,
            f"/api/v1/lab-orders/{order.id}/items/{item.id}/result/",
            {"result_value": "13.2"},
        )
        self.post_action(self.writer, f"/api/v1/lab-orders/{order.id}/items/{item.id}/validate/")
        repeated = self.post_action(
            self.writer, f"/api/v1/lab-orders/{order.id}/items/{item.id}/validate/"
        )
        cancelled = self.post_action(self.writer, f"/api/v1/lab-orders/{order.id}/cancel/")
        self.assertEqual(repeated.status_code, 409)
        self.assertEqual(cancelled.status_code, 409)

    def test_completed_order_cannot_be_patched(self):
        order = self.create_order()
        item = order.items.get()
        self.post_action(self.writer, f"/api/v1/lab-orders/{order.id}/collect/")
        self.post_action(
            self.writer,
            f"/api/v1/lab-orders/{order.id}/items/{item.id}/result/",
            {"result_value": "13.2"},
        )
        self.post_action(self.writer, f"/api/v1/lab-orders/{order.id}/items/{item.id}/validate/")
        response = self.client_for(self.writer).patch(
            f"/api/v1/lab-orders/{order.id}/", {"notes": "alterado"}, format="json"
        )
        self.assertEqual(response.status_code, 400)

    def test_catalog_delete_is_soft_delete(self):
        response = self.client_for(self.writer).delete(f"/api/v1/lab-tests/{self.test.id}/")
        self.assertEqual(response.status_code, 204)
        self.test.refresh_from_db()
        self.assertFalse(self.test.active)

    def test_database_rejects_inconsistent_validation_metadata(self):
        order = LabOrder.objects.create(patient=self.patient, requested_by=self.writer)
        with self.assertRaises(IntegrityError), transaction.atomic():
            LabOrderItem.objects.create(
                order=order,
                test=self.test,
                test_name=self.test.name,
                validated_by=self.writer,
            )
