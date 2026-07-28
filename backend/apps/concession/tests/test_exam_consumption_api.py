"""B0-T4 — ExamConsumption read ledger + manual record endpoint."""

from __future__ import annotations

from decimal import Decimal

from rest_framework.test import APIClient

from apps.concession.contract_models import ServiceRecipe
from apps.concession.models import ConcessionService
from apps.concession.pnl_models import ExamConsumption, MaterialUnitCost
from apps.concession.services_pnl import record_exam_consumption
from apps.concession.tests.factories import (
    make_facility,
    make_material,
    make_user,
    make_warehouse,
    stock_item_with_qty,
)
from apps.core.models import FeatureFlag
from apps.test_utils import TenantTestCase

BASE = "/api/v1/concession"


class ExamConsumptionApiTests(TenantTestCase):
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

        self.unit = make_facility()
        self.wh = make_warehouse()
        self.material = make_material()
        MaterialUnitCost.objects.create(material=self.material, unit_cost=Decimal("1.50"))
        self.stock = stock_item_with_qty(self.material, self.wh, 50, self.user)
        self.service = ConcessionService.objects.create(code="US", name="Ultrassom")
        ServiceRecipe.objects.create(
            service=self.service, material=self.material, quantity=Decimal("2")
        )

    def test_record_endpoint_creates_row_and_deducts_stock(self):
        resp = self.client.post(
            f"{BASE}/exam-consumptions/record/",
            {
                "service": self.service.id,
                "unit": str(self.unit.pk),
                "external_ref": "EX-1",
                "warehouse": str(self.wh.pk),
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(ExamConsumption.objects.count(), 1)
        row = ExamConsumption.objects.get()
        self.assertEqual(row.cost_snapshot, Decimal("3.00"))
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, Decimal("48"))

    def test_record_insufficient_stock_returns_400(self):
        empty_wh = make_warehouse(code="EMPTY", name="Vazio")
        resp = self.client.post(
            f"{BASE}/exam-consumptions/record/",
            {
                "service": self.service.id,
                "unit": str(self.unit.pk),
                "external_ref": "EX-SHORT",
                "warehouse": str(empty_wh.pk),
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertEqual(ExamConsumption.objects.count(), 0)

    def test_list_and_retrieve_ledger(self):
        c = record_exam_consumption(self.service, self.unit, "EX-2", warehouse=self.wh)
        resp = self.client.get(f"{BASE}/exam-consumptions/")
        self.assertEqual(resp.status_code, 200, resp.content)
        results = resp.data["results"] if isinstance(resp.data, dict) else resp.data
        self.assertEqual(len(results), 1)
        detail = self.client.get(f"{BASE}/exam-consumptions/{c.pk}/")
        self.assertEqual(detail.status_code, 200, detail.content)

    def test_ledger_is_append_only_no_put_delete(self):
        c = record_exam_consumption(self.service, self.unit, "EX-3", warehouse=self.wh)
        self.assertEqual(
            self.client.put(
                f"{BASE}/exam-consumptions/{c.pk}/", {"external_ref": "X"}, format="json"
            ).status_code,
            405,
        )
        self.assertEqual(self.client.delete(f"{BASE}/exam-consumptions/{c.pk}/").status_code, 405)

    def test_tier_gate_403(self):
        FeatureFlag.objects.filter(
            tenant=self.__class__.tenant, module_key="diagnostic_concession"
        ).update(is_enabled=False)
        self.assertEqual(self.client.get(f"{BASE}/exam-consumptions/").status_code, 403)
