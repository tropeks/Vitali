"""
S29-05 CurationReadinessView — TDD test suite

Tests for GET /api/v1/pharmacy/curation/readiness/ which returns a per-wedge
data-readiness shape for the frontend dashboard. Frontend does ZERO math — all
derivation happens in the view.

Wedges: dose, allergy, interaction, supply.
"""

from decimal import Decimal

from rest_framework.test import APIClient

from apps.core.models import FeatureFlag
from apps.core.permissions import DEFAULT_ROLES
from apps.pharmacy.models import (
    AllergenClass,
    DoseRule,
    Drug,
    DrugInteraction,
    Material,
    MedicationFormulary,
)
from apps.test_utils import TenantTestCase


def _make_drug(name="Drug-ReadinessTest", is_active=True, reorder_point=None):
    return Drug.objects.create(
        name=name,
        generic_name=name.lower(),
        is_active=is_active,
        reorder_point=reorder_point,
    )


def _make_material(name="Material-ReadinessTest", is_active=True, reorder_point=None):
    return Material.objects.create(
        name=name,
        is_active=is_active,
        reorder_point=reorder_point,
    )


def _make_dose_rule(drug=None, active=True, validated=False):
    """Build Drug → MedicationFormulary → DoseRule (fixed basis). Returns rule."""
    if drug is None:
        drug = Drug.objects.create(
            name=f"Drug-DR-{Drug.objects.count()}",
            generic_name="fake_dr",
        )
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
        active=active,
        validated=validated,
    )
    return rule


def _make_allergen_class(name, active=True):
    return AllergenClass.objects.create(
        name=name,
        members=["fake-member"],
        active=active,
    )


def _make_drug_interaction(ingredient_a, ingredient_b, active=True):
    return DrugInteraction.objects.create(
        ingredient_a=ingredient_a,
        ingredient_b=ingredient_b,
        severity=DrugInteraction.Severity.ADVISE,
        active=active,
    )


READINESS_URL = "/api/v1/pharmacy/curation/readiness/"


