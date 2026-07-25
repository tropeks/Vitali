"""Dedicated-logistics domain models for the diagnostic-concession tier.

The operational chain the operator runs at its own cost:

    SupplyRequisition (unit asks)  →  PickList (warehouse picks)
        →  Dispatch (leaves warehouse, deducts stock)
        →  ProofOfDelivery (+ DispatchDiscrepancy) at the unit (adds stock)

Stock is NEVER duplicated here: quantities-on-hand live in
``pharmacy.StockItem`` and every real movement of goods is written to the
existing append-only ``pharmacy.StockMovement`` ledger (out on dispatch, in on
delivery). This module only owns the *logistics workflow* rows.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from django.db import models

# NB: FKs into pharmacy/organization are same-tenant-schema references, not a
# cross-schema join. We reference by string label to avoid import-time coupling.


class SupplyRequisition(models.Model):
    """A client unit's request for the operator to replenish supplies."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Rascunho"
        SUBMITTED = "submitted", "Enviada"
        APPROVED = "approved", "Aprovada"
        FULFILLED = "fulfilled", "Atendida"
        CANCELLED = "cancelled", "Cancelada"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    requesting_facility = models.ForeignKey(
        "organization.Facility",
        on_delete=models.PROTECT,
        related_name="supply_requisitions",
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True
    )
    requested_by = models.ForeignKey(
        "core.User", on_delete=models.PROTECT, related_name="supply_requisitions"
    )
    notes = models.TextField(blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["requesting_facility", "status"])]

    def __str__(self) -> str:
        return f"Requisição {self.id} — {self.requesting_facility_id} ({self.status})"


class RequisitionItem(models.Model):
    """A single material line on a :class:`SupplyRequisition`."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    requisition = models.ForeignKey(
        SupplyRequisition, on_delete=models.CASCADE, related_name="items"
    )
    material = models.ForeignKey("pharmacy.Material", on_delete=models.PROTECT, related_name="+")
    quantity = models.DecimalField(max_digits=12, decimal_places=3)

    class Meta:
        ordering = ["material__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["requisition", "material"], name="uniq_requisition_material"
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gt=Decimal("0")),
                name="requisition_item_qty_positive",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.quantity} × {self.material_id}"


class PickList(models.Model):
    """Warehouse pick sheet generated from an APPROVED requisition."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pendente"
        PICKING = "picking", "Em separação"
        PICKED = "picked", "Separada"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    requisition = models.OneToOneField(
        SupplyRequisition, on_delete=models.PROTECT, related_name="pick_list"
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"PickList {self.id} ({self.status})"


class PickItem(models.Model):
    """One material line to pick; ``picked_qty`` is captured during scanning."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pick_list = models.ForeignKey(PickList, on_delete=models.CASCADE, related_name="items")
    requisition_item = models.OneToOneField(
        RequisitionItem, on_delete=models.PROTECT, related_name="pick_item"
    )
    material = models.ForeignKey("pharmacy.Material", on_delete=models.PROTECT, related_name="+")
    # Source lot chosen by the picker; the dispatch out-movement is written here.
    source_stock_item = models.ForeignKey(
        "pharmacy.StockItem",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    picked_qty = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal("0"))
    is_picked = models.BooleanField(default=False, db_index=True)
    picked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["material__name"]
        indexes = [models.Index(fields=["pick_list", "is_picked"])]

    def __str__(self) -> str:
        return f"{self.picked_qty}/{self.quantity} × {self.material_id}"


class Dispatch(models.Model):
    """Goods leaving the source warehouse toward the requesting unit."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pendente"
        IN_TRANSIT = "in_transit", "Em trânsito"
        DELIVERED = "delivered", "Entregue"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    manifest_code = models.CharField(max_length=64, unique=True, db_index=True)
    pick_list = models.OneToOneField(PickList, on_delete=models.PROTECT, related_name="dispatch")
    # Warehouse the goods leave from (stock deducted here on dispatch).
    source_warehouse = models.ForeignKey(
        "pharmacy.Warehouse", on_delete=models.PROTECT, related_name="concession_dispatches"
    )
    # Destination unit (business requester) + its local receiving warehouse
    # where delivered goods land. See module docstring: Facility is the unit,
    # its on-hand stock is a pharmacy StockItem at destination_warehouse.
    destination_facility = models.ForeignKey(
        "organization.Facility",
        on_delete=models.PROTECT,
        related_name="concession_dispatches",
    )
    destination_warehouse = models.ForeignKey(
        "pharmacy.Warehouse",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="concession_inbound_dispatches",
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    shipped_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["destination_facility", "status"]),
            models.Index(fields=["manifest_code"]),
        ]

    def __str__(self) -> str:
        return f"Dispatch {self.manifest_code} ({self.status})"


class DispatchItem(models.Model):
    """A material line on a dispatch; ``received_qty`` filled at delivery."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    dispatch = models.ForeignKey(Dispatch, on_delete=models.CASCADE, related_name="items")
    material = models.ForeignKey("pharmacy.Material", on_delete=models.PROTECT, related_name="+")
    source_stock_item = models.ForeignKey(
        "pharmacy.StockItem", on_delete=models.PROTECT, related_name="+"
    )
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    received_qty = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)

    class Meta:
        ordering = ["material__name"]
        indexes = [models.Index(fields=["dispatch"])]

    def __str__(self) -> str:
        return f"{self.quantity} × {self.material_id}"


class ProofOfDelivery(models.Model):
    """Append-only proof captured at the unit (QR / signature / GPS).

    Immutable after creation: ``save()`` refuses updates, ``delete()`` raises —
    same contract as ``pharmacy.StockMovement``.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    dispatch = models.OneToOneField(
        Dispatch, on_delete=models.PROTECT, related_name="proof_of_delivery"
    )
    received_by = models.CharField(max_length=200)
    signature_ref = models.CharField(max_length=300, blank=True)
    geo_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    geo_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    delivered_at = models.DateTimeField()
    captured_by = models.ForeignKey(
        "core.User", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Comprovante de entrega"
        verbose_name_plural = "Comprovantes de entrega"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError("ProofOfDelivery is append-only — a proof cannot be modified.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("ProofOfDelivery is append-only — proofs cannot be deleted.")

    def __str__(self) -> str:
        return f"POD {self.dispatch_id} — {self.received_by}"


class DispatchDiscrepancy(models.Model):
    """A mismatch recorded at delivery against a dispatched material."""

    class Type(models.TextChoices):
        MISSING = "missing", "Faltante"
        DAMAGED = "damaged", "Avariado"
        EXTRA = "extra", "Excedente"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    dispatch = models.ForeignKey(Dispatch, on_delete=models.CASCADE, related_name="discrepancies")
    dispatch_item = models.ForeignKey(
        DispatchItem,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="discrepancies",
    )
    type = models.CharField(max_length=20, choices=Type.choices, db_index=True)
    material = models.ForeignKey("pharmacy.Material", on_delete=models.PROTECT, related_name="+")
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    notes = models.TextField(blank=True)
    reported_by = models.ForeignKey(
        "core.User", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["dispatch", "type"])]

    def __str__(self) -> str:
        return f"{self.get_type_display()} {self.quantity} × {self.material_id}"


__all__ = [
    "SupplyRequisition",
    "RequisitionItem",
    "PickList",
    "PickItem",
    "Dispatch",
    "DispatchItem",
    "ProofOfDelivery",
    "DispatchDiscrepancy",
]
