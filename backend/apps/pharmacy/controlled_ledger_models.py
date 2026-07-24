"""
Sprint M1-S2 — Livro de escrituração de controlados (SNGPC-like) · ENT-009.

Regulatory book for Portaria 344 controlled substances. Builds ON the existing
append-only ``StockMovement`` ledger and the governance maker-checker idiom — it
does not reinvent stock accounting. Each ``ControlledSubstanceLedger`` row is the
*livro de escrituração* for one (controlled Drug / presentation / competency
period): opening balance, entries, exits and closing balance, all derived from
the underlying StockMovements of ``is_controlled`` drugs.

Both models here are append-only/immutable, mirroring ``StockMovement.save``/
``delete`` guards: a book (and its signed closing) is a regulatory record — once
written it is never mutated in place; corrections are made by new movements and a
new period's book.
"""

import uuid

from django.db import models

__all__ = ["ControlledSubstanceLedger", "ControlledLedgerClosing"]


class ControlledSubstanceLedger(models.Model):
    """Livro de escrituração de um controlado por período de competência.

    Reconstructed from the ``StockMovement`` ledger by
    ``services.controlled_ledger.ControlledLedgerBuilder``. Immutable after
    creation (mirror of ``StockMovement``): balances are a snapshot of the
    movement ledger at build time; a re-run produces a NEW book only while the
    period is still open (no signed closing).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    drug = models.ForeignKey("Drug", on_delete=models.PROTECT, related_name="controlled_ledgers")
    # Snapshots taken at build time so the book is self-contained even if the
    # Drug's classification/presentation is later edited.
    controlled_class = models.CharField(max_length=5)
    presentation = models.CharField(max_length=220, blank=True)
    period_start = models.DateField()
    period_end = models.DateField()
    opening_balance = models.DecimalField(max_digits=14, decimal_places=3)
    total_entries = models.DecimalField(max_digits=14, decimal_places=3)
    total_exits = models.DecimalField(max_digits=14, decimal_places=3)
    closing_balance = models.DecimalField(max_digits=14, decimal_places=3)
    built_by = models.ForeignKey(
        "core.User",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="controlled_ledgers_built",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-period_start", "drug__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["drug", "period_start", "period_end"],
                name="uniq_controlled_ledger_drug_period",
            )
        ]
        indexes = [
            models.Index(fields=["controlled_class", "period_start"]),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError(
                "ControlledSubstanceLedger é imutável — reconstrua um novo livro em vez de editar."
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("ControlledSubstanceLedger não pode ser excluído (registro regulatório).")

    @property
    def reconciles(self):
        """The book identity must always hold."""
        return self.closing_balance == (
            self.opening_balance + self.total_entries - self.total_exits
        )

    @property
    def is_closed(self):
        return hasattr(self, "closing")

    def __str__(self):
        return (
            f"Livro {self.controlled_class} {self.drug.name} "
            f"{self.period_start}→{self.period_end} (saldo {self.closing_balance})"
        )


class ControlledLedgerClosing(models.Model):
    """Fechamento assinado de um período (RT/farmacêutico).

    Maker-checker: the signer must differ from the ledger's ``built_by`` (the
    maker who reconstructed the book) — same segregation principle as the
    InventoryCount / governance ApprovalRequest flow (requester ≠ approver).
    Once a closing exists the period is immutable: the book cannot be rebuilt and
    the closing itself cannot be mutated or deleted.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ledger = models.OneToOneField(
        ControlledSubstanceLedger, on_delete=models.PROTECT, related_name="closing"
    )
    # RT's independently conferred closing balance (dupla conferência).
    checked_balance = models.DecimalField(max_digits=14, decimal_places=3)
    signed_by = models.ForeignKey(
        "core.User",
        on_delete=models.PROTECT,
        related_name="controlled_ledger_closings",
    )
    signature_hash = models.CharField(max_length=128, blank=True)
    closed_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-closed_at"]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError(
                "ControlledLedgerClosing é imutável — o período fechado não pode ser alterado."
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("ControlledLedgerClosing não pode ser excluído (fechamento assinado).")

    @property
    def reconciles(self):
        return self.checked_balance == self.ledger.closing_balance

    @property
    def divergence(self):
        return self.checked_balance - self.ledger.closing_balance

    def __str__(self):
        return f"Fechamento {self.ledger_id} por {self.signed_by_id} em {self.closed_at:%Y-%m}"