class TestCurationReadinessView(TenantTestCase):
    def setUp(self):
        from apps.core.models import Role, User

        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key="pharmacy",
            defaults={"is_enabled": True},
        )
        self.role_farmaceutico = Role.objects.create(
            name="farmaceutico_readiness",
            permissions=DEFAULT_ROLES["farmaceutico"],
        )
        self.role_recepcionista = Role.objects.create(
            name="recepcionista_readiness",
            permissions=DEFAULT_ROLES["recepcionista"],
        )
        self.farmaceutico = User.objects.create_user(
            email="farm@readiness.test", password="pw", role=self.role_farmaceutico
        )
        self.recepcionista = User.objects.create_user(
            email="recep@readiness.test", password="pw", role=self.role_recepcionista
        )

    def _client(self, user):
        c = APIClient()
        c.defaults["SERVER_NAME"] = self.__class__.domain.domain
        c.force_authenticate(user=user)
        return c

    def _wedge(self, data, key):
        """Return the wedge dict by key from the response data."""
        return next(w for w in data["wedges"] if w["key"] == key)

    # ── Empty tenant ─────────────────────────────────────────────────────────

    def test_readiness_empty_tenant(self):
        """No data → GET returns 4 wedges, each total=0, ready_count=0, blockers=[]."""
        resp = self._client(self.farmaceutico).get(READINESS_URL)
        self.assertEqual(resp.status_code, 200)

        data = resp.json()
        self.assertIn("wedges", data)
        self.assertEqual(len(data["wedges"]), 4)

        for wedge in data["wedges"]:
            self.assertEqual(wedge["total"], 0, f"wedge {wedge['key']} total != 0")
            self.assertEqual(wedge["ready_count"], 0, f"wedge {wedge['key']} ready_count != 0")
            self.assertEqual(wedge["blockers"], [], f"wedge {wedge['key']} blockers not empty")

        # Verify all 4 keys are present
        keys = {w["key"] for w in data["wedges"]}
        self.assertEqual(keys, {"dose", "allergy", "interaction", "supply"})

    # ── Dose blocker ─────────────────────────────────────────────────────────

    def test_readiness_dose_blocker(self):
        """1 active+validated DoseRule + 1 active+unvalidated → dose total=2, ready_count=1, blocker with '1'."""
        _make_dose_rule(active=True, validated=True)
        _make_dose_rule(active=True, validated=False)

        resp = self._client(self.farmaceutico).get(READINESS_URL)
        self.assertEqual(resp.status_code, 200)

        dose = self._wedge(resp.json(), "dose")
        self.assertEqual(dose["total"], 2)
        self.assertEqual(dose["ready_count"], 1)
        # At least one blocker string containing "1"
        self.assertTrue(len(dose["blockers"]) >= 1)
        self.assertTrue(
            any("1" in b for b in dose["blockers"]),
            f"Expected '1' in a blocker string, got: {dose['blockers']}",
        )

    def test_readiness_dose_all_ready(self):
        """All DoseRules validated → blockers=[] and ready_text present."""
        _make_dose_rule(active=True, validated=True)

        resp = self._client(self.farmaceutico).get(READINESS_URL)
        self.assertEqual(resp.status_code, 200)

        dose = self._wedge(resp.json(), "dose")
        self.assertEqual(dose["total"], 1)
        self.assertEqual(dose["ready_count"], 1)
        self.assertEqual(dose["blockers"], [])
        self.assertIn("ready_text", dose)
        self.assertTrue(len(dose["ready_text"]) > 0)

    # ── Allergy + Interaction counts ─────────────────────────────────────────

    def test_readiness_allergy_interaction_counts(self):
        """2 AllergenClass (1 active, 1 inactive) + 2 DrugInteraction (1 active, 1 inactive)
        → allergy total=2 ready_count=1; interaction total=2 ready_count=1."""
        _make_allergen_class("Readiness-Classe-A", active=True)
        _make_allergen_class("Readiness-Classe-B", active=False)
        _make_drug_interaction("mol-x", "mol-y", active=True)
        _make_drug_interaction("mol-p", "mol-q", active=False)

        resp = self._client(self.farmaceutico).get(READINESS_URL)
        self.assertEqual(resp.status_code, 200)

        data = resp.json()
        allergy = self._wedge(data, "allergy")
        self.assertEqual(allergy["total"], 2)
        self.assertEqual(allergy["ready_count"], 1)
        # Has a blocker (1 inactive class)
        self.assertTrue(len(allergy["blockers"]) >= 1)

        interaction = self._wedge(data, "interaction")
        self.assertEqual(interaction["total"], 2)
        self.assertEqual(interaction["ready_count"], 1)
        self.assertTrue(len(interaction["blockers"]) >= 1)

    # ── Supply counts ────────────────────────────────────────────────────────

    def test_readiness_supply_counts(self):
        """1 Drug with reorder_point set + 1 Material without (both is_active)
        → supply total=2 ready_count=1, blocker counts 1."""
        _make_drug(name="Drug-WithReorder", is_active=True, reorder_point=Decimal("10.00"))
        _make_material(name="Material-NoReorder", is_active=True, reorder_point=None)

        resp = self._client(self.farmaceutico).get(READINESS_URL)
        self.assertEqual(resp.status_code, 200)

        supply = self._wedge(resp.json(), "supply")
        self.assertEqual(supply["total"], 2)
        self.assertEqual(supply["ready_count"], 1)
        # Should have a blocker mentioning 1 unconfigured item
        self.assertTrue(len(supply["blockers"]) >= 1)
        self.assertTrue(
            any("1" in b for b in supply["blockers"]),
            f"Expected '1' in a supply blocker, got: {supply['blockers']}",
        )

    def test_readiness_supply_all_ready(self):
        """All active Drug+Material have reorder_point → blockers=[]."""
        _make_drug(name="Drug-Rdy", is_active=True, reorder_point=Decimal("5.00"))
        _make_material(name="Material-Rdy", is_active=True, reorder_point=Decimal("3.00"))

        resp = self._client(self.farmaceutico).get(READINESS_URL)
        self.assertEqual(resp.status_code, 200)

        supply = self._wedge(resp.json(), "supply")
        self.assertEqual(supply["total"], 2)
        self.assertEqual(supply["ready_count"], 2)
        self.assertEqual(supply["blockers"], [])

    # ── Permission gate ──────────────────────────────────────────────────────

    def test_readiness_read_perm_required(self):
        """Recepcionista (no pharmacy.read) → 403."""
        resp = self._client(self.recepcionista).get(READINESS_URL)
        self.assertEqual(resp.status_code, 403)
