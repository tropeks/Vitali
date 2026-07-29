"""
Banco de Sangue/Hemoterapia — doador + triagem sorológica (Sprint H2)
====================================================================

H1 shipped the physical :class:`~apps.emr.bloodbank_models.BloodBag` stock,
defaulting every fresh bag to ``serology_status = quarentena``. H2 owns the
**bag-entry release flow**: the mandatory RDC 34 serology panel (triagem
sorológica) that flips a quarantined bag to *liberada* or *descartada*.

Two tenant models live here:

    BloodDonor         ── the donor / source of a doação (cadastro + aptidão)
    BloodBagSerology   ── the RDC 34 marker panel for ONE BloodBag

The state transition itself (quarentena → liberada/descartada) is NOT done in a
serializer — it is driven only through
:func:`apps.emr.services.blood_serology.registrar_sorologia` so the serology row
and the bag's ``serology_status`` / ``stock_status`` always move together inside
one ``transaction.atomic`` with ``select_for_update`` on the bag.

Kept in a dedicated module (re-exported by ``models.py`` with a single
``from .blood_donor_models import *``) so the parent-worktree merge touches
``models.py`` by exactly one line — mirroring ``bloodbank_models`` / ``adt_models``.

H1 owns :class:`BloodBag`; H2 does NOT add fields there (would risk a merge
collision with H1). The donor link is therefore modelled as an optional FK on the
serology-adjacent workflow only when a collection record is introduced; for H2 a
:class:`BloodDonor` is a standalone cadastro. The RDC 34 panel FKs the bag via
``BloodBagSerology.bag`` (related_name ``serologies``), which needs no change to
the BloodBag model.
"""

from __future__ import annotations

import uuid

from django.db import models

from .bloodbank_models import BloodBag

__all__ = [
    "BloodDonor",
    "BloodBagSerology",
]


# ─── H2: doador ───────────────────────────────────────────────────────────────


class BloodDonor(models.Model):
    """A blood donor (doador) — cadastro + aptidão (apto/inapto para doar).

    ABO / Rh reuse the exact :class:`BloodBag` choice sets. ``apto`` marks the
    donor's current fitness to donate (default apto). A future collection record
    may FK a donor to a :class:`BloodBag`; H2 keeps the donor standalone.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    full_name = models.CharField("Nome completo", max_length=255, db_index=True)
    cpf = models.CharField("CPF", max_length=14, blank=True, default="", db_index=True)
    abo = models.CharField("Grupo ABO", max_length=2, choices=BloodBag.ABO.choices, blank=True)
    rh_factor = models.CharField(
        "Fator Rh", max_length=8, choices=BloodBag.RhFactor.choices, blank=True
    )
    birth_date = models.DateField("Data de nascimento", null=True, blank=True)
    last_donation = models.DateField("Última doação", null=True, blank=True)
    apto = models.BooleanField("Apto a doar", default=True)
    notes = models.TextField("Observações", blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["full_name"]
        verbose_name = "Doador de Sangue"
        verbose_name_plural = "Doadores de Sangue"

    def __str__(self):
        return f"{self.full_name} ({self.abo}{self.rh_factor})".strip()


# ─── H2: triagem sorológica (painel RDC 34) ───────────────────────────────────


class BloodBagSerology(models.Model):
    """The mandatory RDC 34 serology panel (triagem sorológica) for one BloodBag.

    Each obligatory marker is a tri-state result — ``nao_reagente`` (default),
    ``reagente`` or ``indeterminado``. A bag is only released when EVERY marker
    is ``nao_reagente`` (:pyattr:`all_non_reactive`); any reagente/indeterminado
    result discards the bag. The release/discard transition is applied by
    :func:`apps.emr.services.blood_serology.registrar_sorologia`, never here.
    """

    class Result(models.TextChoices):
        NAO_REAGENTE = "nao_reagente", "Não reagente"
        REAGENTE = "reagente", "Reagente"
        INDETERMINADO = "indeterminado", "Indeterminado"

    #: The mandatory RDC 34 marker fields (used by :pyattr:`all_non_reactive`).
    PANEL = ("hiv", "hbsag", "anti_hbc", "anti_hcv", "sifilis", "chagas", "htlv")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    bag = models.ForeignKey(
        "emr.BloodBag",
        on_delete=models.CASCADE,
        related_name="serologies",
        verbose_name="Bolsa",
    )

    hiv = models.CharField(
        "HIV", max_length=16, choices=Result.choices, default=Result.NAO_REAGENTE
    )
    hbsag = models.CharField(
        "HBsAg", max_length=16, choices=Result.choices, default=Result.NAO_REAGENTE
    )
    anti_hbc = models.CharField(
        "Anti-HBc", max_length=16, choices=Result.choices, default=Result.NAO_REAGENTE
    )
    anti_hcv = models.CharField(
        "Anti-HCV", max_length=16, choices=Result.choices, default=Result.NAO_REAGENTE
    )
    sifilis = models.CharField(
        "Sífilis", max_length=16, choices=Result.choices, default=Result.NAO_REAGENTE
    )
    chagas = models.CharField(
        "Doença de Chagas", max_length=16, choices=Result.choices, default=Result.NAO_REAGENTE
    )
    htlv = models.CharField(
        "HTLV I/II", max_length=16, choices=Result.choices, default=Result.NAO_REAGENTE
    )

    tested_at = models.DateTimeField("Testado em", auto_now_add=True)
    tested_by = models.ForeignKey(
        "core.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="blood_serologies_tested",
        verbose_name="Testado por",
    )
    notes = models.TextField("Observações", blank=True, default="")

    class Meta:
        ordering = ["-tested_at"]
        verbose_name = "Sorologia de Bolsa"
        verbose_name_plural = "Sorologias de Bolsas"
        indexes = [
            models.Index(fields=["bag", "-tested_at"], name="emr_serol_bag_tested_idx"),
        ]

    @property
    def all_non_reactive(self) -> bool:
        """True when every mandatory RDC 34 marker is ``nao_reagente``."""
        return all(getattr(self, m) == self.Result.NAO_REAGENTE for m in self.PANEL)

    def __str__(self):
        state = "todos não-reagentes" if self.all_non_reactive else "com reatividade"
        return f"Sorologia bolsa {self.bag_id} ({state})"
