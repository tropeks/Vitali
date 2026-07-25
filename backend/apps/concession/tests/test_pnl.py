"""Sprint C4-T2 — contract_pnl / unit_pnl engine (service layer).

TDD for the all-inclusive P&L: revenue (billable only, volume always counts) −
cost (consumption + freight + maintenance), exact Decimal, per-service breakdown.
"""

from datetime import date, datetime
from decimal import Decimal

from django.utils import timezone

from apps.concession.models import (
    ConcessionContract,
    ConcessionService,
    ContractServicePrice,
    EquipmentAsset,
    MaintenanceTicket,
    MaterialUnitCost,
    ServiceRecipe,
)
from apps.concession.services_pnl import contract_pnl, record_exam_consumption, unit_pnl
from apps.test_utils import TenantTestCase

from .factories import make_facility, make_material, make_user, make_warehouse, stock_item_with_qty

PERIOD_START = date(2026, 1, 1)
PERIOD_END = date(2026, 12, 31)


class _Fixtures(TenantTestCase):
    def setUp(self):
        self.user = make_user()
        self.unit_a = make_facility(code="UNIT-A", name="Unidade A")
        self.unit_b = make_facility(code="UNIT-B", name="Unidade B")
        self.wh = make_warehouse()

        self.gel = make_material("Gel condutor")
        self.film = make_material("Filme radiológico")
        MaterialUnitCost.objects.create(material=self.gel, unit_cost=Decimal("1.50"))
        MaterialUnitCost.objects.create(material=self.film, unit_cost=Decimal("10.00"))
        stock_item_with_qty(self.gel, self.wh, 100, self.user, lot="G-1")
        stock_item_with_qty(self.film, self.wh, 100, self.user, lot="F-1")

        self.xray = ConcessionService.objects.create(code="SRV-XRAY", name="Raio-X")
        self.ct = ConcessionService.objects.create(code="SRV-CT", name="Tomografia")
        ServiceRecipe.objects.create(service=self.xray, material=self.gel, quantity=Decimal("2"))
        ServiceRecipe.objects.create(service=self.ct, material=self.film, quantity=Decimal("1"))

        self.contract = ConcessionContract.objects.create(
            name="Contrato Mestre", client_name="Rede", start_date=PERIOD_START
        )
        self.contract.units.add(self.unit_a, self.unit_b)
        # X-ray is billable at 100; CT is INCLUDED (non-billable) — volume counts,
        # revenue 0.
        ContractServicePrice.objects.create(
            contract=self.contract, service=self.xray, price=Decimal("100.00"), is_billable=True
        )
        ContractServicePrice.objects.create(
            contract=self.contract, service=self.ct, price=Decimal("200.00"), is_billable=False
        )

    def _record(self, service, unit, ref, performed_at=None):
        return record_exam_consumption(
            service, unit, ref, warehouse=self.wh, performed_at=performed_at, performed_by=self.user
        )


class TestContractPnlMath(_Fixtures):
    def setUp(self):
        super().setUp()
        # 2 billable X-rays + 1 included CT at unit A.
        self._record(self.xray, self.unit_a, "X-1")
        self._record(self.xray, self.unit_a, "X-2")
        self._record(self.ct, self.unit_a, "C-1")
        # A maintenance ticket cost (50) at unit A in the period.
        asset = EquipmentAsset.objects.create(
            asset_tag="AST-1", model="GE", current_location=self.unit_a
        )
        MaintenanceTicket.objects.create(
            asset=asset,
            facility=self.unit_a,
            cost=Decimal("50.00"),
            status=MaintenanceTicket.Status.COMPLETED,
        )

    def test_revenue_counts_billable_only(self):
        pnl = contract_pnl(self.contract, PERIOD_START, PERIOD_END)
        # 2 × 100 (X-ray billable) + 0 (CT included) = 200
        self.assertEqual(pnl["revenue"], Decimal("200.00"))

    def test_exam_volume_counts_all_including_non_billable(self):
        pnl = contract_pnl(self.contract, PERIOD_START, PERIOD_END)
        self.assertEqual(pnl["exam_volume"], 3)

    def test_cost_has_all_three_legs(self):
        pnl = contract_pnl(self.contract, PERIOD_START, PERIOD_END)
        # consumption: 2 × (2×1.50)=6.00 + 1 × (1×10)=10.00 → 16.00
        self.assertEqual(pnl["cost_breakdown"]["consumption"], Decimal("16.00"))
        self.assertEqual(pnl["cost_breakdown"]["freight"], Decimal("0"))
        self.assertEqual(pnl["cost_breakdown"]["maintenance"], Decimal("50.00"))
        self.assertEqual(pnl["cost"], Decimal("66.00"))

    def test_result_is_revenue_minus_cost(self):
        pnl = contract_pnl(self.contract, PERIOD_START, PERIOD_END)
        self.assertEqual(pnl["result"], Decimal("134.00"))  # 200 − 66

    def test_per_service_breakdown(self):
        pnl = contract_pnl(self.contract, PERIOD_START, PERIOD_END)
        by = {line["service_code"]: line for line in pnl["by_service"]}
        self.assertEqual(by["SRV-XRAY"]["exam_volume"], 2)
        self.assertEqual(by["SRV-XRAY"]["revenue"], Decimal("200.00"))
        self.assertEqual(by["SRV-XRAY"]["consumption_cost"], Decimal("6.00"))
        # CT included: volume counts, revenue 0.
        self.assertEqual(by["SRV-CT"]["exam_volume"], 1)
        self.assertEqual(by["SRV-CT"]["revenue"], Decimal("0"))
        self.assertEqual(by["SRV-CT"]["consumption_cost"], Decimal("10.00"))


class TestPnlPeriodAndUnit(_Fixtures):
    def test_period_filters_out_of_range_exams(self):
        in_period = timezone.make_aware(datetime(2026, 6, 1, 12, 0))
        out_period = timezone.make_aware(datetime(2025, 6, 1, 12, 0))
        self._record(self.xray, self.unit_a, "IN", performed_at=in_period)
        self._record(self.xray, self.unit_a, "OUT", performed_at=out_period)
        pnl = contract_pnl(self.contract, PERIOD_START, PERIOD_END)
        self.assertEqual(pnl["exam_volume"], 1)
        self.assertEqual(pnl["revenue"], Decimal("100.00"))

    def test_unit_pnl_scopes_to_single_unit(self):
        self._record(self.xray, self.unit_a, "A-1")
        self._record(self.xray, self.unit_b, "B-1")
        pnl_a = unit_pnl(self.contract, self.unit_a, PERIOD_START, PERIOD_END)
        self.assertEqual(pnl_a["exam_volume"], 1)
        self.assertEqual(pnl_a["revenue"], Decimal("100.00"))
