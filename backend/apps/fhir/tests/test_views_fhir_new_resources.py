"""
Integration tests for the FHIR R4 resources added alongside SMART-on-FHIR:
DocumentReference, DiagnosticReport, Coverage — plus searchset paging
(Bundle.link + RFC 5988 Link header) verified end-to-end on a real endpoint.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from rest_framework.test import APIClient

from apps.core.models import FeatureFlag, Role, User
from apps.emr.models import (
    ClinicalDocument,
    Encounter,
    Patient,
    PatientInsurance,
    Professional,
)
from apps.test_utils import TenantTestCase

METADATA_URL = "/api/v1/fhir/metadata"
DOCREF_SEARCH = "/api/v1/fhir/DocumentReference/"
DIAGREPORT_SEARCH = "/api/v1/fhir/DiagnosticReport/"
COVERAGE_SEARCH = "/api/v1/fhir/Coverage/"
PATIENT_SEARCH = "/api/v1/fhir/Patient/"


def _make_user(*, role_name: str, perms: list[str], full_name: str = "Tester") -> User:
    role, _ = Role.objects.get_or_create(name=role_name, defaults={"permissions": perms})
    role.permissions = perms
    role.save()
    return User.objects.create_user(
        email=f"{role_name}@test.com", password="pw", role=role, full_name=full_name
    )


class _FhirCaseBase(TenantTestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key="fhir",
            defaults={"is_enabled": True},
        )
        self.user = _make_user(role_name="fhir_new", perms=["fhir.read"])
        self.client.force_authenticate(user=self.user)


class DocumentReferenceTest(_FhirCaseBase):
    def setUp(self):
        super().setUp()
        self.patient = Patient.objects.create(
            full_name="Ana Maria Souza",
            cpf="12345678909",
            birth_date=date(1985, 7, 14),
            gender="F",
        )
        self.md_user = _make_user(role_name="md_doc", perms=["fhir.read"], full_name="Dra Bia")
        self.professional = Professional.objects.create(
            user=self.md_user, council_type="CRM", council_number="800300", council_state="SP"
        )
        self.encounter = Encounter.objects.create(
            patient=self.patient,
            professional=self.professional,
            status="signed",
            encounter_date=datetime(2026, 5, 19, 9, 0, tzinfo=UTC),
        )
        self.certificate = ClinicalDocument.objects.create(
            encounter=self.encounter,
            doc_type="certificate",
            content="Atestado de 2 dias.",
            signed_at=datetime(2026, 5, 19, 10, 0, tzinfo=UTC),
            signed_by=self.md_user,
        )
        # A report is NOT a DocumentReference (it is a DiagnosticReport).
        self.report = ClinicalDocument.objects.create(
            encounter=self.encounter, doc_type="report", content="Laudo."
        )

    def test_capability_lists_document_reference(self):
        self.client.logout()
        resp = self.client.get(METADATA_URL)
        types = {r["type"] for r in resp.data["rest"][0]["resource"]}
        self.assertIn("DocumentReference", types)

    def test_read_certificate_returns_document_reference(self):
        resp = self.client.get(f"{DOCREF_SEARCH}{self.certificate.pk}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["resourceType"], "DocumentReference")
        self.assertEqual(resp.data["status"], "current")
        self.assertEqual(resp.data["docStatus"], "final")
        self.assertEqual(resp.data["subject"]["reference"], f"Patient/{self.patient.pk}")
        # Body is embedded as a base64 attachment.
        self.assertEqual(resp.data["content"][0]["attachment"]["contentType"], "text/plain")

    def test_read_report_returns_404_via_document_reference(self):
        resp = self.client.get(f"{DOCREF_SEARCH}{self.report.pk}/")
        self.assertEqual(resp.status_code, 404)

    def test_search_by_patient_returns_only_certificates(self):
        resp = self.client.get(DOCREF_SEARCH, {"patient": str(self.patient.pk)})
        ids = {e["resource"]["id"] for e in resp.data["entry"]}
        self.assertIn(str(self.certificate.pk), ids)
        self.assertNotIn(str(self.report.pk), ids)

    def test_blocked_when_module_disabled(self):
        FeatureFlag.objects.filter(tenant=self.__class__.tenant, module_key="fhir").update(
            is_enabled=False
        )
        resp = self.client.get(f"{DOCREF_SEARCH}{self.certificate.pk}/")
        self.assertEqual(resp.status_code, 403)


class DiagnosticReportTest(_FhirCaseBase):
    def setUp(self):
        super().setUp()
        self.patient = Patient.objects.create(
            full_name="Bruno Lima",
            cpf="98765432100",
            birth_date=date(1990, 3, 1),
            gender="M",
        )
        self.md_user = _make_user(role_name="md_rep", perms=["fhir.read"], full_name="Dr Caio")
        self.professional = Professional.objects.create(
            user=self.md_user, council_type="CRM", council_number="900400", council_state="SP"
        )
        self.encounter = Encounter.objects.create(
            patient=self.patient,
            professional=self.professional,
            status="signed",
            encounter_date=datetime(2026, 5, 20, 9, 0, tzinfo=UTC),
        )
        self.signed_report = ClinicalDocument.objects.create(
            encounter=self.encounter,
            doc_type="report",
            content="Hemoglobina 14.2 g/dL. Sem alterações.",
            signed_at=datetime(2026, 5, 20, 10, 0, tzinfo=UTC),
            signed_by=self.md_user,
        )
        self.draft_report = ClinicalDocument.objects.create(
            encounter=self.encounter, doc_type="report", content="Em análise."
        )

    def test_capability_lists_diagnostic_report(self):
        self.client.logout()
        resp = self.client.get(METADATA_URL)
        types = {r["type"] for r in resp.data["rest"][0]["resource"]}
        self.assertIn("DiagnosticReport", types)

    def test_read_signed_report_is_final(self):
        resp = self.client.get(f"{DIAGREPORT_SEARCH}{self.signed_report.pk}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["resourceType"], "DiagnosticReport")
        self.assertEqual(resp.data["status"], "final")
        self.assertIn("conclusion", resp.data)
        self.assertEqual(resp.data["performer"][0]["display"], "Dr Caio")

    def test_search_status_final_excludes_drafts(self):
        resp = self.client.get(
            DIAGREPORT_SEARCH, {"patient": str(self.patient.pk), "status": "final"}
        )
        ids = {e["resource"]["id"] for e in resp.data["entry"]}
        self.assertIn(str(self.signed_report.pk), ids)
        self.assertNotIn(str(self.draft_report.pk), ids)

    def test_search_unknown_status_is_empty(self):
        resp = self.client.get(DIAGREPORT_SEARCH, {"status": "amended"})
        self.assertEqual(resp.data["total"], 0)


class CoverageTest(_FhirCaseBase):
    def setUp(self):
        super().setUp()
        self.patient = Patient.objects.create(
            full_name="Carla Dias",
            cpf="11144477735",
            birth_date=date(1979, 2, 2),
            gender="F",
        )
        self.active = PatientInsurance.objects.create(
            patient=self.patient,
            provider_ans_code="123456",
            provider_name="Unimed",
            card_number="0001-2222-3333",
            valid_until=date(2027, 12, 31),
            is_active=True,
        )
        self.cancelled = PatientInsurance.objects.create(
            patient=self.patient,
            provider_ans_code="654321",
            provider_name="Amil",
            card_number="9999-8888-7777",
            is_active=False,
        )

    def test_capability_lists_coverage(self):
        self.client.logout()
        resp = self.client.get(METADATA_URL)
        types = {r["type"] for r in resp.data["rest"][0]["resource"]}
        self.assertIn("Coverage", types)

    def test_read_active_coverage(self):
        resp = self.client.get(f"{COVERAGE_SEARCH}{self.active.pk}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["resourceType"], "Coverage")
        self.assertEqual(resp.data["status"], "active")
        self.assertEqual(resp.data["beneficiary"]["reference"], f"Patient/{self.patient.pk}")
        self.assertEqual(resp.data["payor"][0]["identifier"]["value"], "123456")

    def test_search_status_active_filters(self):
        resp = self.client.get(
            COVERAGE_SEARCH, {"patient": str(self.patient.pk), "status": "active"}
        )
        ids = {e["resource"]["id"] for e in resp.data["entry"]}
        self.assertIn(str(self.active.pk), ids)
        self.assertNotIn(str(self.cancelled.pk), ids)

    def test_cancelled_coverage_status(self):
        resp = self.client.get(f"{COVERAGE_SEARCH}{self.cancelled.pk}/")
        self.assertEqual(resp.data["status"], "cancelled")


class SearchsetPagingTest(_FhirCaseBase):
    """End-to-end paging behaviour on a real search endpoint (Patient)."""

    def setUp(self):
        super().setUp()
        for i in range(5):
            Patient.objects.create(
                full_name=f"Paciente {i:02d}",
                cpf=f"1234567890{i}",
                birth_date=date(1980, 1, 1),
                gender="O",
            )

    def test_first_page_has_next_link_and_header(self):
        resp = self.client.get(PATIENT_SEARCH, {"_count": 2, "_offset": 0})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["total"], 5)
        self.assertEqual(len(resp.data["entry"]), 2)
        rels = {link["relation"] for link in resp.data["link"]}
        self.assertIn("next", rels)
        self.assertIn("last", rels)
        self.assertNotIn("previous", rels)
        # The RFC 5988 Link header mirrors the Bundle.link relations.
        self.assertIn('rel="next"', resp["Link"])

    def test_offset_window_returns_disjoint_pages(self):
        page1 = self.client.get(PATIENT_SEARCH, {"_count": 2, "_offset": 0})
        page2 = self.client.get(PATIENT_SEARCH, {"_count": 2, "_offset": 2})
        ids1 = {e["resource"]["id"] for e in page1.data["entry"]}
        ids2 = {e["resource"]["id"] for e in page2.data["entry"]}
        self.assertEqual(ids1 & ids2, set())

    def test_last_page_has_no_next(self):
        resp = self.client.get(PATIENT_SEARCH, {"_count": 2, "_offset": 4})
        rels = {link["relation"] for link in resp.data["link"]}
        self.assertNotIn("next", rels)
        self.assertIn("previous", rels)
