"""Workflow + stock-ledger operations for the concession logistics chain.

Every physical movement of goods is recorded on the **existing**
``pharmacy.StockMovement`` append-only ledger — this module never mutates
``StockItem.quantity`` directly and never introduces its own stock table.

Ledger convention (see assumptions in TDD_LOG.md):
  * dispatch  → StockMovement(quantity < 0) on the source lot ("out")
  * delivery  → StockMovement(quantity > 0) on the destination lot ("in")
Both legs use ``movement_type="transfer"`` (warehouse → client unit is a
transfer of custody) with a ``reference`` of ``concession-dispatch:<pk>``.
"""

from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .logistics_models import (
    Dispatch,
    DispatchDiscrepancy,
    DispatchItem,
    PickItem,
    PickList,
    ProofOfDelivery,
    SupplyRequisition,
)

MOVEMENT_TYPE = "transfer"


def _ref(dispatch: Dispatch) -> str:
    return f"concession-dispatch:{dispatch.pk}"


# ─── Requisition ──────────────────────────────────────────────────────────────


def submit_requisition(requisition: SupplyRequisition) -> SupplyRequisition:
    """DRAFT → SUBMITTED."""
    if requisition.status != SupplyRequisition.Status.DRAFT:
        raise ValidationError("Only a DRAFT requisition can be submitted.")
    if not requisition.items.exists():
        raise ValidationError("Cannot submit a requisition with no items.")
    requisition.status = SupplyRequisition.Status.SUBMITTED
    requisition.submitted_at = timezone.now()
    requisition.save(update_fields=["status", "submitted_at", "updated_at"])
    return requisition


def approve_requisition(requisition: SupplyRequisition) -> SupplyRequisition:
    """SUBMITTED → APPROVED."""
    if requisition.status != SupplyRequisition.Status.SUBMITTED:
        raise ValidationError("Only a SUBMITTED requisition can be approved.")
    requisition.status = SupplyRequisition.Status.APPROVED
    requisition.approved_at = timezone.now()
    requisition.save(update_fields=["status", "approved_at", "updated_at"])
    return requisition


# ─── Pick ─────────────────────────────────────────────────────────────────────


@transaction.atomic
def create_pick_list(requisition: SupplyRequisition) -> PickList:
    """Generate a PENDING pick list (+ one PickItem per requisition item) from an
    APPROVED requisition."""
    if requisition.status != SupplyRequisition.Status.APPROVED:
        raise ValidationError("A pick list requires an APPROVED requisition.")
    pick_list = PickList.objects.create(requisition=requisition)
    for req_item in requisition.items.all():
        PickItem.objects.create(
            pick_list=pick_list,
            requisition_item=req_item,
            material=req_item.material,
            quantity=req_item.quantity,
        )
    return pick_list


@transaction.atomic
def pick_item(pick_item_obj: PickItem, *, source_stock_item, picked_qty: Decimal) -> PickItem:
    """Record the picked quantity + chosen source lot for one line."""
    pick_list = pick_item_obj.pick_list
    if pick_list.status == PickList.Status.PENDING:
        pick_list.status = PickList.Status.PICKING
        pick_list.started_at = timezone.now()
        pick_list.save(update_fields=["status", "started_at", "updated_at"])
    pick_item_obj.source_stock_item = source_stock_item
    pick_item_obj.picked_qty = picked_qty
    pick_item_obj.is_picked = True
    pick_item_obj.picked_at = timezone.now()
    pick_item_obj.save(update_fields=["source_stock_item", "picked_qty", "is_picked", "picked_at"])
    if not pick_list.items.filter(is_picked=False).exists():
        pick_list.status = PickList.Status.PICKED
        pick_list.completed_at = timezone.now()
        pick_list.save(update_fields=["status", "completed_at", "updated_at"])
    return pick_item_obj


# ─── Dispatch (out) ───────────────────────────────────────────────────────────


@transaction.atomic
def create_dispatch(
    pick_list: PickList,
    *,
    manifest_code: str,
    source_warehouse,
    destination_warehouse=None,
) -> Dispatch:
    """Build a PENDING dispatch from a fully PICKED pick list.

    One DispatchItem per picked line (only positive picked quantities ship).
    Destination unit is inherited from the requisition's facility.
    """
    if pick_list.status != PickList.Status.PICKED:
        raise ValidationError("Dispatch requires a fully PICKED pick list.")
    dispatch = Dispatch.objects.create(
        manifest_code=manifest_code,
        pick_list=pick_list,
        source_warehouse=source_warehouse,
        destination_facility=pick_list.requisition.requesting_facility,
        destination_warehouse=destination_warehouse,
    )
    for pi in pick_list.items.filter(is_picked=True, picked_qty__gt=Decimal("0")):
        if pi.source_stock_item is None:
            raise ValidationError(
                "A picked line must reference the source stock item before dispatch."
            )
        DispatchItem.objects.create(
            dispatch=dispatch,
            material=pi.material,
            source_stock_item=pi.source_stock_item,
            quantity=pi.picked_qty,
        )
    return dispatch


