"""
PS/Emergência domain — boletim + classificação de risco Manchester (Sprint E2)
==============================================================================

E1 shipped the governed **SHARED** Manchester catalog
(:mod:`apps.core.manchester_catalog_models`: ``ManchesterFlowchart`` /
``ManchesterDiscriminator`` + acuidade). E2 adds the **tenant-side** boletim de
atendimento de emergência + its append-only risk classification (triagem):

    EmergencyEncounter (boletim de atendimento)
        →  RiskClassification (classificação de risco — histórico append-only)

Queue ordering / disposition (encerramento) are E3 — the ``status`` enum already
carries the values E3 will drive transitions through; no queue/SLA logic here.

Cross-schema FK pattern (tenant → SHARED catalog)
-------------------------------------------------
``RiskClassification.flowchart`` / ``.discriminator`` reference the SHARED
``core.ManchesterFlowchart`` / ``core.ManchesterDiscriminator``. PostgreSQL does
not enforce FK integrity across schemas (tenant → public), so — exactly like
``emr.Bed.bed_type`` / ``emr.SurgicalProcedure.tuss_code`` — these use
``on_delete=models.DO_NOTHING`` and rely on the ``pre_delete`` PROTECT signals in
:mod:`apps.core.signals` (``protect_manchester_flowchart_deletion`` /
``protect_manchester_discriminator_deletion``) to block deleting a catalog row any
tenant references. PROTECT is unusable across schemas: Django's deletion Collector
runs in the public schema and would query the (non-existent)
``public.emr_riskclassification`` table BEFORE the pre_delete signal can raise a
graceful ProtectedError. ``acuity_level`` / ``target_minutes`` are COPIED from the
chosen discriminator at classify time so the history stays stable even if the
governed catalog later changes.

Kept in a dedicated module (re-exported by ``models.py`` with a single
``from .emergency_models import *``) so the parent-worktree merge touches
``models.py`` by exactly one line — mirroring ``adt_models`` / ``surgery_models``.
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils import timezone

from apps.core.manchester_catalog_models import AcuityLevel

__all__ = [
    "EmergencyEncounter",
    "RiskClassification",
]


# ─── E2: boletim de atendimento de emergência ────────────────────────────────


class EmergencyEncounter(models.Model):
    """Boletim de atendimento de emergência (BAE) — a patient's PS visit.

    Opened at arrival (recepção do PS), links the ``patient`` and — optionally —
    the ``emergencia`` clinical :class:`~apps.emr.models.Encounter` (which may be
    created/linked later). Its ``status`` starts at ``aguardando_classificacao``;
    the classify service advances it to ``classificado``. ``em_atendimento`` /
    ``encerrado`` are reserved for E3 (queue + disposition) — the enum carries
    them now so E3 only wires transitions.
    """

    class ModeOfArrival(models.TextChoices):
        AMBULANTE = "ambulante", "Ambulante"
        CADEIRA_RODAS = "cadeira_rodas", "Cadeira de rodas"
        MACA = "maca", "Maca"
        AMBULANCIA = "ambulancia", "Ambulância"
        VIATURA_PM = "viatura_pm", "Viatura (PM/SAMU)"
        OUTRO = "outro", "Outro"

    class Status(models.TextChoices):
        AGUARDANDO_CLASSIFICACAO = "aguardando_classificacao", "Aguardando classificação"
        CLASSIFICADO = "classificado", "Classificado"
        EM_ATENDIMENTO = "em_atendimento", "Em atendimento"
        ENCERRADO = "encerrado", "Encerrado"

    class Disposition(models.TextChoices):
        """Desfecho do atendimento de PS (set at encerramento — E3)."""

        ALTA = "alta", "Alta"
        INTERNACAO = "internacao", "Internação"
        TRANSFERENCIA_EXTERNA = "transferencia_externa", "Transferência externa"
        OBITO = "obito", "Óbito"
        EVASAO = "evasao", "Evasão"
        OBSERVACAO = "observacao", "Observação"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey(
        "emr.Patient",
        on_delete=models.PROTECT,
        related_name="emergency_encounters",
        verbose_name="Paciente",
    )
    # Optional link to the emergencia clinical Encounter (may be created later).
    encounter = models.ForeignKey(
        "emr.Encounter",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="emergency_encounters",
        verbose_name="Encontro clínico (emergência)",
    )
    arrival_at = models.DateTimeField("Chegada", default=timezone.now, db_index=True)
    mode_of_arrival = models.CharField(
        "Meio de chegada",
        max_length=16,
        choices=ModeOfArrival.choices,
        default=ModeOfArrival.AMBULANTE,
    )
    # Plain free-text queixa here (the LGPD-encrypted one lives on Encounter).
    chief_complaint = models.TextField("Queixa principal", blank=True, default="")
    status = models.CharField(
        "Situação",
        max_length=32,
        choices=Status.choices,
        default=Status.AGUARDANDO_CLASSIFICACAO,
        db_index=True,
    )
    # Desfecho (E3): set at encerramento. NULL = boletim ainda ativo (sem desfecho)
    # — distinto de "" (DJ001 suprimido, convenção do repo, igual Admission.disposition).
    disposition = models.CharField(  # noqa: DJ001
        "Desfecho",
        max_length=32,
        choices=Disposition.choices,
        null=True,
        blank=True,
        db_index=True,
    )
    # Internação bridge (E3): quando o desfecho é `internacao` e um leito é
    # informado, o serviço de encerramento chama apps.emr.services.adt.admit e
    # grava aqui a Admission resultante. NULL quando interna-se depois (sem leito).
    admission = models.ForeignKey(
        "emr.Admission",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="emergency_encounters",
        verbose_name="Internação",
    )
    created_by = models.ForeignKey(
        "core.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="emergency_encounters_created",
        verbose_name="Aberto por",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-arrival_at"]
        verbose_name = "Boletim de Emergência"
        verbose_name_plural = "Boletins de Emergência"
        indexes = [
            models.Index(fields=["status", "arrival_at"], name="emr_emerg_status_arr_idx"),
            models.Index(fields=["patient", "status"], name="emr_emerg_patient_status_idx"),
        ]

    @property
    def current_classification(self) -> RiskClassification | None:
        """The latest risk classification (re-triagem wins), or None if unclassified."""
        return self.classifications.first()

    def __str__(self):
        return f"Boletim {self.patient_id} ({self.get_status_display()})"


# ─── E2: classificação de risco (histórico append-only) ──────────────────────


class RiskClassification(models.Model):
    """A Manchester risk classification (triagem) of an :class:`EmergencyEncounter`.

    Append-only history: a re-classificação (re-triagem) is a NEW row, never an
    edit — so the audit trail of every priority the patient held is preserved.
    ``acuity_level`` / ``target_minutes`` are COPIED from the chosen discriminator
    at classify time (catalog-change stable). ``flowchart`` / ``discriminator``
    are cross-schema FKs to the SHARED catalog (DO_NOTHING + the pre_delete
    guards in apps/core/signals.py).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    boletim = models.ForeignKey(
        EmergencyEncounter,
        on_delete=models.PROTECT,
        related_name="classifications",
        verbose_name="Boletim",
    )
    # Cross-schema FKs to the SHARED Manchester catalog. DO_NOTHING + the
    # protect_manchester_* pre_delete signals (apps/core/signals.py); PROTECT would
    # crash the cross-schema deletion Collector (see module docstring).
    flowchart = models.ForeignKey(
        "core.ManchesterFlowchart",
        on_delete=models.DO_NOTHING,
        related_name="+",
        verbose_name="Fluxograma",
    )
    discriminator = models.ForeignKey(
        "core.ManchesterDiscriminator",
        on_delete=models.DO_NOTHING,
        related_name="+",
        verbose_name="Discriminador",
    )
    acuity_level = models.CharField(
        "Nível de acuidade",
        max_length=10,
        choices=AcuityLevel.choices,
        db_index=True,
        help_text="Cópia estável do nível do discriminador no momento da classificação.",
    )
    target_minutes = models.PositiveIntegerField(
        "Tempo-alvo (min)",
        help_text="Tempo-alvo de atendimento do nível Manchester (cópia estável).",
    )
    # The vitals snapshot used at triage (optional).
    vitals = models.ForeignKey(
        "emr.VitalSigns",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="risk_classifications",
        verbose_name="Sinais vitais",
    )
    classified_by = models.ForeignKey(
        "core.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="risk_classifications",
        verbose_name="Classificado por",
    )
    classified_at = models.DateTimeField("Classificado em", default=timezone.now, db_index=True)
    notes = models.TextField("Observações", blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Latest first: current_classification = classifications.first(); the
        # created_at tiebreak keeps ordering stable when two triagens share a
        # classified_at timestamp.
        ordering = ["-classified_at", "-created_at"]
        verbose_name = "Classificação de Risco"
        verbose_name_plural = "Classificações de Risco"
        indexes = [
            models.Index(fields=["boletim", "classified_at"], name="emr_riskcls_bol_dt_idx"),
        ]

    @property
    def flowchart_code(self) -> str:
        """Null-safe read accessor for the linked flowchart code (else '')."""
        if self.flowchart_id:
            return self.flowchart.code
        return ""

    @property
    def discriminator_code(self) -> str:
        """Null-safe read accessor for the linked discriminator code (else '')."""
        if self.discriminator_id:
            return self.discriminator.code
        return ""

    def __str__(self):
        return f"Triagem {self.acuity_level} — boletim {self.boletim_id}"
