"""
S29-03 Reference Curation — API test suite

Tests for the read-only AllergenClass LIST + set-active toggle action, and the
read-only DrugInteraction LIST + set-active toggle action.

INVIOLABLE: `active` is NEVER serializer-writable; ONLY the set-active action
mutates it. Mirrors the T2 DoseRule Curation pattern exactly.
"""

from rest_framework.test import APIClient

from apps.core.models import AuditLog, FeatureFlag
from apps.core.permissions import DEFAULT_ROLES
from apps.pharmacy.models import AllergenClass, DrugInteraction
from apps.test_utils import TenantTestCase


def _make_allergen_class(*, name="Beta-lactâmicos", active=True):
    return AllergenClass.objects.create(
        name=name,
        members=["amoxicilina", "ampicilina"],
        description="Penicilinas e similares",
        active=active,
        source="SBRAFH v1",
        version="1.0",
    )


def _make_drug_interaction(*, ingredient_a="varfarina", ingredient_b="aas", active=True):
    return DrugInteraction.objects.create(
        ingredient_a=ingredient_a,
        ingredient_b=ingredient_b,
        severity=DrugInteraction.Severity.CONTRAINDICATED,
        description="Aumenta risco de sangramento",
        active=active,
        source="SBRAFH v1",
        version="1.0",
    )


