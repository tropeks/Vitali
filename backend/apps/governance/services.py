"""Transactional services for approvals and domain events."""

from dataclasses import dataclass
from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.core.models import AuditLog

from .models import ApprovalRequest, ApprovalStep, DomainEventOutbox, IntegrationInbox


def _require(user, permission: str) -> None:
    if not user or not user.has_role_permission(permission):
        raise PermissionDenied(f"Permissão necessária: {permission}.")


def _audit(user, action: str, resource, data: dict) -> None:
    AuditLog.objects.create(
        user=user,
        action=action,
        resource_type="approval_request",
        resource_id=str(resource.pk),
        new_data=data,
    )


def _emit_approval_event(approval, event_type: str, suffix: str) -> None:
    OutboxService.append(
        EventEnvelope(
            aggregate_type="approval_request",
            aggregate_id=str(approval.pk),
            event_type=event_type,
            payload={
                "approval_id": str(approval.pk),
                "workflow_key": approval.workflow_key,
                "reference_type": approval.reference_type,
                "reference_id": approval.reference_id,
                "status": approval.status,
            },
            idempotency_key=f"approval:{approval.pk}:{suffix}",
        )
    )


class ApprovalService:
    @staticmethod
    @transaction.atomic
    def create(
        *,
        requested_by,
        workflow_key: str,
        reference_type: str,
        reference_id: str,
        title: str,
        step_permissions: list[str],
        context: dict | None = None,
    ):
        _require(requested_by, "workflow.request")
        if not step_permissions or any(not permission for permission in step_permissions):
            raise ValidationError("Ao menos uma alçada válida é obrigatória.")
        approval = ApprovalRequest.objects.create(
            workflow_key=workflow_key,
            reference_type=reference_type,
            reference_id=str(reference_id),
            title=title,
            context=context or {},
            requested_by=requested_by,
        )
        ApprovalStep.objects.bulk_create(
            [
                ApprovalStep(
                    approval=approval,
                    sequence=index,
                    permission_required=permission,
                )
                for index, permission in enumerate(step_permissions, start=1)
            ]
        )
        _audit(requested_by, "approval_requested", approval, {"workflow_key": workflow_key})
        _emit_approval_event(approval, "approval.requested", "requested")
        return approval

    @staticmethod
    @transaction.atomic
    def cancel(*, approval_id, actor, note: str = ""):
        _require(actor, "workflow.request")
        approval = ApprovalRequest.objects.select_for_update().get(pk=approval_id)
        if approval.status != ApprovalRequest.Status.PENDING:
            raise ValidationError("Esta solicitação já foi encerrada.")
        if approval.requested_by_id != actor.pk:
            raise PermissionDenied("Somente o solicitante pode cancelar esta solicitação.")
        approval.status = ApprovalRequest.Status.CANCELLED
        approval.decided_at = timezone.now()
        approval.save(update_fields=("status", "decided_at"))
        _audit(actor, "approval_cancelled", approval, {"note": note})
        _emit_approval_event(approval, "approval.cancelled", "cancelled")
        return approval

    @staticmethod
    @transaction.atomic
    def decide(*, approval_id, actor, approve: bool, note: str = ""):
        _require(actor, "workflow.approve")
        approval = ApprovalRequest.objects.select_for_update().get(pk=approval_id)
        if approval.status != ApprovalRequest.Status.PENDING:
            raise ValidationError("Esta solicitação já foi encerrada.")
        if approval.requested_by_id == actor.pk:
            raise PermissionDenied("Maker-checker: o solicitante não pode aprovar ou rejeitar.")
        step = approval.steps.select_for_update().filter(status=ApprovalStep.Status.PENDING).first()
        if step is None:
            raise ValidationError("A solicitação não possui etapa pendente.")
        _require(actor, step.permission_required)
        now = timezone.now()
        step.status = ApprovalStep.Status.APPROVED if approve else ApprovalStep.Status.REJECTED
        step.decided_by = actor
        step.decision_note = note
        step.decided_at = now
        step.save(update_fields=("status", "decided_by", "decision_note", "decided_at"))
        if not approve:
            approval.status = ApprovalRequest.Status.REJECTED
            approval.decided_at = now
        elif not approval.steps.filter(status=ApprovalStep.Status.PENDING).exists():
            approval.status = ApprovalRequest.Status.APPROVED
            approval.decided_at = now
        approval.save(update_fields=("status", "decided_at"))
        _audit(
            actor,
            "approval_step_approved" if approve else "approval_step_rejected",
            approval,
            {"sequence": step.sequence, "note": note, "status": approval.status},
        )
        event_type = (
            "approval.approved"
            if approval.status == ApprovalRequest.Status.APPROVED
            else "approval.rejected"
            if approval.status == ApprovalRequest.Status.REJECTED
            else "approval.step_approved"
        )
        _emit_approval_event(approval, event_type, f"step:{step.sequence}:{step.status}")
        return approval


