"""
S29-02 DoseRule Curation — API test suite

Tests for the read-only DoseRule LIST endpoint and the pharmacist-only `validate`
action that sets validated/validated_by/validated_at and writes an AuditLog.

INVIOLABLE: `validated` is NEVER serializer-writable; ONLY the validate action
mutates it.
"""

from decimal import Decimal

from rest_framework.test import APIClient

from apps.core.models import AuditLog, FeatureFlag
from apps.core.permissions import DEFAULT_ROLES
from apps.pharmacy.models import DoseRule, Drug, MedicationFormulary
from apps.test_utils import TenantTestCase


def _make_dose_rule(*, validated=False):
    """
    Build a minimal fixture: Drug → MedicationFormulary → DoseRule (fixed basis).
    Returns (drug, formulary, rule).
    """
    drug = Drug.objects.create(name="FAKE-CurationDrug", generic_name="fake_curation")
    formulary = MedicationFormulary.objects.create(
        drug=drug,
        strength_value=Decimal("10.000"),
        strength_unit="mg",
        route="PO",
        active=True,
    )
    rule = DoseRule.objects.create(
        formulary=formulary,
        basis="fixed",
        dose_unit="mg",
        min_per_dose=Decimal("5.0000"),
        max_per_dose=Decimal("20.0000"),
        absolute_max_dose=Decimal("20.0000"),
        active=True,
        validated=validated,
    )
    return drug, formulary, rule


class TestDoseRuleCurationAPI(TenantTestCase):
    def setUp(self):
        from apps.core.models import Role, User

        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key="pharmacy",
            defaults={"is_enabled": True},
        )
        self.role_farmaceutico = Role.objects.create(
            name="farmaceutico",
            permissions=DEFAULT_ROLES["farmaceutico"],
        )
        self.role_recepcionista = Role.objects.create(
            name="recepcionista",
            permissions=DEFAULT_ROLES["recepcionista"],
        )
        self.farmaceutico = User.objects.create_user(
            email="farm@curation.test", password="pw", role=self.role_farmaceutico
        )
        self.recepcionista = User.objects.create_user(
            email="recep@curation.test", password="pw", role=self.role_recepcionista
        )

    def _client(self, user):
        c = APIClient()
        c.defaults["SERVER_NAME"] = self.__class__.domain.domain
        c.force_authenticate(user=user)
        return c

    # ── List tests ────────────────────────────────────────────────────────────

    def test_list_returns_rows_with_drug_name(self):
        """GET /api/v1/pharmacy/dose-rules/ as pharmacy.read user → 200; row has drug_name + validated=False."""
        _, _, rule = _make_dose_rule(validated=False)

        resp = self._client(self.farmaceutico).get("/api/v1/pharmacy/dose-rules/")
        self.assertEqual(resp.status_code, 200)

        results = resp.data.get("results", resp.data)
        self.assertTrue(len(results) >= 1, "Expected at least one dose-rule row")

        row = next((r for r in results if str(r["id"]) == str(rule.id)), None)
        self.assertIsNotNone(row, "Created rule not found in response")
        self.assertEqual(row["drug_name"], "FAKE-CurationDrug")
        self.assertFalse(row["validated"])

    def test_list_recepcionista_403(self):
        """Recepcionista lacks pharmacy.read → 403 on dose-rules list."""
        _make_dose_rule()
        resp = self._client(self.recepcionista).get("/api/v1/pharmacy/dose-rules/")
        self.assertEqual(resp.status_code, 403)

    # ── Validate action tests ─────────────────────────────────────────────────

    def test_validate_sets_fields_and_audit(self):
        """POST /validate/ as farmaceutico → 200; rule flips to validated=True; AuditLog written."""
        _, _, rule = _make_dose_rule(validated=False)

        resp = self._client(self.farmaceutico).post(
            f"/api/v1/pharmacy/dose-rules/{rule.id}/validate/"
        )
        self.assertEqual(resp.status_code, 200)

        rule.refresh_from_db()
        self.assertTrue(rule.validated)
        self.assertEqual(rule.validated_by_id, self.farmaceutico.id)
        self.assertIsNotNone(rule.validated_at)

        # Exactly one AuditLog row for this action
        logs = AuditLog.objects.filter(action="dose_rule_validated", resource_id=str(rule.id))
        self.assertEqual(logs.count(), 1)

    def test_validate_already_validated_409(self):
        """POST /validate/ on a rule already validated → 409 Conflict."""
        _, _, rule = _make_dose_rule(validated=True)
        # Simulate prior validation metadata
        from django.utils import timezone

        rule.validated_by = self.farmaceutico
        rule.validated_at = timezone.now()
        rule.save(update_fields=["validated_by", "validated_at"])

        resp = self._client(self.farmaceutico).post(
            f"/api/v1/pharmacy/dose-rules/{rule.id}/validate/"
        )
        self.assertEqual(resp.status_code, 409)

    def test_validate_recepcionista_403(self):
        """Recepcionista lacks pharmacy.catalog_manage → 403 on validate action."""
        _, _, rule = _make_dose_rule(validated=False)

        resp = self._client(self.recepcionista).post(
            f"/api/v1/pharmacy/dose-rules/{rule.id}/validate/"
        )
        self.assertEqual(resp.status_code, 403)

    # ── Fix 2: PATCH write-protection regression ──────────────────────────────

    def test_doserule_patch_validated_rejected(self):
        """PATCH dose-rules/{id}/ with {"validated": true} → 403 or 405; validated still False."""
        _, _, rule = _make_dose_rule(validated=False)

        resp = self._client(self.farmaceutico).patch(
            f"/api/v1/pharmacy/dose-rules/{rule.id}/",
            {"validated": True},
            format="json",
        )
        self.assertIn(resp.status_code, (403, 405), f"Expected 403 or 405, got {resp.status_code}")

        rule.refresh_from_db()
        self.assertFalse(rule.validated, "PATCH must not have mutated validated")
