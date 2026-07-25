"""Sprint C4 — Consumo por exame + P&L do contrato (economic keystone).

An exam performed at a client unit CONSUMES supplies (per ``ServiceRecipe``)
that must be deducted from that unit's on-hand stock (the pharmacy ledger) as a
COST, and it produces revenue (``ContractServicePrice`` when billable). This
module records per-exam consumption (:class:`ExamConsumption`); on top of it,
``services_pnl`` computes the contract/unit P&L (revenue − cost).

Cost-basis note (assumption): ``pharmacy.Material`` has no unit cost of its own
(costs live on the purchase/receipt ledger, per lot). The operator's *supply
cost basis* for the concession economics is therefore kept HERE, concession-
local (:class:`MaterialUnitCost`) — deliberately separate from pharmacy's
purchase ledger, and INERT (0) until the operator registers it. ``cost_snapshot``
is frozen on the ``ExamConsumption`` row at record time, so later cost edits
never rewrite historical P&L.
"""

from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class MaterialUnitCost(models.Model):
    """The operator's cost basis for one ``pharmacy.Material`` (concession-local).

    Kept in this module (not on ``Material``) because it models the operator's
    concession economics, not pharmacy's purchase ledger. Absent row → cost 0
    (inert), mirroring the pharmacy "NULL means no value, not zero-by-default"
    philosophy but defaulting the *contribution* to 0 so consumption still runs.
    """

    material = models.OneToOneField(
        "pharmacy.Material",
        on_delete=models.CASCADE,
        related_name="concession_unit_cost",
        verbose_name="Insumo",
    )
    unit_cost = models.DecimalField(
        "Custo unitário",
        max_digits=12,
        decimal_places=2,
        default=Decimal("0"),
        help_text="Custo unitário do insumo para a economia da concessão.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["material__name"]
        verbose_name = "Custo unitário de insumo (concessão)"
        verbose_name_plural = "Custos unitários de insumo (concessão)"

    def __str__(self):
        return f"{self.material_id} @ {self.unit_cost}"


class ExamConsumption(models.Model):
    """One exam performed at a unit — deducts the service recipe from that unit's
    stock (pharmacy ledger) and freezes the consumed cost.

    Append-only ledger row (like ``pharmacy.StockMovement`` / ``ProofOfDelivery``):
    ``save()`` refuses updates and ``delete()`` raises. Idempotent per exam via
    the unique ``idempotency_key`` — re-recording the same exam is a no-op, so a
    retry never double-deducts stock.
    """

    unit = models.ForeignKey(
        "organization.Facility",
        on_delete=models.PROTECT,
        related_name="concession_exam_consumptions",
        verbose_name="Unidade",
    )
    service = models.ForeignKey(
        "concession.ConcessionService",
        on_delete=models.PROTECT,
        related_name="exam_consumptions",
        verbose_name="Serviço/exame",
    )
    # Exam reference: a free-form external id and/or a structured imaging study.
    external_ref = models.CharField(
        "Referência externa do exame", max_length=128, blank=True, db_index=True
    )
    dicom_study = models.ForeignKey(
        "imaging.DicomStudy",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="concession_exam_consumptions",
        verbose_name="Estudo DICOM (opcional)",
    )
    # Warehouse the unit's on-hand stock was drawn from (same warehouse C3
    # delivers replenishment into). Kept for traceability of the deduction.
    source_warehouse = models.ForeignKey(
        "pharmacy.Warehouse",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="concession_exam_consumptions",
        verbose_name="Estoque de origem",
    )
    performed_at = models.DateTimeField("Realizado em", default=timezone.now, db_index=True)
    cost_snapshot = models.DecimalField(
        "Custo consumido (congelado)",
        max_digits=12,
        decimal_places=2,
        default=Decimal("0"),
        help_text="Σ quantidade_da_receita × custo_unitário no momento do exame.",
    )
    idempotency_key = models.CharField("Chave de idempotência", max_length=200, unique=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-performed_at"]
        indexes = [
            models.Index(fields=["unit", "service"]),
            models.Index(fields=["performed_at"]),
        ]
        verbose_name = "Consumo por exame"
        verbose_name_plural = "Consumos por exame"

    def __str__(self):
        return f"Exame {self.external_ref or self.dicom_study_id} @ {self.unit_id}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError(
                "ExamConsumption é um ledger append-only; atualização não é permitida."
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("ExamConsumption é um ledger append-only; remoção não é permitida.")


__all__ = [
    "MaterialUnitCost",
    "ExamConsumption",
]
