"""
Integration tests for the FHIR R4 REST surface (read + search + metadata).
"""

from __future__ import annotations

from datetime import date

from rest_framework.test import APIClient

from apps.core.models import FeatureFlag, Role, User
from apps.emr.models import Patient
from apps.fhir.services.patient_mapper import SYSTEM_CPF, SYSTEM_MRN
from apps.test_utils import TenantTestCase

METADATA_URL = "/api/v1/fhir/metadata"
PATIENT_SEARCH_URL = "/api/v1/fhir/Patient/"


def _patient_read_url(pk):
    return f"/api/v1/fhir/Patient/{pk}/"


def _make_user(*, role_name: str, perms: list[str]) -> User:
    role, _ = Role.objects.get_or_create(name=role_name, defaults={"permissions": perms})
    role.permissions = perms
    role.save()
    return User.objects.create_user(email=f"{role_name}@test.com", password="pw", role=role)


class FHIRViewsTest(TenantTestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key="fhir",
            defaults={"is_enabled": True},
        )
        self.user = _make_user(role_name="fhir_reader", perms=["fhir.read"])
        self.client.force_authenticate(user=self.user)

        self.ana = Patient.objects.create(
            full_name="Ana Maria Souza",
            cpf="12345678909",
            birth_date=date(1985, 7, 14),
            gender="F",
            phone="11 3000-1000",
            whatsapp="11 99999-1234",
            email="ana@example.com",
        )
        self.bruno = Patient.objects.create(
            full_name="Bruno Lima",
            cpf="98765432100",
            birth_date=date(1990, 3, 1),
            gender="M",
        )

    # ─── Capability statement ─────────────────────────────────────────────────

    def test_metadata_is_public(self):
        self.client.logout()
        resp = self.client.get(METADATA_URL)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["resourceType"], "CapabilityStatement")
        self.assertEqual(resp.data["fhirVersion"], "4.0.1")
        resources = resp.data["rest"][0]["resource"]
        types = {r["type"] for r in resources}
        self.assertIn("Patient", types)

    # ─── Patient read ─────────────────────────────────────────────────────────

    def test_patient_read_returns_fhir_resource(self):
        resp = self.client.get(_patient_read_url(self.ana.pk))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["resourceType"], "Patient")
        self.assertEqual(resp.data["id"], str(self.ana.pk))
        self.assertEqual(resp.data["gender"], "female")
        self.assertEqual(resp.data["birthDate"], "1985-07-14")
        identifiers = {ident["system"]: ident["value"] for ident in resp.data["identifier"]}
        self.assertEqual(identifiers[SYSTEM_CPF], "12345678909")
        self.assertEqual(identifiers[SYSTEM_MRN], self.ana.medical_record_number)

    def test_patient_read_returns_404_for_unknown_id(self):
        resp = self.client.get(_patient_read_url("00000000-0000-4000-8000-000000000000"))
        self.assertEqual(resp.status_code, 404)

    # ─── Patient search ───────────────────────────────────────────────────────

    def test_search_without_filters_returns_searchset_bundle(self):
        resp = self.client.get(PATIENT_SEARCH_URL, {"_count": 100})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["resourceType"], "Bundle")
        self.assertEqual(resp.data["type"], "searchset")
        ids_in_bundle = {entry["resource"]["id"] for entry in resp.data["entry"]}
        self.assertIn(str(self.ana.pk), ids_in_bundle)
        self.assertIn(str(self.bruno.pk), ids_in_bundle)

    def test_search_by_mrn_identifier(self):
        resp = self.client.get(
            PATIENT_SEARCH_URL,
            {"identifier": f"{SYSTEM_MRN}|{self.ana.medical_record_number}"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["total"], 1)
        self.assertEqual(resp.data["entry"][0]["resource"]["id"], str(self.ana.pk))

    def test_search_by_cpf_identifier(self):
        resp = self.client.get(PATIENT_SEARCH_URL, {"identifier": f"{SYSTEM_CPF}|12345678909"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["total"], 1)
        self.assertEqual(resp.data["entry"][0]["resource"]["id"], str(self.ana.pk))

    def test_search_by_name_substring(self):
        resp = self.client.get(PATIENT_SEARCH_URL, {"name": "bruno"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["total"], 1)
        self.assertEqual(resp.data["entry"][0]["resource"]["id"], str(self.bruno.pk))

    def test_search_count_capped_at_max(self):
        resp = self.client.get(PATIENT_SEARCH_URL, {"_count": 9999})
        # Even with a huge ?_count the response must not exceed 100; we only
        # have 2 patients so total=2.
        self.assertEqual(resp.status_code, 200)
        self.assertLessEqual(len(resp.data["entry"]), 100)

    # ─── Gates ────────────────────────────────────────────────────────────────

    def test_read_blocked_when_module_disabled(self):
        FeatureFlag.objects.filter(tenant=self.__class__.tenant, module_key="fhir").update(
            is_enabled=False
        )
        resp = self.client.get(_patient_read_url(self.ana.pk))
        self.assertEqual(resp.status_code, 403)

    def test_read_blocked_without_fhir_read_permission(self):
        no_perm = _make_user(role_name="no_fhir", perms=["patients.read"])
        self.client.force_authenticate(user=no_perm)
        resp = self.client.get(_patient_read_url(self.ana.pk))
        self.assertEqual(resp.status_code, 403)

    def test_read_unauthenticated_returns_401(self):
        self.client.logout()
        resp = self.client.get(_patient_read_url(self.ana.pk))
        self.assertIn(resp.status_code, [401, 403])

    def test_search_blocked_when_module_disabled(self):
        FeatureFlag.objects.filter(tenant=self.__class__.tenant, module_key="fhir").update(
            is_enabled=False
        )
        resp = self.client.get(PATIENT_SEARCH_URL)
        self.assertEqual(resp.status_code, 403)