@dataclass(frozen=True)
class EventEnvelope:
    aggregate_type: str
    aggregate_id: str
    event_type: str
    payload: dict
    idempotency_key: str


class OutboxService:
    @staticmethod
    def append(event: EventEnvelope) -> tuple[DomainEventOutbox, bool]:
        now = timezone.now()
        row, created = DomainEventOutbox.objects.get_or_create(
            idempotency_key=event.idempotency_key,
            defaults={
                "aggregate_type": event.aggregate_type,
                "aggregate_id": str(event.aggregate_id),
                "event_type": event.event_type,
                "payload": event.payload,
                "occurred_at": now,
                "available_at": now,
            },
        )
        if not created and (
            row.aggregate_type != event.aggregate_type
            or row.aggregate_id != str(event.aggregate_id)
            or row.event_type != event.event_type
            or row.payload != event.payload
        ):
            raise ValidationError("A chave de idempotência já pertence a outro evento.")
        return row, created

    @staticmethod
    @transaction.atomic
    def claim_batch(*, limit: int = 100, lock_timeout=None) -> list[DomainEventOutbox]:
        now = timezone.now()
        lock_timeout = lock_timeout or timedelta(minutes=10)
        rows = list(
            DomainEventOutbox.objects.select_for_update(skip_locked=True)
            .filter(available_at__lte=now)
            .filter(
                Q(status__in=(DomainEventOutbox.Status.PENDING, DomainEventOutbox.Status.FAILED))
                | Q(
                    status=DomainEventOutbox.Status.PROCESSING,
                    locked_at__lt=now - lock_timeout,
                )
            )
            .order_by("created_at")[:limit]
        )
        for row in rows:
            row.status = DomainEventOutbox.Status.PROCESSING
            row.attempts += 1
            row.locked_at = now
            row.save(update_fields=("status", "attempts", "locked_at"))
        return rows

    @staticmethod
    def mark_published(event: DomainEventOutbox) -> None:
        event.status = DomainEventOutbox.Status.PUBLISHED
        event.published_at = timezone.now()
        event.locked_at = None
        event.last_error = ""
        event.save(update_fields=("status", "published_at", "locked_at", "last_error"))

    @staticmethod
    def mark_failed(
        event: DomainEventOutbox, *, error: str, retry_at, max_attempts: int = 10
    ) -> None:
        event.status = (
            DomainEventOutbox.Status.DEAD
            if event.attempts >= max_attempts
            else DomainEventOutbox.Status.FAILED
        )
        event.last_error = error[:4000]
        event.available_at = retry_at
        event.locked_at = None
        event.save(update_fields=("status", "last_error", "available_at", "locked_at"))

    @staticmethod
    def replay(event: DomainEventOutbox) -> DomainEventOutbox:
        if event.status not in (DomainEventOutbox.Status.FAILED, DomainEventOutbox.Status.DEAD):
            raise ValidationError("Somente eventos falhos ou esgotados podem ser reenfileirados.")
        event.status = DomainEventOutbox.Status.PENDING
        event.available_at = timezone.now()
        event.locked_at = None
        event.last_error = ""
        event.attempts = 0
        event.replay_count += 1
        event.save(
            update_fields=(
                "status",
                "available_at",
                "locked_at",
                "last_error",
                "attempts",
                "replay_count",
            )
        )
        return event


