"""Sprint M1-S3 — order-set publishing service (governance approval reuse).

Publishing an ``OrderSet`` is maker-checker gated through
``governance.ApprovalService``: the author submits a version for approval (which
mints an ``ApprovalRequest`` + one ``ApprovalStep`` per required alçada) and, once
a different actor approves it, :meth:`OrderSetService.sync_from_approval` freezes
the version as ``APPROVED``. A rejection returns it to ``DRAFT`` for revision.
"""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.governance.models import ApprovalRequest
from apps.governance.services import ApprovalService

from ..reconciliation_models import OrderSet

DEFAULT_APPROVAL_PERMISSION = "emr.order_set_approve"


class OrderSetService:
    WORKFLOW_KEY = "emr.order_set_publish"

    @staticmethod
    @transaction.atomic
    def submit(*, order_set: OrderSet, requested_by, step_permissions=None):
        """Submit a DRAFT order set for approval; returns the ApprovalRequest."""
        if order_set.status != OrderSet.Status.DRAFT:
            raise ValidationError("Apenas um order set em rascunho pode ser submetido.")
        if not order_set.items.exists():
            raise ValidationError("Um order set sem itens não pode ser submetido.")
        approval = ApprovalService.create(
            requested_by=requested_by,
            workflow_key=OrderSetService.WORKFLOW_KEY,
            reference_type="order_set",
            reference_id=str(order_set.pk),
            title=f"Publicação order set {order_set.name} v{order_set.version}",
            step_permissions=step_permissions or [DEFAULT_APPROVAL_PERMISSION],
            context={"key": order_set.key, "version": order_set.version},
        )
        order_set.approval = approval
        order_set.status = OrderSet.Status.PENDING_APPROVAL
        order_set.save(update_fields=["approval", "status", "updated_at"])
        return approval

    @staticmethod
    @transaction.atomic
    def sync_from_approval(*, order_set: OrderSet) -> OrderSet:
        """Reconcile the order set's status with its linked approval decision."""
        order_set.refresh_from_db()
        if order_set.status != OrderSet.Status.PENDING_APPROVAL or order_set.approval is None:
            return order_set
        approval = order_set.approval
        if approval.status == ApprovalRequest.Status.APPROVED:
            order_set.status = OrderSet.Status.APPROVED
            order_set.approved_at = timezone.now()
            order_set.save(update_fields=["status", "approved_at", "updated_at"])
        elif approval.status in (
            ApprovalRequest.Status.REJECTED,
            ApprovalRequest.Status.CANCELLED,
        ):
            order_set.status = OrderSet.Status.DRAFT
            order_set.save(update_fields=["status", "updated_at"])
        return order_set

    @staticmethod
    def publish(*, order_set: OrderSet, requested_by, approver, step_permissions=None):
        """Convenience: submit + approve (distinct actors) + freeze. For tooling/tests."""
        approval = OrderSetService.submit(
            order_set=order_set, requested_by=requested_by, step_permissions=step_permissions
        )
        ApprovalService.decide(approval_id=approval.pk, actor=approver, approve=True)
        return OrderSetService.sync_from_approval(order_set=order_set)
