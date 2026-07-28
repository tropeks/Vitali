"""
Banco de Sangue/Hemoterapia domain — estoque de bolsas (Sprint H1)
==================================================================

The H1 sprint shipped the governed
:class:`~apps.core.blood_catalog_models.BloodComponentCatalog` **catalog**
(hemocomponentes, master data in the SHARED/public schema). This module adds the
**tenant-side stock** that consumes it — the physical blood bag (bolsa):

    BloodBag (bolsa / DIN)  ── governed BloodComponentCatalog FK + estoque

No donor / serology workflow here (that is H2 — H1 only *models* the
``serology_status`` field, defaulting every fresh bag to ``quarentena``). No
request / crossmatch (H3) and no bedside checagem/reaction (H4). This sprint
models only the bag structure + its CRUD API and RBAC.

Cross-schema FK pattern (tenant → SHARED catalog)
-------------------------------------------------
PostgreSQL does not enforce FK integrity across schemas (tenant → public), so —
**exactly like** ``emr.Bed.bed_type`` / ``emr.NursingDiagnosis.nanda`` — the
``BloodBag.component`` catalog reference uses ``on_delete=DO_NOTHING`` and relies
on the matching ``pre_delete`` PROTECT signal in :mod:`apps.core.signals`
(``protect_blood_component_deletion``) to block deleting a hemocomponente any
tenant references.

Kept in a dedicated module (re-exported by ``models.py`` with a single
``from .bloodbank_models import *``) so the parent-worktree merge touches
``models.py`` by exactly one line — mirroring ``adt_models`` / ``surgery_models``.

Contract for later sprints
--------------------------
* **H2** (doador + sorologia) flips ``serology_status`` quarentena → liberada /
  descartada and owns the bag-entry flow (collection → serology → release).
* **H3** (TransfusionRequest + CrossMatch) will FK :class:`BloodBag` + the
  patient's ``abo`` / ``rh_factor`` typed result for the compatibility check and
  will drive ``stock_status`` reservada → transfundida.
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils import timezone

__all__ = [
    "BloodBag",
]


# ─── H1: bolsa de hemocomponente ─────────────────────────────────────────────


class BloodBag(models.Model):
    """A physical blood bag (bolsa) in tenant stock, identified by its DIN.

    Carries the typed ABO/Rh of the unit, the collection/expiry dates, the
    ``serology_status`` (quarentena até a sorologia liberar — H2) and the
    operational ``stock_status`` (disponível → reservada → transfundida), plus
    the attribute flags (irradiada / leucodepletada / aférese). A governed
    cross-schema ``component`` FK to the SHARED
    :class:`~apps.core.blood_catalog_models.BloodComponentCatalog` classifies the
    hemocomponente (reconcile-safe DO_NOTHING + pre_delete PROTECT guard).
    """

    class ABO(models.TextChoices):
        A = "A", "A"
        B = "B", "B"
        AB = "AB", "AB"
        O = "O", "O"  # noqa: E741 — grupo sanguíneo O (não a letra 'o' ambígua)

    class RhFactor(models.TextChoices):
        POSITIVO = "positivo", "Positivo"
        NEGATIVO = "negativo", "Negativo"

    class SerologyStatus(models.TextChoices):
        QUARENTENA = "quarentena", "Em quarentena"
        LIBERADA = "liberada", "Liberada"
        DESCARTADA = "descartada", "Descartada"

    class StockStatus(models.TextChoices):
        DISPONIVEL = "disponivel", "Disponível"
        RESERVADA = "reservada", "Reservada"
        TRANSFUNDIDA = "transfundida", "Transfundida"
        DESCARTADA = "descartada", "Descartada"
        VENCIDA = "vencida", "Vencida"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    identifier = models.CharField(
        "Identificador/DIN",
        max_length=64,
        unique=True,
        db_index=True,
        help_text="Número de identificação da doação (DIN) — único.",
    )

    # ── governed cross-schema FK to the SHARED core.BloodComponentCatalog ─────
    # DO_NOTHING + protect_blood_component_deletion pre_delete signal, mirroring
    # emr.Bed.bed_type. A bag must classify a hemocomponente (non-nullable).
    component = models.ForeignKey(
        "core.BloodComponentCatalog",
        on_delete=models.DO_NOTHING,
        related_name="+",
        verbose_name="Hemocomponente",
    )

    abo = models.CharField("Grupo ABO", max_length=2, choices=ABO.choices, db_index=True)
    rh_factor = models.CharField("Fator Rh", max_length=8, choices=RhFactor.choices, db_index=True)
    volume_ml = models.PositiveIntegerField("Volume (mL)")
    collection_date = models.DateField("Data de coleta")
    expiry_date = models.DateField("Data de validade", db_index=True)

    serology_status = models.CharField(
        "Situação sorológica",
        max_length=16,
        choices=SerologyStatus.choices,
        default=SerologyStatus.QUARENTENA,
        db_index=True,
        help_text="Bolsa fica em quarentena até a sorologia liberar (workflow em H2).",
    )
    stock_status = models.CharField(
        "Situação de estoque",
        max_length=16,
        choices=StockStatus.choices,
        default=StockStatus.DISPONIVEL,
        db_index=True,
    )

    irradiada = models.BooleanField("Irradiada", default=False)
    leucodepletada = models.BooleanField("Leucodepletada", default=False)
    aferese = models.BooleanField("Aférese", default=False)
    lot = models.CharField("Lote", max_length=64, blank=True, default="")

    created_by = models.ForeignKey(
        "core.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="blood_bags_created",
        verbose_name="Criado por",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Bolsa de Sangue"
        verbose_name_plural = "Bolsas de Sangue"
        indexes = [
            models.Index(fields=["component", "abo", "rh_factor"], name="emr_bag_comp_type_idx"),
            models.Index(
                fields=["serology_status", "stock_status"], name="emr_bag_serol_stock_idx"
            ),
            models.Index(fields=["expiry_date"], name="emr_bag_expiry_idx"),
        ]

    def is_available(self, on_date=None) -> bool:
        """True when the bag can be dispensed: serology liberada AND stock
        disponível AND not expired (``expiry_date`` today or later).

        A quarantined, reserved, discarded or expired bag is NOT available.
        """
        today = on_date or timezone.now().date()
        return (
            self.serology_status == self.SerologyStatus.LIBERADA
            and self.stock_status == self.StockStatus.DISPONIVEL
            and self.expiry_date is not None
            and self.expiry_date >= today
        )

    def __str__(self):
        return f"Bolsa {self.identifier} ({self.abo}{self.rh_factor}) — {self.get_stock_status_display()}"
