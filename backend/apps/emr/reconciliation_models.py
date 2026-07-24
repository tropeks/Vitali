"""Sprint M1-S3 — Medication reconciliation + versioned/approved order sets.

New TENANT models (kept out of the already-large ``models.py`` and re-exported
via a single ``from .reconciliation_models import *`` at the end of that module):

S3-T1 — reconciliation
  * ``MedicationReconciliation`` — the per-encounter reconciliation event
    (admission/discharge), authored and status-tracked. Once ``complete()``-d it
    is frozen: its decision items become immutable (append-only audit of what was
    decided at that clinical moment).
  * ``MedicationReconciliationItem`` — one decision line: a medication from the
    patient's continuous-use/home list, the action taken (continue/stop/modify/
    start), an optional link to the resulting ``PrescriptionItem`` and a reason.

S3-T2 — order sets
  * ``OrderSet`` / ``OrderSetItem`` — a versioned, approval-gated bundle of order
    templates (medication/lab/imaging). Publishing reuses
    ``governance.ApprovalRequest`` (maker-checker). Once APPROVED a version is
    frozen; changes require a NEW version. Applying an approved order set to an
    encounter instantiates its items into concrete ``AppliedOrder`` rows grouped
    by an ``OrderSetApplication``.

Tenant-scoping is implicit (django-tenants routes every query to the caller's
schema). Cross-schema FK integrity is not enforced by PostgreSQL, but every FK
here is same-schema (tenant → tenant) except the audited link to the SHARED
``governance.ApprovalRequest`` (also a tenant model), so plain FKs are safe.
"""

import uuid

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from .models import Encounter, Patient, PrescriptionItem


