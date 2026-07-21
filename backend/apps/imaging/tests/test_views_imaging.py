"""Integration tests for the imaging (DICOM Study tracking) REST surface."""

from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import patch

from rest_framework.test import APIClient

from apps.core.models import FeatureFlag, Role, User
from apps.emr.models import (
    ClinicalDocument,
    Encounter,
    LabOrder,
    LabOrderItem,
    LabTest,
    Patient,
    Professional,
)
from apps.imaging.models import DicomStudy
from apps.test_utils import TenantTestCase

LIST_URL = "/api/v1/imaging/studies/"
VIEWER_AUTH_URL = "/api/v1/imaging/viewer-auth/"


def _detail_url(pk):
    return f"/api/v1/imaging/studies/{pk}/"


def _orthanc_url(pk):
    return f"/api/v1/imaging/studies/{pk}/orthanc/"


def _make_user(*, role_name: str, perms: list[str], full_name: str = "Tester") -> User:
    role, _ = Role.objects.get_or_create(name=role_name, defaults={"permissions": perms})
    role.permissions = perms
    role.save()
    return User.objects.create_user(
        email=f"{role_name}@test.com", password="pw", role=role, full_name=full_name
    )


class ImagingViewsTest(TenantTestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key="imaging",
            defaults={"is_enabled": True},
        )
        self.writer = _make_user(
            role_name="imaging_writer",
            perms=["imaging.read", "imaging.write"],
            full_name="Imaging Writer",
        )
        self.reader = _make_user(
            role_name="imaging_reader",
            perms=["imaging.read"],
            full_name="Imaging Reader",
        )
        self.client.force_authenticate(user=self.writer)

        self.patient = Patient.objects.create(
            full_name="Ana Maria Souza",
            cpf="12345678909",
            birth_date=date(1985, 7, 14),
            gender="F",
        )
        self.other_patient = Patient.objects.create(
            full_name="Bruno Lima",
            cpf="98765432100",
            birth_date=date(1990, 3, 1),
            gender="M",
        )
        self.md_user = _make_user(
            role_name="md_img",
            perms=["imaging.read", "imaging.write"],
            full_name="Dra Bia",
        )
        self.professional = Professional.objects.create(
            user=self.md_user,
            council_type="CRM",
            council_number="900100",
            council_state="SP",
        )
        self.encounter = Encounter.objects.create(
            patient=self.patient,
            professional=self.professional,
            status="signed",
            encounter_date=datetime(2026, 5, 19, 9, 0, tzinfo=UTC),
        )

        self.ct_study = DicomStudy.objects.create(
            patient=self.patient,
            encounter=self.encounter,
            study_instance_uid="1.2.840.113619.2.55.3.604688119.1234567890.001",
            accession_number="ACC-2026-001",
            modality="CT",
            body_part_examined="THORAX",
            description="CT de tórax sem contraste.",
            study_date=datetime(2026, 5, 18, 14, 30, tzinfo=UTC),
        )
        self.us_study = DicomStudy.objects.create(
            patient=self.patient,
            study_instance_uid="1.2.840.113619.2.55.3.604688119.1234567890.002",
            modality="US",
            body_part_examined="ABDOMEN",
            study_date=datetime(2026, 5, 17, 11, 0, tzinfo=UTC),
        )
        self.other_ct = DicomStudy.objects.create(
            patient=self.other_patient,
            study_instance_uid="1.2.840.113619.2.55.3.604688119.1234567890.003",
            modality="CT",
            body_part_examined="HEAD",
            study_date=datetime(2026, 5, 18, 16, 0, tzinfo=UTC),
        )
        self.lab_test = LabTest.objects.create(code="IMG-CONTEXT", name="Contexto diagnóstico")
        self.lab_order = LabOrder.objects.create(patient=self.patient, requested_by=self.writer)
        self.lab_item = LabOrderItem.objects.create(
            order=self.lab_order,
            test=self.lab_test,
            test_name=self.lab_test.name,
        )

    def create_payload(self, **overrides):
        payload = {
            "patient": str(self.patient.pk),
            "encounter": str(self.encounter.pk),
            "study_instance_uid": "1.2.840.113619.2.55.3.604688119.999.999",
            "accession_number": "ACC-2026-999",
            "modality": "MR",
            "body_part_examined": "BRAIN",
            "description": "RM crânio com contraste.",
            "study_date": "2026-05-20T10:00:00Z",
            "number_of_series": 8,
            "number_of_instances": 320,
        }
        payload.update(overrides)
        return payload

    # ─── List + filtering ────────────────────────────────────────────────────

    def test_viewer_auth_accepts_authorized_reader(self):
        self.client.force_authenticate(user=self.reader)
        response = self.client.get(VIEWER_AUTH_URL)
        self.assertEqual(response.status_code, 204)

    def test_viewer_auth_rejects_anonymous_user(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(VIEWER_AUTH_URL)
        self.assertIn(response.status_code, (401, 403))

    def test_list_returns_studies(self):
        resp = self.client.get(LIST_URL)
        self.assertEqual(resp.status_code, 200)
        ids = {entry["id"] for entry in resp.data}
        self.assertIn(str(self.ct_study.pk), ids)
        self.assertIn(str(self.us_study.pk), ids)
        self.assertIn(str(self.other_ct.pk), ids)

    def test_filter_by_patient(self):
        resp = self.client.get(LIST_URL, {"patient": str(self.patient.pk)})
        ids = {entry["id"] for entry in resp.data}
        self.assertIn(str(self.ct_study.pk), ids)
        self.assertIn(str(self.us_study.pk), ids)
        self.assertNotIn(str(self.other_ct.pk), ids)

    def test_filter_by_modality(self):
        resp = self.client.get(LIST_URL, {"modality": "ct"})
        ids = {entry["id"] for entry in resp.data}
        self.assertIn(str(self.ct_study.pk), ids)
        self.assertIn(str(self.other_ct.pk), ids)
        self.assertNotIn(str(self.us_study.pk), ids)

    def test_filter_by_encounter(self):
        resp = self.client.get(LIST_URL, {"encounter": str(self.encounter.pk)})
        ids = {entry["id"] for entry in resp.data}
        self.assertEqual(ids, {str(self.ct_study.pk)})

    # ─── Detail ──────────────────────────────────────────────────────────────

    def test_detail_returns_full_record(self):
        resp = self.client.get(_detail_url(self.ct_study.pk))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["modality"], "CT")
        self.assertEqual(resp.data["modality_display"], "Computed Tomography")
        self.assertEqual(resp.data["body_part_examined"], "THORAX")
        self.assertFalse(resp.data["has_pixel_data"])

    def test_detail_unknown_id_returns_404(self):
        resp = self.client.get(_detail_url("00000000-0000-4000-8000-000000000000"))
        self.assertEqual(resp.status_code, 404)

    # ─── Create ──────────────────────────────────────────────────────────────

    def test_create_registers_new_study(self):
        payload = self.create_payload()
        resp = self.client.post(LIST_URL, payload, format="json")
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data["modality_display"], "Magnetic Resonance")
        self.assertEqual(resp.data["created_by"], self.writer.pk)
        # Round-trips into the DB
        self.assertTrue(
            DicomStudy.objects.filter(
                study_instance_uid="1.2.840.113619.2.55.3.604688119.999.999"
            ).exists()
        )

    def test_create_links_lab_context_and_filters_without_changing_its_category(self):
        response = self.client.post(
            LIST_URL,
            self.create_payload(related_lab_item=str(self.lab_item.pk)),
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["related_lab_item"], self.lab_item.pk)
        self.assertEqual(response.data["related_lab_order"], str(self.lab_order.pk))
        self.lab_test.refresh_from_db()
        self.assertEqual(self.lab_test.category, LabTest.Category.OTHER)

        by_item = self.client.get(LIST_URL, {"lab_order_item": str(self.lab_item.pk)})
        by_order = self.client.get(LIST_URL, {"lab_order": str(self.lab_order.pk)})
        self.assertEqual([entry["id"] for entry in by_item.data], [response.data["id"]])
        self.assertEqual([entry["id"] for entry in by_order.data], [response.data["id"]])

    def test_create_rejects_lab_item_from_another_patient(self):
        other_order = LabOrder.objects.create(patient=self.other_patient, requested_by=self.writer)
        other_item = LabOrderItem.objects.create(
            order=other_order,
            test=self.lab_test,
            test_name=self.lab_test.name,
        )
        response = self.client.post(
            LIST_URL,
            self.create_payload(related_lab_item=str(other_item.pk)),
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("related_lab_item", response.data)

    def test_report_link_exposes_metadata_but_not_clinical_content(self):
        report = ClinicalDocument.objects.create(
            encounter=self.encounter,
            doc_type="report",
            content="Achado sensível que não pertence ao endpoint de imagem.",
        )
        response = self.client.post(
            LIST_URL,
            self.create_payload(report_document=str(report.pk)),
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["report_status"]["id"], str(report.pk))
        self.assertFalse(response.data["report_status"]["is_signed"])
        self.assertNotIn("content", response.data["report_status"])
        self.assertNotIn("content", response.data)

    def test_report_link_rejects_non_report_document(self):
        document = ClinicalDocument.objects.create(
            encounter=self.encounter,
            doc_type="exam_request",
            content="Solicitação",
        )
        response = self.client.post(
            LIST_URL,
            self.create_payload(report_document=str(document.pk)),
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("report_document", response.data)

    def test_create_rejects_duplicate_study_uid(self):
        payload = {
            "patient": str(self.patient.pk),
            "study_instance_uid": self.ct_study.study_instance_uid,
            "modality": "MR",
            "study_date": "2026-05-20T10:00:00Z",
        }
        resp = self.client.post(LIST_URL, payload, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_create_blocked_without_imaging_write_permission(self):
        self.client.force_authenticate(user=self.reader)
        payload = {
            "patient": str(self.patient.pk),
            "study_instance_uid": "1.2.840.113619.2.55.3.604688119.888.888",
            "modality": "CT",
            "study_date": "2026-05-20T10:00:00Z",
        }
        resp = self.client.post(LIST_URL, payload, format="json")
        self.assertEqual(resp.status_code, 403)

    # ─── Orthanc backfill ────────────────────────────────────────────────────

    def test_orthanc_patch_sets_uid_and_counts(self):
        orthanc_id = "f9d8a7b6-c5e4-3210-9876-fedcba012345"

        def verified_link(study, requested_orthanc_id):
            self.assertEqual(requested_orthanc_id, orthanc_id)
            study.orthanc_study_id = requested_orthanc_id
            study.dicom_identity_verified = True
            study.number_of_series = 3
            study.number_of_instances = 240
            study.save(
                update_fields=[
                    "orthanc_study_id",
                    "dicom_identity_verified",
                    "number_of_series",
                    "number_of_instances",
                ]
            )
            return "matched"

        with patch(
            "apps.imaging.services.orthanc_sync.verify_and_link_study",
            side_effect=verified_link,
        ):
            resp = self.client.patch(
                _orthanc_url(self.ct_study.pk),
                {"orthanc_study_id": orthanc_id},
                format="json",
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["orthanc_study_id"], "f9d8a7b6-c5e4-3210-9876-fedcba012345")
        self.assertTrue(resp.data["has_pixel_data"])
        self.assertEqual(resp.data["number_of_instances"], 240)

    def test_orthanc_patch_requires_imaging_write(self):
        self.client.force_authenticate(user=self.reader)
        resp = self.client.patch(
            _orthanc_url(self.ct_study.pk),
            {"orthanc_study_id": "any"},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)

    # ─── Gates ───────────────────────────────────────────────────────────────

    def test_list_blocked_when_module_disabled(self):
        FeatureFlag.objects.filter(tenant=self.__class__.tenant, module_key="imaging").update(
            is_enabled=False
        )
        resp = self.client.get(LIST_URL)
        self.assertEqual(resp.status_code, 403)

    def test_list_unauthenticated_returns_401(self):
        self.client.logout()
        resp = self.client.get(LIST_URL)
        self.assertIn(resp.status_code, [401, 403])
