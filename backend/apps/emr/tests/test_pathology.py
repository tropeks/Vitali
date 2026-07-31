"""AP1 — structured anatomic pathology report invariants and API."""

from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import CID10Code, CIDOMorphology, Role, User
from apps.emr.models import (
    Encounter,
    LabOrder,
    LabOrderItem,
    LabTest,
    PathologyReport,
    PathologySpecimen,
    Patient,
    Professional,
    SurgicalCase,
)
from apps.test_utils import TenantTestCase


class PathologyTestCase(TenantTestCase):
    def setUp(self):
        self.writer_role = Role.objects.create(
            name="path_writer", permissions=["emr.read", "emr.write"]
        )
        self.reader_role = Role.objects.create(name="path_reader", permissions=["emr.read"])
        self.writer = User.objects.create_user(
            email="path-writer@example.com", password="pw", role=self.writer_role
        )
        self.reader = User.objects.create_user(
            email="path-reader@example.com", password="pw", role=self.reader_role
        )
        self.professional = Professional.objects.create(
            user=self.writer,
            council_type="CRM",
            council_number="AP-1",
            council_state="SP",
        )
        self.patient = Patient.objects.create(
            full_name="Paciente Patologia",
            birth_date="1980-05-05",
            gender="F",
            cpf="52222222222",
        )
        self.encounter = Encounter.objects.create(
            patient=self.patient, professional=self.professional
        )
        self.test = LabTest.objects.create(
            code="ANAPAT",
            name="Exame anatomopatológico",
            category=LabTest.Category.PATHOLOGY,
        )
        self.order = LabOrder.objects.create(
            patient=self.patient, encounter=self.encounter, requested_by=self.writer
        )
        self.item = LabOrderItem.objects.create(
            order=self.order,
            test=self.test,
            test_name=self.test.name,
            category=LabTest.Category.PATHOLOGY,
            specimen_type="Peça cirúrgica",
        )

    def client_for(self, user):
        client = APIClient()
        client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        client.force_authenticate(user=user)
        return client

    # ── Model invariants ────────────────────────────────────────────────
    def test_one_report_per_order_item(self):
        PathologyReport.objects.create(order_item=self.item)
        with self.assertRaises(IntegrityError), transaction.atomic():
            PathologyReport.objects.create(order_item=self.item)

    def test_report_with_two_specimens_and_cid_o(self):
        report = PathologyReport.objects.create(
            order_item=self.item,
            report_number="AP-2026-0001",
            clinical_history="Nódulo mamário suspeito",
            macroscopy="Fragmento de 2,0 x 1,5 cm, pardo",
            microscopy="Proliferação epitelial atípica",
            diagnosis="Carcinoma ductal invasivo",
            cid_o_topography="C50.9",
            cid_o_morphology="8500/3",
            pathologist=self.professional,
        )
        PathologySpecimen.objects.create(
            report=report, label="A", site="Mama esquerda", blocks_count=3
        )
        PathologySpecimen.objects.create(
            report=report, label="B", site="Linfonodo axilar", blocks_count=2
        )
        self.assertEqual(self.item.pathology_report, report)
        self.assertEqual(report.specimens.count(), 2)
        self.assertEqual(report.cid_o_topography, "C50.9")
        self.assertEqual(report.cid_o_morphology, "8500/3")

    def test_status_flow_pending_to_final(self):
        report = PathologyReport.objects.create(order_item=self.item)
        self.assertEqual(report.status, PathologyReport.Status.PENDENTE)
        self.assertIsNone(report.reported_at)
        report.status = PathologyReport.Status.FINAL
        report.reported_at = timezone.now()
        report.save(update_fields=["status", "reported_at"])
        report.refresh_from_db()
        self.assertEqual(report.status, PathologyReport.Status.FINAL)
        self.assertIsNotNone(report.reported_at)

    def test_optional_surgical_case_link(self):
        case = SurgicalCase.objects.create(
            patient=self.patient,
            surgeon=self.professional,
        )
        report = PathologyReport.objects.create(order_item=self.item, surgical_case=case)
        self.assertEqual(report.surgical_case, case)
        self.assertIn(report, case.pathology_reports.all())

    def test_surgical_case_link_defaults_null(self):
        report = PathologyReport.objects.create(order_item=self.item)
        self.assertIsNone(report.surgical_case)

    # ── API contract + RBAC ────────────────────────────────────────────
    def test_viewset_create_list_retrieve(self):
        client = self.client_for(self.writer)
        create = client.post(
            "/api/v1/pathology-reports/",
            {
                "order_item": str(self.item.id),
                "clinical_history": "Lesão de pele",
                "diagnosis": "Nevo melanocítico benigno",
                "cid_o_topography": "C44.9",
                "cid_o_morphology": "8720/0",
                "status": "final",
            },
            format="json",
        )
        self.assertEqual(create.status_code, 201, create.content)
        report_id = create.data["id"]
        self.assertEqual(create.data["created_by"], self.writer.id)

        spec = client.post(
            "/api/v1/pathology-specimens/",
            {"report": report_id, "label": "A", "site": "Dorso", "blocks_count": 1},
            format="json",
        )
        self.assertEqual(spec.status_code, 201, spec.content)

        listing = client.get("/api/v1/pathology-reports/")
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(len(listing.data["results"]), 1)

        retrieve = client.get(f"/api/v1/pathology-reports/{report_id}/")
        self.assertEqual(retrieve.status_code, 200)
        self.assertEqual(retrieve.data["specimens"][0]["label"], "A")

    def test_status_filter_endpoint(self):
        PathologyReport.objects.create(order_item=self.item, status=PathologyReport.Status.FINAL)
        resp = self.client_for(self.reader).get("/api/v1/pathology-reports/?status=final")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data["results"]), 1)

    def test_reader_cannot_write(self):
        resp = self.client_for(self.reader).post(
            "/api/v1/pathology-reports/",
            {"order_item": str(self.item.id)},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_reader_can_read(self):
        PathologyReport.objects.create(order_item=self.item)
        resp = self.client_for(self.reader).get("/api/v1/pathology-reports/")
        self.assertEqual(resp.status_code, 200)

    # ── CIDO-2: CID-O governado (topografia→CID10Code, morfologia→CIDOMorphology) ──
    def test_topography_reconciles_to_cid10(self):
        CID10Code.objects.create(code="C509", description="Neoplasia maligna da mama SOE")
        report = PathologyReport.objects.create(order_item=self.item)
        report.cid_o_topography_code = "C50.9"  # ponto normalizado -> C509
        report.save()
        report.refresh_from_db()
        self.assertIsNotNone(report.cid_o_topography_cid10_id)
        self.assertEqual(report.cid_o_topography, "")
        self.assertFalse(report.cid_o_topography_unmatched)
        self.assertEqual(report.cid_o_topography_code, "C509")

    def test_morphology_reconciles_to_cido(self):
        CIDOMorphology.objects.create(code="8500/3", display="Carcinoma ductal invasivo")
        report = PathologyReport.objects.create(order_item=self.item)
        report.cid_o_morphology_code = "8500/3"
        report.save()
        report.refresh_from_db()
        self.assertIsNotNone(report.cid_o_morphology_ref_id)
        self.assertFalse(report.cid_o_morphology_unmatched)
        self.assertEqual(report.cid_o_morphology_code, "8500/3")

    def test_unmatched_topography_keeps_text(self):
        report = PathologyReport.objects.create(order_item=self.item)
        report.cid_o_topography_code = "Z99.9"  # não existe
        report.save()
        report.refresh_from_db()
        self.assertIsNone(report.cid_o_topography_cid10_id)
        self.assertEqual(report.cid_o_topography, "Z99.9")
        self.assertTrue(report.cid_o_topography_unmatched)

    def test_patch_cido_codes_reconciles(self):
        CID10Code.objects.create(code="C509", description="Neoplasia mama")
        CIDOMorphology.objects.create(code="8500/3", display="Carcinoma ductal invasivo")
        report = PathologyReport.objects.create(order_item=self.item)
        resp = self.client_for(self.writer).patch(
            f"/api/v1/pathology-reports/{report.id}/",
            {"cid_o_topography_code": "C50.9", "cid_o_morphology_code": "8500/3"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        report.refresh_from_db()
        self.assertIsNotNone(report.cid_o_topography_cid10_id)
        self.assertIsNotNone(report.cid_o_morphology_ref_id)

    def test_delete_cido_morphology_blocked_when_referenced(self):
        morph = CIDOMorphology.objects.create(code="8500/3", display="Carcinoma ductal invasivo")
        report = PathologyReport.objects.create(order_item=self.item)
        report.cid_o_morphology_code = "8500/3"
        report.save()
        with self.assertRaises(ProtectedError) as ctx, transaction.atomic():
            morph.delete()
        self.assertIn("PathologyReport", str(ctx.exception))
        self.assertTrue(CIDOMorphology.objects.filter(pk=morph.pk).exists())

    def test_patient_filter_endpoint(self):
        PathologyReport.objects.create(order_item=self.item, status=PathologyReport.Status.FINAL)
        other_patient = Patient.objects.create(
            full_name="Outro Paciente AP", birth_date="1970-03-03", gender="M", cpf="52998224725"
        )
        other_order = LabOrder.objects.create(
            patient=other_patient, encounter=self.encounter, requested_by=self.writer
        )
        other_item = LabOrderItem.objects.create(
            order=other_order,
            test=self.test,
            test_name=self.test.name,
            category=LabTest.Category.PATHOLOGY,
        )
        PathologyReport.objects.create(order_item=other_item)

        resp = self.client_for(self.reader).get(
            f"/api/v1/pathology-reports/?patient={self.patient.id}"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data["results"]), 1)
        self.assertEqual(resp.data["results"][0]["status"], "final")
