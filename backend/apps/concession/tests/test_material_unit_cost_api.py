"""B0-T3 — MaterialUnitCost CRUD (gated REST)."""

from __future__ import annotations

from decimal import Decimal

from rest_framework.test import APIClient

from apps.concession.pnl_models import MaterialUnitCost
from apps.concession.tests.factories import make_material, make_user
from apps.core.models import AuditLog, FeatureFlag
from apps.test_utils import TenantTestCase

BASE = "/api/v1/concession"


class MaterialUnitCostApiTests(TenantTestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key="diagnostic_concession",
            defaults={"is_enabled": True},
        )
        self.user = make_user()
        self.client.force_authenticate(user=self.user)
        self.material = make_material()

    def test_create_unit_cost_201_and_audited(self):
        resp = self.client.post(
            f"{BASE}/material-unit-costs/",
            {"material": str(self.material.pk), "unit_cost": "1.50"},
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        row = MaterialUnitCost.objects.get(material=self.material)
        self.assertEqual(row.unit_cost, Decimal("1.50"))
        self.assertTrue(
            AuditLog.objects.filter(resource_type="MaterialUnitCost", action="create").exists()
        )

    def test_update_unit_cost_200(self):
        row = MaterialUnitCost.objects.create(material=self.material, unit_cost=Decimal("1.00"))
        resp = self.client.patch(
            f"{BASE}/material-unit-costs/{row.pk}/", {"unit_cost": "2.75"}, format="json"
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        row.refresh_from_db()
        self.assertEqual(row.unit_cost, Decimal("2.75"))

    def test_list_unit_costs_200(self):
        MaterialUnitCost.objects.create(material=self.material, unit_cost=Decimal("3.00"))
        resp = self.client.get(f"{BASE}/material-unit-costs/")
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_tier_gate_403(self):
        FeatureFlag.objects.filter(
            tenant=self.__class__.tenant, module_key="diagnostic_concession"
        ).update(is_enabled=False)
        self.assertEqual(self.client.get(f"{BASE}/material-unit-costs/").status_code, 403)