@dataclass(frozen=True)
class InboxEnvelope:
    source: str
    message_type: str
    payload: dict
    idempotency_key: str
    correlation_id: str = ""
    headers: dict | None = None


class InboxService:
    @staticmethod
    def receive(envelope: InboxEnvelope) -> tuple[IntegrationInbox, bool]:
        now = timezone.now()
        row, created = IntegrationInbox.objects.get_or_create(
            idempotency_key=envelope.idempotency_key,
            defaults={
                "source": envelope.source,
                "message_type": envelope.message_type,
                "correlation_id": envelope.correlation_id,
                "payload": envelope.payload,
                "headers": envelope.headers or {},
                "available_at": now,
            },
        )
        if not created and (
            row.source != envelope.source
            or row.message_type != envelope.message_type
            or row.correlation_id != envelope.correlation_id
            or row.payload != envelope.payload
            or row.headers != (envelope.headers or {})
        ):
            raise ValidationError("A chave de idempotência já pertence a outra mensagem.")
        return row, created

    @staticmethod
    @transaction.atomic
    def claim_batch(*, limit: int = 100, lock_timeout=None) -> list[IntegrationInbox]:
        now = timezone.now()
        lock_timeout = lock_timeout or timedelta(minutes=10)
        rows = list(
            IntegrationInbox.objects.select_for_update(skip_locked=True)
            .filter(available_at__lte=now)
            .filter(
                Q(status__in=(IntegrationInbox.Status.RECEIVED, IntegrationInbox.Status.FAILED))
                | Q(
                    status=IntegrationInbox.Status.PROCESSING,
                    locked_at__lt=now - lock_timeout,
                )
            )
            .order_by("received_at")[:limit]
        )
        for row in rows:
            row.status = IntegrationInbox.Status.PROCESSING
            row.attempts += 1
            row.locked_at = now
            row.save(update_fields=("status", "attempts", "locked_at", "updated_at"))
        return rows

    @staticmethod
    def mark_completed(message: IntegrationInbox) -> None:
        message.status = IntegrationInbox.Status.COMPLETED
        message.processed_at = timezone.now()
        message.locked_at = None
        message.last_error = ""
        message.save(
            update_fields=("status", "processed_at", "locked_at", "last_error", "updated_at")
        )

    @staticmethod
    def mark_failed(message: IntegrationInbox, *, error: str, retry_at, max_attempts=10) -> None:
        message.status = (
            IntegrationInbox.Status.DEAD
            if message.attempts >= max_attempts
            else IntegrationInbox.Status.FAILED
        )
        message.last_error = error[:4000]
        message.available_at = retry_at
        message.locked_at = None
        message.save(
            update_fields=("status", "last_error", "available_at", "locked_at", "updated_at")
        )

    @staticmethod
    def replay(message: IntegrationInbox) -> IntegrationInbox:
        if message.status not in (IntegrationInbox.Status.FAILED, IntegrationInbox.Status.DEAD):
            raise ValidationError("Somente mensagens falhas ou esgotadas podem ser reprocessadas.")
        message.status = IntegrationInbox.Status.RECEIVED
        message.available_at = timezone.now()
        message.locked_at = None
        message.last_error = ""
        message.attempts = 0
        message.replay_count += 1
        message.save(
            update_fields=(
                "status",
                "available_at",
                "locked_at",
                "last_error",
                "attempts",
                "replay_count",
                "updated_at",
            )
        )
        return message
