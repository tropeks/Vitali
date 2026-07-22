"""Tenant-scoped approval workflow and transactional outbox primitives."""

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.core.fields import EncryptedJSONField


class ApprovalRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pendente"
        APPROVED = "approved", "Aprovada"
        REJECTED = "rejected", "Rejeitada"
        CANCELLED = "cancelled", "Cancelada"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workflow_key = models.CharField(max_length=100, db_index=True)
    reference_type = models.CharField(max_length=100)
    reference_id = models.CharField(max_length=100)
    title = models.CharField(max_length=255)
    context = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="approval_requests"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("status", "created_at"), name="gov_approval_status_created"),
            models.Index(fields=("reference_type", "reference_id"), name="gov_approval_reference"),
        ]

    def __str__(self):
        return f"{self.workflow_key}: {self.title} ({self.status})"


class ApprovalStep(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pendente"
        APPROVED = "approved", "Aprovada"
        REJECTED = "rejected", "Rejeitada"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    approval = models.ForeignKey(ApprovalRequest, on_delete=models.CASCADE, related_name="steps")
    sequence = models.PositiveSmallIntegerField()
    permission_required = models.CharField(max_length=100)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="approval_steps_decided",
    )
    decision_note = models.TextField(blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("sequence",)
        constraints = [
            models.UniqueConstraint(
                fields=("approval", "sequence"), name="gov_unique_approval_sequence"
            )
        ]

    def __str__(self):
        return f"{self.approval_id} / etapa {self.sequence} ({self.status})"


class OutboxQuerySet(models.QuerySet):
    MUTABLE_FIELDS = {
        "status",
        "attempts",
        "available_at",
        "last_error",
        "locked_at",
        "published_at",
        "replay_count",
    }

    def delete(self):
        raise ValidationError("Eventos da outbox não podem ser excluídos.")

    def update(self, **kwargs):
        immutable = set(kwargs) - self.MUTABLE_FIELDS
        if immutable:
            raise ValidationError(
                f"Conteúdo de eventos da outbox é imutável: {', '.join(sorted(immutable))}."
            )
        return super().update(**kwargs)


class DomainEventOutbox(models.Model):
    """Immutable event envelope; only delivery metadata may change."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pendente"
        PROCESSING = "processing", "Processando"
        PUBLISHED = "published", "Publicado"
        FAILED = "failed", "Falhou"
        DEAD = "dead", "Esgotado"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    idempotency_key = models.CharField(max_length=255, unique=True)
    aggregate_type = models.CharField(max_length=100)
    aggregate_id = models.CharField(max_length=100)
    event_type = models.CharField(max_length=150, db_index=True)
    payload = models.JSONField()
    occurred_at = models.DateTimeField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    attempts = models.PositiveIntegerField(default=0)
    replay_count = models.PositiveIntegerField(default=0)
    available_at = models.DateTimeField()
    last_error = models.TextField(blank=True)
    locked_at = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = OutboxQuerySet.as_manager()

    class Meta:
        ordering = ("created_at",)
        indexes = [
            models.Index(fields=("status", "available_at"), name="gov_outbox_dispatch"),
            models.Index(fields=("aggregate_type", "aggregate_id"), name="gov_outbox_aggregate"),
        ]

    def __str__(self):
        return f"{self.event_type} / {self.aggregate_type}:{self.aggregate_id}"

    _IMMUTABLE_FIELDS = (
        "idempotency_key",
        "aggregate_type",
        "aggregate_id",
        "event_type",
        "payload",
        "occurred_at",
    )

    def save(self, *args, **kwargs):
        if self.pk and not self._state.adding:
            original = type(self).objects.only(*self._IMMUTABLE_FIELDS).get(pk=self.pk)
            changed = [
                name
                for name in self._IMMUTABLE_FIELDS
                if getattr(self, name) != getattr(original, name)
            ]
            if changed:
                raise ValidationError(
                    f"Conteúdo de eventos da outbox é imutável: {', '.join(changed)}."
                )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Eventos da outbox não podem ser excluídos.")


class IntegrationInbox(models.Model):
    """Durable, encrypted boundary for protocol-neutral inbound messages."""

    class Status(models.TextChoices):
        RECEIVED = "received", "Recebida"
        PROCESSING = "processing", "Processando"
        COMPLETED = "completed", "Concluída"
        FAILED = "failed", "Falhou"
        DEAD = "dead", "Esgotada"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    idempotency_key = models.CharField(max_length=255, unique=True)
    source = models.CharField(max_length=100, db_index=True)
    message_type = models.CharField(max_length=150, db_index=True)
    correlation_id = models.CharField(max_length=255, blank=True, db_index=True)
    payload = EncryptedJSONField()
    headers = EncryptedJSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.RECEIVED)
    attempts = models.PositiveIntegerField(default=0)
    replay_count = models.PositiveIntegerField(default=0)
    available_at = models.DateTimeField()
    locked_at = models.DateTimeField(null=True, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    received_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-received_at",)
        indexes = [
            models.Index(fields=("status", "available_at"), name="gov_inbox_dispatch"),
            models.Index(fields=("source", "message_type"), name="gov_inbox_source_type"),
        ]

    def __str__(self):
        return f"{self.source}/{self.message_type} ({self.status})"
