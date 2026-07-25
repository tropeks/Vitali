"""C3-T3 — ProofOfDelivery (append-only) + DispatchDiscrepancy; delivery adds stock."""

from __future__ import annotations

from decimal import Decimal

from django.utils import timezone

from apps.concession.logistics_models import (
    Dispatch,
    DispatchDiscrepancy,
    ProofOfDelivery,
    RequisitionItem,
    SupplyRequisition,
)
from apps.concession.services_logistics import (
    approve_requisition,
    create_dispatch,
    create_pick_list,
    deliver_dispatch,
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
from apps.pharmacy.models import StockItem
from apps.test_utils import TenantTestCase


class DeliveryTests(TenantTestCase):
    def setUp(self):
        self.user = make_user()
        self.facility = make_facility()
        self.material = make_material()
        self.source_wh = make_warehouse(code="CENTRAL", name="Central")
        # Destination warehouse = the client unit's local on-hand stock location.
        self.unit_wh = make_warehouse(code="UNIT-WH", name="Unidade WH")
        self.stock = stock_item_with_qty(self.material, self.source_wh, 100, self.user)

        req = SupplyRequisition.objects.create(
            requesting_facility=self.facility, requested_by=self.user
        )
        RequisitionItem.objects.create(
            requisition=req, material=self.material, quantity=Decimal("30")
        )
        submit_requisition(req)
        approve_requisition(req)
        pl = create_pick_list(req)
        pick_item(pl.items.first(), source_stock_item=self.stock, picked_qty=Decimal("30"))
        self.dispatch = create_dispatch(
            pl,
            manifest_code="QR-DEL",
            source_warehouse=self.source_wh,
            destination_warehouse=self.unit_wh,
        )
        ship_dispatch(self.dispatch, performed_by=self.user)

    def _dest_qty(self):
        item = StockItem.objects.filter(material=self.material, warehouse=self.unit_wh).first()
        return item.quantity if item else Decimal("0")

    def test_capture_proof_increments_unit_stock(self):
        proof = deliver_dispatch(
            self.dispatch,
            received_by="Enfermeira Ana",
            signature_ref="s3://sig/abc.png",
            geo_lat=Decimal("-23.550520"),
            geo_lng=Decimal("-46.633308"),
            captured_by=self.user,
        )
        self.assertIsInstance(proof, ProofOfDelivery)
        self.dispatch.refresh_from_db()
        self.assertEqual(self.dispatch.status, Dispatch.Status.DELIVERED)
        # Full 30 landed at the unit.
        self.assertEqual(self._dest_qty(), Decimal("30"))
        item = self.dispatch.items.first()
        item.refresh_from_db()
        self.assertEqual(item.received_qty, Decimal("30"))

    def test_missing_discrepancy_reduces_received_qty(self):
        deliver_dispatch(
            self.dispatch,
            received_by="Ana",
            captured_by=self.user,
            discrepancies=[
                {
                    "type": DispatchDiscrepancy.Type.MISSING,
                    "material": self.material,
                    "quantity": Decimal("5"),
                    "notes": "5 faltando",
                }
            ],
        )
        # 30 dispatched − 5 missing = 25 received/added to unit stock.
        self.assertEqual(self._dest_qty(), Decimal("25"))
        item = self.dispatch.items.first()
        item.refresh_from_db()
        self.assertEqual(item.received_qty, Decimal("25"))
        self.assertEqual(self.dispatch.discrepancies.count(), 1)

    def test_proof_is_append_only(self):
        proof = deliver_dispatch(self.dispatch, received_by="Ana", captured_by=self.user)
        proof.received_by = "Outro"
        with self.assertRaises(ValueError):
            proof.save()
        with self.assertRaises(ValueError):
            proof.delete()

    def test_cannot_deliver_a_pending_dispatch(self):
        # A fresh dispatch not yet shipped cannot be delivered.
        req = SupplyRequisition.objects.create(
            requesting_facility=self.facility, requested_by=self.user
        )
        RequisitionItem.objects.create(
            requisition=req, material=self.material, quantity=Decimal("1")
        )
        submit_requisition(req)
        approve_requisition(req)
        pl = create_pick_list(req)
        pick_item(pl.items.first(), source_stock_item=self.stock, picked_qty=Decimal("1"))
        pending = create_dispatch(
            pl,
            manifest_code="QR-PEND",
            source_warehouse=self.source_wh,
            destination_warehouse=self.unit_wh,
        )
        from django.core.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            deliver_dispatch(pending, received_by="X", captured_by=self.user)

    def test_delivery_marks_requisition_fulfilled(self):
        deliver_dispatch(self.dispatch, received_by="Ana", captured_by=self.user)
        req = self.dispatch.pick_list.requisition
        req.refresh_from_db()
        self.assertEqual(req.status, SupplyRequisition.Status.FULFILLED)

    def test_delivered_at_defaults_when_omitted(self):
        before = timezone.now()
        deliver_dispatch(self.dispatch, received_by="Ana", captured_by=self.user)
        self.dispatch.refresh_from_db()
        self.assertGreaterEqual(self.dispatch.delivered_at, before)