@transaction.atomic
def ship_dispatch(dispatch: Dispatch, *, performed_by=None) -> Dispatch:
    """PENDING → IN_TRANSIT, writing an OUT movement per item that DEDUCTS the
    source-warehouse stock on the pharmacy ledger."""
    from apps.pharmacy.models import StockMovement

    if dispatch.status != Dispatch.Status.PENDING:
        raise ValidationError("Only a PENDING dispatch can be shipped.")
    for item in dispatch.items.select_related("source_stock_item").all():
        StockMovement.objects.create(
            stock_item=item.source_stock_item,
            movement_type=MOVEMENT_TYPE,
            quantity=-item.quantity,
            reference=_ref(dispatch),
            performed_by=performed_by,
        )
    dispatch.status = Dispatch.Status.IN_TRANSIT
    dispatch.shipped_at = timezone.now()
    dispatch.save(update_fields=["status", "shipped_at", "updated_at"])
    return dispatch


# ─── Delivery (in) + proof + discrepancies ────────────────────────────────────


def _resolve_destination_stock_item(dispatch: Dispatch, item: DispatchItem):
    """Get-or-create the unit's on-hand StockItem for this material/lot at the
    destination warehouse — reusing pharmacy stock, never a new table."""
    from apps.pharmacy.models import StockItem

    src = item.source_stock_item
    stock_item, _ = StockItem.objects.get_or_create(
        material=item.material,
        lot_number=src.lot_number if src else "",
        expiry_date=src.expiry_date if src else None,
        warehouse=dispatch.destination_warehouse,
        defaults={"quantity": Decimal("0")},
    )
    return stock_item


@transaction.atomic
def deliver_dispatch(
    dispatch: Dispatch,
    *,
    received_by: str,
    delivered_at=None,
    signature_ref: str = "",
    geo_lat=None,
    geo_lng=None,
    captured_by=None,
    discrepancies: list[dict] | None = None,
) -> ProofOfDelivery:
    """IN_TRANSIT → DELIVERED.

    Captures an immutable ProofOfDelivery, records any discrepancies, sets each
    item's ``received_qty`` (dispatched minus MISSING/DAMAGED, plus EXTRA), and
    writes an IN movement that ADDS the received quantity to the destination
    unit's stock on the pharmacy ledger.

    ``discrepancies`` items: ``{"type", "material" | "dispatch_item", "quantity",
    "notes"?}``.
    """
    from apps.pharmacy.models import StockMovement

    if dispatch.status != Dispatch.Status.IN_TRANSIT:
        raise ValidationError("Only an IN_TRANSIT dispatch can be delivered.")

    delivered_at = delivered_at or timezone.now()
    proof = ProofOfDelivery.objects.create(
        dispatch=dispatch,
        received_by=received_by,
        signature_ref=signature_ref,
        geo_lat=geo_lat,
        geo_lng=geo_lng,
        delivered_at=delivered_at,
        captured_by=captured_by,
    )

    # Persist discrepancies and index adjustments by dispatch item.
    adjustments: dict[str, Decimal] = {}
    for disc in discrepancies or []:
        d_item = disc.get("dispatch_item")
        material = disc.get("material") or (d_item.material if d_item else None)
        if material is None:
            raise ValidationError("A discrepancy requires a material.")
        if d_item is None:
            d_item = dispatch.items.filter(material=material).first()
        qty = Decimal(str(disc["quantity"]))
        DispatchDiscrepancy.objects.create(
            dispatch=dispatch,
            dispatch_item=d_item,
            type=disc["type"],
            material=material,
            quantity=qty,
            notes=disc.get("notes", ""),
            reported_by=captured_by,
        )
        if d_item is not None:
            signed = qty if disc["type"] == DispatchDiscrepancy.Type.EXTRA else -qty
            adjustments[str(d_item.pk)] = adjustments.get(str(d_item.pk), Decimal("0")) + signed

    for item in dispatch.items.select_related("source_stock_item").all():
        received = item.quantity + adjustments.get(str(item.pk), Decimal("0"))
        if received < Decimal("0"):
            received = Decimal("0")
        item.received_qty = received
        item.save(update_fields=["received_qty"])
        if dispatch.destination_warehouse is not None and received > Decimal("0"):
            dest_item = _resolve_destination_stock_item(dispatch, item)
            StockMovement.objects.create(
                stock_item=dest_item,
                movement_type=MOVEMENT_TYPE,
                quantity=received,
                reference=_ref(dispatch),
                performed_by=captured_by,
            )

    dispatch.status = Dispatch.Status.DELIVERED
    dispatch.delivered_at = delivered_at
    dispatch.save(update_fields=["status", "delivered_at", "updated_at"])

    # Mark the originating requisition fulfilled.
    req = dispatch.pick_list.requisition
    if req.status == SupplyRequisition.Status.APPROVED:
        req.status = SupplyRequisition.Status.FULFILLED
        req.save(update_fields=["status", "updated_at"])

    return proof


__all__ = [
    "submit_requisition",
    "approve_requisition",
    "create_pick_list",
    "pick_item",
    "create_dispatch",
    "ship_dispatch",
    "deliver_dispatch",
]