class MedicationReconciliation(models.Model):
    """A medication reconciliation performed at a clinical transition.

    Captures, per encounter and moment (admission/discharge), the decision taken
    for each of the patient's continuous-use medications. Draft while decisions
    are being recorded; once completed it is frozen (immutable decision trail).
    """

    class Moment(models.TextChoices):
        ADMISSION = "admission", "Admissão"
        DISCHARGE = "discharge", "Alta"
        TRANSFER = "transfer", "Transferência"

    class Status(models.TextChoices):
        DRAFT = "draft", "Rascunho"
        COMPLETED = "completed", "Concluída"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey(
        Patient, on_delete=models.PROTECT, related_name="medication_reconciliations"
    )
    encounter = models.ForeignKey(
        Encounter, on_delete=models.PROTECT, related_name="medication_reconciliations"
    )
    moment = models.CharField(max_length=20, choices=Moment.choices, db_index=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True
    )
    author = models.ForeignKey(
        "core.User", on_delete=models.PROTECT, related_name="medication_reconciliations"
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Reconciliação medicamentosa"
        verbose_name_plural = "Reconciliações medicamentosas"
        indexes = [
            models.Index(fields=["encounter", "moment"]),
            models.Index(fields=["patient", "status"]),
        ]

    @property
    def is_completed(self) -> bool:
        return self.status == self.Status.COMPLETED

    def complete(self):
        """Freeze the reconciliation. Idempotency guard: cannot re-complete."""
        if self.status == self.Status.COMPLETED:
            raise ValidationError("Reconciliação já concluída.")
        self.status = self.Status.COMPLETED
        self.completed_at = timezone.now()
        self.save(update_fields=["status", "completed_at", "updated_at"])

    def __str__(self):
        return f"Reconciliação {self.get_moment_display()} — {self.patient} ({self.status})"


class MedicationReconciliationItem(models.Model):
    """One reconciliation decision for a single continuous-use medication."""

    class Action(models.TextChoices):
        CONTINUE = "continue", "Manter"
        STOP = "stop", "Suspender"
        MODIFY = "modify", "Modificar"
        START = "start", "Iniciar"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reconciliation = models.ForeignKey(
        MedicationReconciliation, on_delete=models.CASCADE, related_name="items"
    )
    # The continuous-use / home medication under review (free text — the home-med
    # list is not a governed catalog here). ``prescription_item`` optionally links
    # the resulting active order once the decision instantiates one.
    medication_name = models.CharField(max_length=300)
    home_dosage = models.CharField(
        max_length=200, blank=True, help_text="Posologia de uso contínuo em casa."
    )
    action = models.CharField(max_length=20, choices=Action.choices, db_index=True)
    prescription_item = models.ForeignKey(
        PrescriptionItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reconciliation_items",
        help_text="Ordem resultante (quando a decisão instancia/altera uma prescrição).",
    )
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def _guard_frozen(self):
        if self.reconciliation_id and self.reconciliation.is_completed:
            raise ValidationError(
                "Reconciliação concluída é imutável; as decisões não podem ser alteradas."
            )

    def save(self, *args, **kwargs):
        self._guard_frozen()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self._guard_frozen()
        return super().delete(*args, **kwargs)

    def __str__(self):
        return f"{self.medication_name} — {self.get_action_display()}"


class OrderSet(models.Model):
    """A versioned, approval-gated bundle of order templates.

    ``key`` identifies the logical order set across versions; ``version`` bumps on
    each revision. Only a ``DRAFT`` may be edited or submitted; once ``APPROVED``
    (via ``governance.ApprovalRequest``) the version is frozen — content changes
    require a new version (:meth:`create_new_version`). Only an ``APPROVED`` order
    set may be applied to an encounter.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Rascunho"
        PENDING_APPROVAL = "pending_approval", "Aguardando aprovação"
        APPROVED = "approved", "Aprovado"
        ARCHIVED = "archived", "Arquivado"

    # Content fields that are immutable once the version is APPROVED.
    FROZEN_FIELDS = ("key", "name", "version", "description")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    key = models.SlugField(max_length=100, db_index=True, help_text="Identificador lógico estável.")
    name = models.CharField(max_length=200)
    version = models.PositiveSmallIntegerField(default=1)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True
    )
    description = models.TextField(blank=True)
    approval = models.ForeignKey(
        "governance.ApprovalRequest",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_by = models.ForeignKey(
        "core.User", on_delete=models.PROTECT, related_name="order_sets_created"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["key", "-version"]
        verbose_name = "Order set"
        verbose_name_plural = "Order sets"
        constraints = [
            models.UniqueConstraint(fields=["key", "version"], name="emr_orderset_key_version"),
        ]

    def save(self, *args, **kwargs):
        # Frozen-after-approval: block content edits once the DB row is APPROVED.
        # Status transitions (e.g. APPROVED→ARCHIVED) and approval bookkeeping stay
        # allowed so archiving/superseding a version still works.
        if self.pk:
            old = (
                type(self).objects.filter(pk=self.pk).values("status", *self.FROZEN_FIELDS).first()
            )
            if old and old["status"] == self.Status.APPROVED:
                changed = [f for f in self.FROZEN_FIELDS if old[f] != getattr(self, f)]
                if changed:
                    raise ValidationError(
                        "Order set aprovado é imutável; crie uma nova versão para alterá-lo."
                    )
        super().save(*args, **kwargs)

    @property
    def is_approved(self) -> bool:
        return self.status == self.Status.APPROVED

    @transaction.atomic
    def create_new_version(self, user):
        """Clone this order set (and its items) into a fresh DRAFT with version+1."""
        latest = (
            OrderSet.objects.filter(key=self.key)
            .order_by("-version")
            .values_list("version", flat=True)
            .first()
        )
        new = OrderSet.objects.create(
            key=self.key,
            name=self.name,
            version=(latest or self.version) + 1,
            description=self.description,
            status=self.Status.DRAFT,
            created_by=user,
        )
        OrderSetItem.objects.bulk_create(
            [
                OrderSetItem(
                    order_set=new,
                    order_type=item.order_type,
                    label=item.label,
                    drug_id=item.drug_id,
                    dosage_instructions=item.dosage_instructions,
                    quantity=item.quantity,
                    details=item.details,
                    sequence=item.sequence,
                )
                for item in self.items.all()
            ]
        )
        return new

    @transaction.atomic
    def apply_to_encounter(self, encounter, user):
        """Instantiate this (approved) order set's items as concrete orders."""
        if self.status != self.Status.APPROVED:
            raise ValidationError("Somente um order set aprovado pode ser aplicado a um encontro.")
        application = OrderSetApplication.objects.create(
            order_set=self, encounter=encounter, applied_by=user
        )
        AppliedOrder.objects.bulk_create(
            [
                AppliedOrder(
                    application=application,
                    encounter=encounter,
                    source_item=item,
                    order_type=item.order_type,
                    label=item.label,
                    drug_id=item.drug_id,
                    details=item.details,
                )
                for item in self.items.all().order_by("sequence", "created_at")
            ]
        )
        return application

    def __str__(self):
        return f"{self.name} v{self.version} ({self.status})"


class OrderSetItem(models.Model):
    """A single order template inside an order set (med / lab / imaging)."""

    class OrderType(models.TextChoices):
        MEDICATION = "medication", "Medicamento"
        LAB = "lab", "Laboratório"
        IMAGING = "imaging", "Imagem"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order_set = models.ForeignKey(OrderSet, on_delete=models.CASCADE, related_name="items")
    order_type = models.CharField(max_length=20, choices=OrderType.choices, db_index=True)
    label = models.CharField(max_length=300)
    # Optional structured references — a medication template may point at a Drug;
    # lab/imaging templates typically carry their spec in ``details``.
    drug = models.ForeignKey(
        "pharmacy.Drug", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    dosage_instructions = models.TextField(blank=True)
    quantity = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    details = models.JSONField(default=dict, blank=True)
    sequence = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sequence", "created_at"]

    def _guard_frozen(self):
        if self.order_set_id and self.order_set.status == OrderSet.Status.APPROVED:
            raise ValidationError(
                "Itens de um order set aprovado são imutáveis; crie uma nova versão."
            )

    def save(self, *args, **kwargs):
        self._guard_frozen()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self._guard_frozen()
        return super().delete(*args, **kwargs)

    def __str__(self):
        return f"[{self.get_order_type_display()}] {self.label}"


class OrderSetApplication(models.Model):
    """Header grouping the orders instantiated when an order set is applied."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order_set = models.ForeignKey(OrderSet, on_delete=models.PROTECT, related_name="applications")
    encounter = models.ForeignKey(
        Encounter, on_delete=models.CASCADE, related_name="order_set_applications"
    )
    applied_by = models.ForeignKey(
        "core.User", on_delete=models.PROTECT, related_name="order_set_applications"
    )
    applied_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-applied_at"]

    def __str__(self):
        return f"{self.order_set} → {self.encounter_id}"


class AppliedOrder(models.Model):
    """A concrete order instantiated from an order-set item onto an encounter."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pendente"
        FULFILLED = "fulfilled", "Efetivada"
        CANCELLED = "cancelled", "Cancelada"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    application = models.ForeignKey(
        OrderSetApplication, on_delete=models.CASCADE, related_name="orders"
    )
    encounter = models.ForeignKey(
        Encounter, on_delete=models.CASCADE, related_name="applied_orders"
    )
    source_item = models.ForeignKey(
        OrderSetItem, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    order_type = models.CharField(max_length=20, choices=OrderSetItem.OrderType.choices)
    label = models.CharField(max_length=300)
    drug = models.ForeignKey(
        "pharmacy.Drug", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    details = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.label} ({self.order_type})"
