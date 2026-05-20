"""Integration tests for the FHIR R4 Practitioner REST surface."""

from __future__ import annotations

from rest_framework.test import APIClient

from apps.core.models import FeatureFlag, Role, User
from apps.emr.models import Professional
from apps.test_utils import TenantTestCase

PRACTITIONER_SEARCH_URL = "/api/v1/fhir/Practitioner/"
METADATA_URL = "/api/v1/fhir/metadata"


def _practitioner_read_url(pk):
    return f"/api/v1/fhir/Practitioner/{pk}/"


def _make_user(*, role_name: str, perms: list[str], full_name: str) -> User:
    role, _ = Role.objects.get_or_create(name=role_name, defaults={"permissions": perms})
    role.permissions = perms
    role.save()
    return User.objects.create_user(
        email=f"{role_name}@test.com", password="pw", role=role, full_name=full_name
    )


class FHIRPractitionerViewsTest(TenantTestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key="fhir",
            defaults={"is_enabled": True},
        )
        self.reader_user = _make_user(
            role_name="fhir_prac_reader",
            perms=["fhir.read"],
            full_name="FHIR Reader Bot",
        )
        self.client.force_authenticate(user=self.reader_user)

        # Two professionals: an active CRM and an inactive CRO.
        self.md_user = _make_user(
            role_name="md_prac", perms=["fhir.read"], full_name="Dra Ana Silva"
        )
        self.md = Professional.objects.create(
            user=self.md_user,
            council_type="CRM",
            council_number="123456",
            council_state="SP",
            specialty="Clínica Médica",
            cbo_code="225125",
        )
        self.dentist_user = _make_user(
            role_name="dt_prac", perms=["fhir.read"], full_name="Dr Bruno Lima"
        )
        self.dentist = Professional.objects.create(
            user=self.dentist_user,
            council_type="CRO",
            council_number="98765",
            council_state="RJ",
            is_active=False,
        )

    # ─── Capability statement ─────────────────────────────────────────────────

    def test_capability_statement_advertises_practitioner(self):
        self.client.logout()
        resp = self.client.get(METADATA_URL)
        self.assertEqual(resp.status_code, 200)
        types = {r["type"] for r in resp.data["rest"][0]["resource"]}
        self.assertIn("Practitioner", types)

    # ─── Read ─────────────────────────────────────────────────────────────────

    def test_read_returns_fhir_practitioner(self):
        resp = self.client.get(_practitioner_read_url(self.md.pk))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["resourceType"], "Practitioner")
        self.assertEqual(resp.data["id"], str(self.md.pk))
        self.assertTrue(resp.data["active"])
        identifier = resp.data["identifier"][0]
        self.assertEqual(identifier["system"], "urn:vitali:council/crm")
        self.assertEqual(identifier["value"], "123456")

    def test_read_returns_404_for_unknown_id(self):
        resp = self.client.get(_practitioner_read_url("00000000-0000-4000-8000-000000000000"))
        self.assertEqual(resp.status_code, 404)

    # ─── Search ───────────────────────────────────────────────────────────────

    def test_search_by_council_identifier_returns_only_match(self):
        resp = self.client.get(
            PRACTITIONER_SEARCH_URL, {"identifier": "urn:vitali:council/crm|123456"}
        )
        self.assertEqual(resp.status_code, 200)
        ids = {entry["resource"]["id"] for entry in resp.data["entry"]}
        self.assertEqual(ids, {str(self.md.pk)})

    def test_search_by_bare_council_number_ignores_council_type(self):
        resp = self.client.get(PRACTITIONER_SEARCH_URL, {"identifier": "98765"})
        self.assertEqual(resp.status_code, 200)
        ids = {entry["resource"]["id"] for entry in resp.data["entry"]}
        self.assertIn(str(self.dentist.pk), ids)

    def test_search_by_name_substring(self):
        resp = self.client.get(PRACTITIONER_SEARCH_URL, {"name": "ana"})
        self.assertEqual(resp.status_code, 200)
        ids = {entry["resource"]["id"] for entry in resp.data["entry"]}
        self.assertIn(str(self.md.pk), ids)
        self.assertNotIn(str(self.dentist.pk), ids)

    def test_search_active_true_filters_out_inactive(self):
        resp = self.client.get(PRACTITIONER_SEARCH_URL, {"active": "true"})
        self.assertEqual(resp.status_code, 200)
        ids = {entry["resource"]["id"] for entry in resp.data["entry"]}
        self.assertIn(str(self.md.pk), ids)
        self.assertNotIn(str(self.dentist.pk), ids)

    def test_search_active_false_returns_only_inactive(self):
        resp = self.client.get(PRACTITIONER_SEARCH_URL, {"active": "false"})
        self.assertEqual(resp.status_code, 200)
        ids = {entry["resource"]["id"] for entry in resp.data["entry"]}
        self.assertIn(str(self.dentist.pk), ids)
        self.assertNotIn(str(self.md.pk), ids)

    # ─── Gates ────────────────────────────────────────────────────────────────

    def test_search_blocked_when_module_disabled(self):
        FeatureFlag.objects.filter(tenant=self.__class__.tenant, module_key="fhir").update(
            is_enabled=False
        )
        resp = self.client.get(PRACTITIONER_SEARCH_URL)
        self.assertEqual(resp.status_code, 403)

    def test_read_blocked_without_fhir_read_permission(self):
        no_perm = _make_user(role_name="no_fhir_prac", perms=["patients.read"], full_name="No Perm")
        self.client.force_authenticate(user=no_perm)
        resp = self.client.get(_practitioner_read_url(self.md.pk))
        self.assertEqual(resp.status_code, 403)
