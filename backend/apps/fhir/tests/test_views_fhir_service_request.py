"""Integration tests for the FHIR R4 ServiceRequest REST surface."""

from __future__ import annotations

from datetime import UTC, date, datetime

from rest_framework.test import APIClient

from apps.core.models import FeatureFlag, Role, User
from apps.emr.models import ClinicalDocument, Encounter, Patient, Professional
from apps.test_utils import TenantTestCase

METADATA_URL = "/api/v1/fhir/metadata"
SR_SEARCH = "/api/v1/fhir/ServiceRequest/"


def _sr_read(pk):
    return f"/api/v1/fhir/ServiceRequest/{pk}/"


def _make_user(*, role_name: str, perms: list[str], full_name: str = "Tester") -> User:
    role, _ = Role.objects.get_or_create(name=role_name, defaults={"permissions": perms})
    role.permissions = perms
    role.save()
    return User.objects.create_user(
        email=f"{role_name}@test.com", password="pw", role=role, full_name=full_name
    )


class FHIRServiceRequestViewsTest(TenantTestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key="fhir",
            defaults={"is_enabled": True},
        )
        self.user = _make_user(role_name="fhir_sr", perms=["fhir.read"])
        self.client.force_authenticate(user=self.user)

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
        self.md_user = _make_user(role_name="md_sr", perms=["fhir.read"], full_name="Dra Bia")
        self.professional = Professional.objects.create(
            user=self.md_user,
            council_type="CRM",
            council_number="800300",
            council_state="SP",
        )
        self.encounter = Encounter.objects.create(
            patient=self.patient,
            professional=self.professional,
            status="signed",
            encounter_date=datetime(2026, 5, 19, 9, 0, tzinfo=UTC),
        )
        self.other_encounter = Encounter.objects.create(
            patient=self.other_patient,
            professional=self.professional,
            status="signed",
        )

        # Mix of ServiceRequest-eligible and ineligible clinical documents.
        self.referral_signed = ClinicalDocument.objects.create(
            encounter=self.encounter,
            doc_type="referral",
            content="Encaminhamento para cardiologia.",
            signed_at=datetime(2026, 5, 19, 10, 0, tzinfo=UTC),
            signed_by=self.md_user,
        )
        self.exam_request_draft = ClinicalDocument.objects.create(
            encounter=self.encounter,
            doc_type="exam_request",
            content="Hemograma completo.",
        )
        self.certificate = ClinicalDocument.objects.create(
            encounter=self.encounter,
            doc_type="certificate",
            content="Atestado de 1 dia.",
        )
        self.other_referral = ClinicalDocument.objects.create(
            encounter=self.other_encounter,
            doc_type="referral",
            content="Encaminhamento para ortopedia.",
            signed_at=datetime(2026, 5, 19, 11, 0, tzinfo=UTC),
        )

    # ─── Capability statement ────────────────────────────────────────────────

    def test_capability_statement_lists_service_request(self):
        self.client.logout()
        resp = self.client.get(METADATA_URL)
        types = {r["type"] for r in resp.data["rest"][0]["resource"]}
        self.assertIn("ServiceRequest", types)

    # ─── Read ────────────────────────────────────────────────────────────────

    def test_read_referral_returns_fhir_resource(self):
        resp = self.client.get(_sr_read(self.referral_signed.pk))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["resourceType"], "ServiceRequest")
        self.assertEqual(resp.data["status"], "active")
        self.assertEqual(resp.data["category"][0]["text"], "Encaminhamento")

    def test_read_unsigned_exam_request_is_draft(self):
        resp = self.client.get(_sr_read(self.exam_request_draft.pk))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["status"], "draft")

    def test_read_certificate_returns_404(self):
        # Certificates are NOT ServiceRequests; FHIR clients must not get one
        # back via this endpoint.
        resp = self.client.get(_sr_read(self.certificate.pk))
        self.assertEqual(resp.status_code, 404)

    def test_read_unknown_id_returns_404(self):
        resp = self.client.get(_sr_read("00000000-0000-4000-8000-000000000000"))
        self.assertEqual(resp.status_code, 404)

    # ─── Search ──────────────────────────────────────────────────────────────

    def test_search_by_patient_returns_referrals_and_exam_requests_only(self):
        resp = self.client.get(SR_SEARCH, {"patient": str(self.patient.pk)})
        ids = {entry["resource"]["id"] for entry in resp.data["entry"]}
        self.assertIn(str(self.referral_signed.pk), ids)
        self.assertIn(str(self.exam_request_draft.pk), ids)
        # Certificate excluded
        self.assertNotIn(str(self.certificate.pk), ids)
        # Other patient excluded
        self.assertNotIn(str(self.other_referral.pk), ids)

    def test_search_by_status_active_returns_signed_only(self):
        resp = self.client.get(SR_SEARCH, {"patient": str(self.patient.pk), "status": "active"})
        ids = {entry["resource"]["id"] for entry in resp.data["entry"]}
        self.assertIn(str(self.referral_signed.pk), ids)
        self.assertNotIn(str(self.exam_request_draft.pk), ids)

    def test_search_by_status_draft_returns_unsigned_only(self):
        resp = self.client.get(SR_SEARCH, {"patient": str(self.patient.pk), "status": "draft"})
        ids = {entry["resource"]["id"] for entry in resp.data["entry"]}
        self.assertIn(str(self.exam_request_draft.pk), ids)
        self.assertNotIn(str(self.referral_signed.pk), ids)

    def test_search_by_category_referral_filters(self):
        resp = self.client.get(SR_SEARCH, {"category": "referral"})
        ids = {entry["resource"]["id"] for entry in resp.data["entry"]}
        self.assertIn(str(self.referral_signed.pk), ids)
        self.assertNotIn(str(self.exam_request_draft.pk), ids)

    def test_search_by_category_exam_request_filters(self):
        resp = self.client.get(SR_SEARCH, {"category": "exam_request"})
        ids = {entry["resource"]["id"] for entry in resp.data["entry"]}
        self.assertIn(str(self.exam_request_draft.pk), ids)
        self.assertNotIn(str(self.referral_signed.pk), ids)

    def test_search_with_unknown_category_returns_empty(self):
        resp = self.client.get(SR_SEARCH, {"category": "certificate"})
        self.assertEqual(resp.data["total"], 0)

    def test_search_with_unknown_status_returns_empty(self):
        resp = self.client.get(SR_SEARCH, {"status": "completed"})
        self.assertEqual(resp.data["total"], 0)

    # ─── Gates ───────────────────────────────────────────────────────────────

    def test_read_blocked_when_module_disabled(self):
        FeatureFlag.objects.filter(tenant=self.__class__.tenant, module_key="fhir").update(
            is_enabled=False
        )
        resp = self.client.get(_sr_read(self.referral_signed.pk))
        self.assertEqual(resp.status_code, 403)
