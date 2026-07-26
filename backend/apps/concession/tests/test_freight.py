"""C5-P1 — Dispatch.freight_cost feeds the P&L freight leg (contract_pnl).

A Dispatch to a contract's unit with ``freight_cost`` set makes the P&L freight
leg reflect it (and drops ``result`` accordingly). No freight → 0 (unchanged).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from apps.concession.logistics_models import RequisitionItem, SupplyRequisition
from apps.concession.models import ConcessionContract
from apps.concession.services_logistics import (
    approve_requisition,
    create_dispatch,
    create_pick_list,
    pick_item,
    submit_requisition,
)
from apps.concession.services_pnl import contract_pnl
from apps.test_utils import TenantTestCase

from .factories import make_facility, make_material, make_user, make_warehouse, stock_item_with_qty

PERIOD_START = date(2026, 1, 1)
PERIOD_END = date(2026, 12, 31)


class FreightLegTests(TenantTestCase):
    def setUp(self):
        self.user = make_user()
        self.unit = make_facility()
        self.wh = make_warehouse()
        self.material = make_material()
        self.stock = stock_item_with_qty(self.material, self.wh, 100, self.user)
        self.contract = ConcessionContract.objects.create(
            name="Contrato", client_name="Rede", start_date=PERIOD_START
        )
        self.contract.units.add(self.unit)

    def _dispatch_to_unit(self, manifest, freight=None):
        req = SupplyRequisition.objects.create(
            requesting_facility=self.unit, requested_by=self.user
        )
        RequisitionItem.objects.create(
            requisition=req, material=self.material, quantity=Decimal("5")
        )
        submit_requisition(req)
        approve_requisition(req)
        pl = create_pick_list(req)
        pi = pl.items.first()
        pick_item(pi, source_stock_item=self.stock, picked_qty=Decimal("5"))
        dispatch = create_dispatch(pl, manifest_code=manifest, source_warehouse=self.wh)
        if freight is not None:
            dispatch.freight_cost = freight
            dispatch.save()
        return dispatch

    def test_freight_cost_flows_into_pnl_freight_leg(self):
        self._dispatch_to_unit("QR-F1", freight=Decimal("120.00"))
        pnl = contract_pnl(self.contract, PERIOD_START, PERIOD_END)
        self.assertEqual(pnl["cost_breakdown"]["freight"], Decimal("120.00"))
        self.assertEqual(pnl["cost"], Decimal("120.00"))
        # No revenue, no exams → result = −cost.
        self.assertEqual(pnl["result"], Decimal("-120.00"))

    def test_no_freight_defaults_to_zero(self):
        self._dispatch_to_unit("QR-F0")  # freight_cost left null
        pnl = contract_pnl(self.contract, PERIOD_START, PERIOD_END)
        self.assertEqual(pnl["cost_breakdown"]["freight"], Decimal("0"))
        self.assertEqual(pnl["cost"], Decimal("0"))
