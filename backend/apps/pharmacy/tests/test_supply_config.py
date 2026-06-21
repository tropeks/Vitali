"""
S-29 Supply-config fields on Drug/Material serializers — test suite (TDD)

Tests that DrugSerializer and MaterialSerializer expose the stockout-prediction
config fields (lead_time_days, safety_stock, reorder_point, and
min_refill_interval_days for Drug) and allow PATCH by catalog_manage users
while blocking low-priv users.
"""

from decimal import Decimal

from rest_framework import status
from rest_framework.test import APIClient

from apps.core.models import FeatureFlag
from apps.core.permissions import DEFAULT_ROLES
from apps.pharmacy.models import Drug, Material
from apps.test_utils import TenantTestCase


class TestSupplyConfigFields(TenantTestCase):
    def setUp(self):
        from apps.core.models import Role, User

        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant, module_key="pharmacy", defaults={"is_enabled": True}
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
            email="farm@test.com", password="pw", role=self.role_farmaceutico
        )
        self.recepcionista = User.objects.create_user(
            email="recep@test.com", password="pw", role=self.role_recepcionista
        )

    def _client(self, user):
        c = APIClient()
        c.defaults["SERVER_NAME"] = self.__class__.domain.domain
        c.force_authenticate(user=user)
        return c

    # ── Drug tests ─────────────────────────────────────────────────────────────

    def test_drug_list_exposes_supply_fields(self):
        """GET /api/v1/pharmacy/drugs/ must include all four supply-config keys."""
        Drug.objects.create(
            name="Amoxicilina 500mg",
            lead_time_days=3,
            safety_stock=Decimal("20.00"),
            reorder_point=Decimal("50.00"),
            min_refill_interval_days=30,
        )
        resp = self._client(self.farmaceutico).get("/api/v1/pharmacy/drugs/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        results = resp.data.get("results", resp.data)
        self.assertTrue(len(results) >= 1, "Expected at least one drug in list")
        row = results[0]
        for field in (
            "lead_time_days",
            "safety_stock",
            "reorder_point",
            "min_refill_interval_days",
        ):
            self.assertIn(field, row, f"Field '{field}' missing from drug list response")

    def test_drug_patch_sets_reorder_point(self):
        """PATCH with reorder_point and lead_time_days persists correctly."""
        drug = Drug.objects.create(name="Dipirona 500mg")
        resp = self._client(self.farmaceutico).patch(
            f"/api/v1/pharmacy/drugs/{drug.id}/",
            {"reorder_point": "5.00", "lead_time_days": 7},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        drug.refresh_from_db()
        self.assertEqual(drug.reorder_point, Decimal("5.00"))
        self.assertEqual(drug.lead_time_days, 7)

    def test_drug_patch_nullable_clears_min_refill(self):
        """PATCH min_refill_interval_days=null clears the field (sets to None)."""
        drug = Drug.objects.create(name="Morfina 10mg", min_refill_interval_days=30)
        resp = self._client(self.farmaceutico).patch(
            f"/api/v1/pharmacy/drugs/{drug.id}/",
            {"min_refill_interval_days": None},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        drug.refresh_from_db()
        self.assertIsNone(drug.min_refill_interval_days)

    # ── Material tests ─────────────────────────────────────────────────────────

    def test_material_patch_sets_safety_stock(self):
        """PATCH safety_stock on a Material persists correctly."""
        mat = Material.objects.create(name="Luva nitrílica G", category="EPI")
        resp = self._client(self.farmaceutico).patch(
            f"/api/v1/pharmacy/materials/{mat.id}/",
            {"safety_stock": "10.00"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        mat.refresh_from_db()
        self.assertEqual(mat.safety_stock, Decimal("10.00"))

    # ── Permission gate ────────────────────────────────────────────────────────

    def test_supply_patch_recepcionista_403(self):
        """A recepcionista (no catalog_manage) must get 403 when PATCHing supply fields."""
        drug = Drug.objects.create(name="Paracetamol 500mg")
        resp = self._client(self.recepcionista).patch(
            f"/api/v1/pharmacy/drugs/{drug.id}/",
            {"reorder_point": "5.00"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
