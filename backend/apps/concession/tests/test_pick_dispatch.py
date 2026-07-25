"""C3-T2 — PickList/PickItem + Dispatch/DispatchItem; dispatch deducts stock."""

from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError

from apps.concession.logistics_models import (
    Dispatch,
    PickList,
    RequisitionItem,
    SupplyRequisition,
)
from apps.concession.services_logistics import (
    approve_requisition,
    create_dispatch,
    create_pick_list,
    pick_item,
    ship_dispatch,
    submit_requisition,
)
from apps.concession.tests.factories import (
    make_facility,
    make_material,
    make_user,
    make_warehouse,
    stock_item_with_qty,
)
from apps.test_utils import TenantTestCase


class PickAndDispatchTests(TenantTestCase):
    def setUp(self):
        self.user = make_user()
        self.facility = make_facility()
        self.material = make_material()
        self.warehouse = make_warehouse()
        self.stock = stock_item_with_qty(self.material, self.warehouse, 100, self.user)

        self.req = SupplyRequisition.objects.create(
            requesting_facility=self.facility, requested_by=self.user
        )
        RequisitionItem.objects.create(
            requisition=self.req, material=self.material, quantity=Decimal("30")
        )
        submit_requisition(self.req)
        approve_requisition(self.req)

    def test_pick_list_requires_approved_requisition(self):
        draft = SupplyRequisition.objects.create(
            requesting_facility=self.facility, requested_by=self.user
        )
        with self.assertRaises(ValidationError):
            create_pick_list(draft)

    def test_pick_flow_completes_pick_list(self):
        pl = create_pick_list(self.req)
        self.assertEqual(pl.status, PickList.Status.PENDING)
        self.assertEqual(pl.items.count(), 1)

        pi = pl.items.first()
        pick_item(pi, source_stock_item=self.stock, picked_qty=Decimal("30"))
        pl.refresh_from_db()
        self.assertEqual(pl.status, PickList.Status.PICKED)
        pi.refresh_from_db()
        self.assertTrue(pi.is_picked)
        self.assertEqual(pi.picked_qty, Decimal("30"))

    def test_dispatch_deducts_source_stock_via_ledger(self):
        pl = create_pick_list(self.req)
        pi = pl.items.first()
        pick_item(pi, source_stock_item=self.stock, picked_qty=Decimal("30"))

        dispatch = create_dispatch(pl, manifest_code="QR-001", source_warehouse=self.warehouse)
        self.assertEqual(dispatch.status, Dispatch.Status.PENDING)
        self.assertEqual(dispatch.items.count(), 1)
        self.assertEqual(dispatch.destination_facility, self.facility)

        ship_dispatch(dispatch, performed_by=self.user)
        dispatch.refresh_from_db()
        self.assertEqual(dispatch.status, Dispatch.Status.IN_TRANSIT)

        # Stock reduced 100 → 70 via a single OUT ledger movement.
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, Decimal("70"))
        out = self.stock.movements.filter(reference=f"concession-dispatch:{dispatch.pk}")
        self.assertEqual(out.count(), 1)
        self.assertEqual(out.first().quantity, Decimal("-30"))

    def test_dispatch_requires_fully_picked_list(self):
        pl = create_pick_list(self.req)
        with self.assertRaises(ValidationError):
            create_dispatch(pl, manifest_code="QR-002", source_warehouse=self.warehouse)
