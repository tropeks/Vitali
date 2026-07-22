from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.governance.models import ApprovalRequest
from apps.governance.services import ApprovalService

from ..models import InventoryCount, StockItem, StockMovement, StockTransfer


class InventoryService:
    @staticmethod
    @transaction.atomic
    def submit(inventory: InventoryCount, actor):
        inventory = InventoryCount.objects.select_for_update().get(pk=inventory.pk)
        if inventory.status != InventoryCount.Status.DRAFT or not inventory.lines.exists():
            raise ValidationError("Inventário vazio ou já submetido.")
        for line in inventory.lines.select_related("stock_item"):
            if line.stock_item.warehouse_id != inventory.warehouse_id:
                raise ValidationError("Todos os lotes devem pertencer ao almoxarifado contado.")
            line.system_quantity_snapshot = line.stock_item.quantity
            line.save(update_fields=("system_quantity_snapshot",))
        approval = ApprovalService.create(
            requested_by=actor,
            workflow_key="stock.inventory_adjustment",
            reference_type="inventory_count",
            reference_id=str(inventory.pk),
            title=f"Ajuste do inventário {inventory.pk}",
            step_permissions=["pharmacy.inventory_approve"],
            context={"warehouse_id": str(inventory.warehouse_id)},
        )
        inventory.approval = approval
        inventory.status = InventoryCount.Status.SUBMITTED
        inventory.save(update_fields=("approval", "status"))
        return inventory

    @staticmethod
    @transaction.atomic
    def decide(inventory: InventoryCount, actor, approve: bool, note=""):
        # `approval` is nullable until submission; joining it here creates an
        # outer join that PostgreSQL refuses to lock with FOR UPDATE.
        inventory = InventoryCount.objects.select_for_update().get(pk=inventory.pk)
        if inventory.status != InventoryCount.Status.SUBMITTED:
            raise ValidationError("Inventário não está aguardando aprovação.")
        approval = ApprovalService.decide(
            approval_id=inventory.approval_id, actor=actor, approve=approve, note=note
        )
        if approval.status == ApprovalRequest.Status.REJECTED:
            inventory.status = InventoryCount.Status.REJECTED
        elif approval.status == ApprovalRequest.Status.APPROVED:
            for line in inventory.lines.select_related("stock_item"):
                current = StockItem.objects.select_for_update().get(pk=line.stock_item_id)
                delta = line.counted_quantity - current.quantity
                if delta:
                    StockMovement.objects.create(
                        stock_item=current,
                        movement_type="adjustment",
                        quantity=delta,
                        reference=str(inventory.pk),
                        notes="Contagem cega aprovada",
                        performed_by=actor,
                    )
            inventory.status = InventoryCount.Status.APPROVED
            inventory.applied_at = timezone.now()
        inventory.save(update_fields=("status", "applied_at"))
        return inventory


class TransferService:
    @staticmethod
    @transaction.atomic
    def ship(transfer: StockTransfer, actor):
        transfer = StockTransfer.objects.select_for_update().get(pk=transfer.pk)
        if transfer.status != StockTransfer.Status.DRAFT or not transfer.lines.exists():
            raise ValidationError("Transferência vazia ou já expedida.")
        for line in transfer.lines.select_related("source_item"):
            if line.source_item.warehouse_id != transfer.origin_id or line.quantity <= 0:
                raise ValidationError("Lote/quantidade incompatível com a origem.")
            StockMovement.objects.create(
                stock_item=line.source_item,
                movement_type="transfer",
                quantity=-line.quantity,
                reference=f"transfer:{transfer.pk}:out",
                performed_by=actor,
            )
        transfer.status, transfer.shipped_at = StockTransfer.Status.IN_TRANSIT, timezone.now()
        transfer.save(update_fields=("status", "shipped_at"))
        return transfer

    @staticmethod
    @transaction.atomic
    def accept(transfer: StockTransfer, actor):
        transfer = StockTransfer.objects.select_for_update().get(pk=transfer.pk)
        if transfer.status != StockTransfer.Status.IN_TRANSIT:
            raise ValidationError("Transferência não está em trânsito.")
        for line in transfer.lines.select_related("source_item"):
            source = line.source_item
            destination, _ = StockItem.objects.get_or_create(
                drug=source.drug,
                material=source.material,
                lot_number=source.lot_number,
                expiry_date=source.expiry_date,
                warehouse=transfer.destination,
                defaults={"min_stock": Decimal("0"), "status": source.status},
            )
            StockMovement.objects.create(
                stock_item=destination,
                movement_type="transfer",
                quantity=line.quantity,
                reference=f"transfer:{transfer.pk}:in",
                performed_by=actor,
            )
            line.destination_item = destination
            line.save(update_fields=("destination_item",))
        transfer.status, transfer.accepted_by, transfer.accepted_at = (
            StockTransfer.Status.ACCEPTED,
            actor,
            timezone.now(),
        )
        transfer.save(update_fields=("status", "accepted_by", "accepted_at"))
        return transfer