class TestReferenceCurationAPI(TenantTestCase):
    def setUp(self):
        from apps.core.models import Role, User

        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key="pharmacy",
            defaults={"is_enabled": True},
        )
        self.role_farmaceutico = Role.objects.create(
            name="farmaceutico_ref",
            permissions=DEFAULT_ROLES["farmaceutico"],
        )
        self.role_recepcionista = Role.objects.create(
            name="recepcionista_ref",
            permissions=DEFAULT_ROLES["recepcionista"],
        )
        self.farmaceutico = User.objects.create_user(
            email="farm@refcuration.test", password="pw", role=self.role_farmaceutico
        )
        self.recepcionista = User.objects.create_user(
            email="recep@refcuration.test", password="pw", role=self.role_recepcionista
        )

    def _client(self, user):
        c = APIClient()
        c.defaults["SERVER_NAME"] = self.__class__.domain.domain
        c.force_authenticate(user=user)
        return c

    # ── AllergenClass list ────────────────────────────────────────────────────

    def test_allergen_list_returns_rows(self):
        """GET /api/v1/pharmacy/allergen-classes/ as pharmacy.read user → 200; row has source, version, active."""
        allergen = _make_allergen_class()

        resp = self._client(self.farmaceutico).get("/api/v1/pharmacy/allergen-classes/")
        self.assertEqual(resp.status_code, 200)

        results = resp.data.get("results", resp.data)
        self.assertTrue(len(results) >= 1, "Expected at least one allergen-class row")

        row = next((r for r in results if str(r["id"]) == str(allergen.id)), None)
        self.assertIsNotNone(row, "Created allergen class not found in response")
        self.assertEqual(row["source"], "SBRAFH v1")
        self.assertEqual(row["version"], "1.0")
        self.assertTrue(row["active"])

    # ── AllergenClass set-active ──────────────────────────────────────────────

    def test_allergen_set_active_toggle_and_audit(self):
        """POST set-active {"active": false} as farmaceutico → 200; refreshed obj has active=False; AuditLog written."""
        allergen = _make_allergen_class(name="Cefalosporinas")

        resp = self._client(self.farmaceutico).post(
            f"/api/v1/pharmacy/allergen-classes/{allergen.id}/set-active/",
            {"active": False},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)

        allergen.refresh_from_db()
        self.assertFalse(allergen.active)

        logs = AuditLog.objects.filter(
            action="allergen_class_set_active", resource_id=str(allergen.id)
        )
        self.assertEqual(logs.count(), 1)

    # ── DrugInteraction list ──────────────────────────────────────────────────

    def test_interaction_list_returns_rows(self):
        """GET /api/v1/pharmacy/drug-interactions/ → 200; row has severity_display."""
        interaction = _make_drug_interaction()

        resp = self._client(self.farmaceutico).get("/api/v1/pharmacy/drug-interactions/")
        self.assertEqual(resp.status_code, 200)

        results = resp.data.get("results", resp.data)
        self.assertTrue(len(results) >= 1, "Expected at least one drug-interaction row")

        row = next((r for r in results if str(r["id"]) == str(interaction.id)), None)
        self.assertIsNotNone(row, "Created drug interaction not found in response")
        self.assertIn("severity_display", row)
        self.assertEqual(row["severity_display"], "Contraindicada (bloqueia)")

    # ── DrugInteraction set-active ────────────────────────────────────────────

    def test_interaction_set_active_toggle(self):
        """POST set-active {"active": false} → 200; refresh active=False; AuditLog written."""
        interaction = _make_drug_interaction(
            ingredient_a="captopril", ingredient_b="espironolactona"
        )

        resp = self._client(self.farmaceutico).post(
            f"/api/v1/pharmacy/drug-interactions/{interaction.id}/set-active/",
            {"active": False},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)

        interaction.refresh_from_db()
        self.assertFalse(interaction.active)

        logs = AuditLog.objects.filter(
            action="drug_interaction_set_active", resource_id=str(interaction.id)
        )
        self.assertEqual(logs.count(), 1)

    # ── set-active validation ─────────────────────────────────────────────────

    def test_set_active_missing_key_400(self):
        """POST set-active with empty body {} → 400."""
        allergen = _make_allergen_class(name="Sulfonamidas")

        resp = self._client(self.farmaceutico).post(
            f"/api/v1/pharmacy/allergen-classes/{allergen.id}/set-active/",
            {},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    # ── permission gate ───────────────────────────────────────────────────────

    def test_set_active_recepcionista_403(self):
        """Recepcionista lacks pharmacy.catalog_manage → 403 on set-active."""
        allergen = _make_allergen_class(name="Quinolonas")

        resp = self._client(self.recepcionista).post(
            f"/api/v1/pharmacy/allergen-classes/{allergen.id}/set-active/",
            {"active": False},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)

    # ── Fix 1: non-boolean string → 400 ──────────────────────────────────────

    def test_set_active_non_boolean_400_allergen(self):
        """POST set-active with {"active": "false"} (string) → 400; active was NOT changed."""
        allergen = _make_allergen_class(name="Macrolídeos", active=True)

        resp = self._client(self.farmaceutico).post(
            f"/api/v1/pharmacy/allergen-classes/{allergen.id}/set-active/",
            {"active": "false"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

        allergen.refresh_from_db()
        self.assertTrue(
            allergen.active, "active must NOT have been changed by a non-boolean payload"
        )

    def test_set_active_non_boolean_400_interaction(self):
        """POST set-active with {"active": "false"} (string) → 400; active was NOT changed."""
        interaction = _make_drug_interaction(
            ingredient_a="metformina", ingredient_b="contrastemedio", active=True
        )

        resp = self._client(self.farmaceutico).post(
            f"/api/v1/pharmacy/drug-interactions/{interaction.id}/set-active/",
            {"active": "false"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

        interaction.refresh_from_db()
        self.assertTrue(
            interaction.active, "active must NOT have been changed by a non-boolean payload"
        )

    # ── Fix 2: PATCH/PUT write-protection regression ─────────────────────────

    def test_allergen_patch_active_rejected(self):
        """PATCH allergen-classes/{id}/ with {"active": false} → 403 or 405; active unchanged."""
        allergen = _make_allergen_class(name="Aminoglicosídeos", active=True)

        resp = self._client(self.farmaceutico).patch(
            f"/api/v1/pharmacy/allergen-classes/{allergen.id}/",
            {"active": False},
            format="json",
        )
        self.assertIn(resp.status_code, (403, 405), f"Expected 403 or 405, got {resp.status_code}")

        allergen.refresh_from_db()
        self.assertTrue(allergen.active, "PATCH must not have mutated active")

    def test_interaction_patch_active_rejected(self):
        """PATCH drug-interactions/{id}/ with {"active": false} → 403 or 405; active unchanged."""
        interaction = _make_drug_interaction(
            ingredient_a="digoxina", ingredient_b="quinidina", active=True
        )

        resp = self._client(self.farmaceutico).patch(
            f"/api/v1/pharmacy/drug-interactions/{interaction.id}/",
            {"active": False},
            format="json",
        )
        self.assertIn(resp.status_code, (403, 405), f"Expected 403 or 405, got {resp.status_code}")

        interaction.refresh_from_db()
        self.assertTrue(interaction.active, "PATCH must not have mutated active")
