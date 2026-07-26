"""
SAE domain — executable Sistematização da Assistência de Enfermagem (Sprint N2)
==============================================================================

The N1 sprint shipped the governed NANDA-I / NIC / NOC **catalogs** (master data
in the SHARED/public schema, see :mod:`apps.core.nursing_catalog_models`). N2
adds the **tenant-side clinical domain** that consumes them — the real,
structured, executable SAE process:

    diagnóstico (NANDA)  →  planejamento (NOC resultado + meta)
                         →  intervenções (NIC)
                         →  prescrição de enfermagem (aprazável)
                         →  evolução

Model graph
-----------
* :class:`NursingDiagnosis` — a nursing diagnosis for a ``patient`` on an
  ``encounter``, linked to a governed ``core.NandaDiagnosis`` (the *diagnóstico*
  step). Enfermeiro-privativo (COFEN 736/2024): only ``sae.write`` may author.
* :class:`NursingCareplan` — the *planejamento* for one diagnosis: the expected
  ``core.NocOutcome`` result plus its ``target`` (meta/indicator target).
* :class:`NursingCareplanIntervention` — a prescribed ``core.NicIntervention``
  under a careplan (a careplan has one NOC and one-or-more NIC).
* :class:`NursingPrescriptionItem` — the **executable** intervention line: an
  interval (``frequency_hours``) + ``start_at`` that drives *aprazamento* (the
  due-time grid, computed by :mod:`apps.emr.services.aprazamento`).
* :class:`NursingEvolution` — the *evolução* narrative note for a patient/encounter.

Cross-schema FK pattern (tenant → SHARED catalog)
-------------------------------------------------
PostgreSQL does not enforce FK integrity across schemas (tenant → public), so —
**exactly like** ``emr.MedicalHistory.cid10`` / ``emr.Professional.cbo`` — every
catalog reference here uses ``on_delete=DO_NOTHING`` and relies on the matching
``pre_delete`` PROTECT signal in :mod:`apps.core.signals`
(``protect_nanda_diagnosis_deletion`` / ``protect_nic_intervention_deletion`` /
``protect_noc_outcome_deletion``) to block deleting a catalog row any tenant
references. Each catalog FK is nullable and paired with a ``legacy_*_text`` free
column + an ``*_unmatched`` flag, surfaced through a backward-compatible
``*_code`` string accessor — the same reconcile-safe shape as ``cbo`` / ``cnes``.

Kept in a dedicated module (re-exported by ``models.py`` with a single
``from .sae_models import *``) so the parent-worktree merge touches ``models.py``
by exactly one line.
"""

from __future__ import annotations

import uuid

from django.db import models
from encrypted_model_fields.fields import EncryptedTextField

from .models import Encounter, Patient

__all__ = [
    "NursingDiagnosis",
    "NursingCareplan",
    "NursingCareplanIntervention",
    "NursingPrescriptionItem",
    "NursingEvolution",
]


# ─── N2-T1: diagnóstico de enfermagem (NANDA) ────────────────────────────────


class NursingDiagnosis(models.Model):
    """A nursing diagnosis (NANDA-I) for a patient on an encounter.

    Enfermeiro-privativo per COFEN 736/2024: creating/updating requires
    ``sae.write`` (enforced at the API layer). The ``nanda`` FK is the governed
    cross-schema link to ``core.NandaDiagnosis``; ``related_factors`` /
    ``defining_characteristics`` capture the case-specific evidence.
    """

    class Status(models.TextChoices):
        ACTIVE = "active", "Ativo"
        RESOLVED = "resolved", "Resolvido"

    class Priority(models.TextChoices):
        HIGH = "high", "Alta"
        MEDIUM = "medium", "Média"
        LOW = "low", "Baixa"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="nursing_diagnoses")
    encounter = models.ForeignKey(
        Encounter, on_delete=models.PROTECT, related_name="nursing_diagnoses"
    )

    # ── governed cross-schema FK to the SHARED core.NandaDiagnosis catalog ────
    # DO_NOTHING + protect_nanda_diagnosis_deletion pre_delete signal, mirroring
    # emr.Professional.cbo exactly (nullable FK + legacy free text + unmatched
    # flag + backward-compatible ``nanda_code`` accessor).
    nanda = models.ForeignKey(
        "core.NandaDiagnosis",
        on_delete=models.DO_NOTHING,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Diagnóstico NANDA-I",
    )
    legacy_nanda_text = models.CharField(
        max_length=32,
        blank=True,
        default="",
        help_text="Código NANDA-I bruto não reconciliado com core.NandaDiagnosis.",
    )
    nanda_unmatched = models.BooleanField(
        default=False,
        help_text="True quando legacy_nanda_text não corresponde a nenhum NandaDiagnosis governado.",
    )

    related_factors = models.TextField(
        "Fatores relacionados",
        blank=True,
        default="",
        help_text="Fatores relacionados / de risco identificados neste paciente.",
    )
    defining_characteristics = models.TextField(
        "Características definidoras",
        blank=True,
        default="",
        help_text="Características definidoras observadas neste paciente.",
    )
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.ACTIVE, db_index=True
    )
    priority = models.CharField(
        max_length=8, choices=Priority.choices, default=Priority.MEDIUM, db_index=True
    )
    created_by = models.ForeignKey(
        "core.User", on_delete=models.PROTECT, related_name="authored_nursing_diagnoses"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Diagnóstico de Enfermagem"
        verbose_name_plural = "Diagnósticos de Enfermagem"
        indexes = [
            models.Index(fields=["patient", "status"], name="emr_nursingdx_pat_status_idx"),
            models.Index(fields=["encounter"], name="emr_nursingdx_enc_idx"),
        ]

    @property
    def nanda_code(self) -> str:
        """NANDA code string: the governed FK's code when linked, else raw legacy text."""
        if self.nanda_id:
            return self.nanda.code  # type: ignore[union-attr]
        return self.legacy_nanda_text

    @nanda_code.setter
    def nanda_code(self, value: str) -> None:
        code = (value or "").strip()
        if not code:
            self.nanda = None
            self.legacy_nanda_text = ""
            self.nanda_unmatched = False
            return
        from apps.core.models import NandaDiagnosis

        match = NandaDiagnosis.objects.filter(code=code).first()
        if match is not None:
            self.nanda = match
            self.legacy_nanda_text = ""
            self.nanda_unmatched = False
        else:
            self.nanda = None
            self.legacy_nanda_text = code
            self.nanda_unmatched = True

    def __str__(self):
        return f"Dx enf {self.nanda_code or '—'} ({self.get_status_display()}) — {self.patient}"


# ─── N2-T1: planejamento (NOC resultado esperado + meta) ─────────────────────


class NursingCareplan(models.Model):
    """The *planejamento* for one nursing diagnosis: expected NOC outcome + target.

    Links a :class:`NursingDiagnosis` to a governed ``core.NocOutcome`` (the
    resultado esperado) and records the ``target`` (meta / indicator target).
    Its NIC interventions hang off :class:`NursingCareplanIntervention`.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    diagnosis = models.ForeignKey(
        NursingDiagnosis, on_delete=models.CASCADE, related_name="careplans"
    )

    # ── governed cross-schema FK to the SHARED core.NocOutcome catalog ────────
    noc = models.ForeignKey(
        "core.NocOutcome",
        on_delete=models.DO_NOTHING,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Resultado NOC",
    )
    legacy_noc_text = models.CharField(
        max_length=32,
        blank=True,
        default="",
        help_text="Código NOC bruto não reconciliado com core.NocOutcome.",
    )
    noc_unmatched = models.BooleanField(
        default=False,
        help_text="True quando legacy_noc_text não corresponde a nenhum NocOutcome governado.",
    )

    expected_outcome = models.TextField(
        "Resultado esperado",
        blank=True,
        default="",
        help_text="Descrição do resultado esperado (complementa o rótulo NOC).",
    )
    target = models.CharField(
        "Meta",
        max_length=200,
        blank=True,
        default="",
        help_text="Meta / alvo do indicador NOC (ex.: 'escala de dor ≤ 2 em 48h').",
    )
    created_by = models.ForeignKey(
        "core.User", on_delete=models.PROTECT, related_name="authored_nursing_careplans"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Planejamento de Enfermagem"
        verbose_name_plural = "Planejamentos de Enfermagem"

    @property
    def noc_code(self) -> str:
        """NOC code string: the governed FK's code when linked, else raw legacy text."""
        if self.noc_id:
            return self.noc.code  # type: ignore[union-attr]
        return self.legacy_noc_text

    @noc_code.setter
    def noc_code(self, value: str) -> None:
        code = (value or "").strip()
        if not code:
            self.noc = None
            self.legacy_noc_text = ""
            self.noc_unmatched = False
            return
        from apps.core.models import NocOutcome

        match = NocOutcome.objects.filter(code=code).first()
        if match is not None:
            self.noc = match
            self.legacy_noc_text = ""
            self.noc_unmatched = False
        else:
            self.noc = None
            self.legacy_noc_text = code
            self.noc_unmatched = True

    def __str__(self):
        return f"Plano {self.noc_code or '—'} — {self.diagnosis}"


# ─── N2-T1: intervenção prescrita (NIC) sob um planejamento ──────────────────


class NursingCareplanIntervention(models.Model):
    """A prescribed NIC intervention under a careplan (careplan 1—* NIC)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    careplan = models.ForeignKey(
        NursingCareplan, on_delete=models.CASCADE, related_name="interventions"
    )

    # ── governed cross-schema FK to the SHARED core.NicIntervention catalog ───
    nic = models.ForeignKey(
        "core.NicIntervention",
        on_delete=models.DO_NOTHING,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Intervenção NIC",
    )
    legacy_nic_text = models.CharField(
        max_length=32,
        blank=True,
        default="",
        help_text="Código NIC bruto não reconciliado com core.NicIntervention.",
    )
    nic_unmatched = models.BooleanField(
        default=False,
        help_text="True quando legacy_nic_text não corresponde a nenhum NicIntervention governado.",
    )

    notes = models.TextField(
        "Observações",
        blank=True,
        default="",
        help_text="Detalhamento / atividades específicas da intervenção neste paciente.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "Intervenção de Enfermagem (NIC)"
        verbose_name_plural = "Intervenções de Enfermagem (NIC)"

    @property
    def nic_code(self) -> str:
        """NIC code string: the governed FK's code when linked, else raw legacy text."""
        if self.nic_id:
            return self.nic.code  # type: ignore[union-attr]
        return self.legacy_nic_text

    @nic_code.setter
    def nic_code(self, value: str) -> None:
        code = (value or "").strip()
        if not code:
            self.nic = None
            self.legacy_nic_text = ""
            self.nic_unmatched = False
            return
        from apps.core.models import NicIntervention

        match = NicIntervention.objects.filter(code=code).first()
        if match is not None:
            self.nic = match
            self.legacy_nic_text = ""
            self.nic_unmatched = False
        else:
            self.nic = None
            self.legacy_nic_text = code
            self.nic_unmatched = True

    def __str__(self):
        return f"Intervenção {self.nic_code or '—'} — {self.careplan}"


# ─── N2-T1: prescrição de enfermagem (aprazável) ─────────────────────────────


class NursingPrescriptionItem(models.Model):
    """The executable intervention line — carries the frequency that drives aprazamento.

    ``frequency_hours`` is the canonical interval (a "6/6h" order = 6). The
    :mod:`apps.emr.services.aprazamento` service expands ``start_at`` +
    ``frequency_hours`` into the due-time grid over a window.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    intervention = models.ForeignKey(
        NursingCareplanIntervention,
        on_delete=models.CASCADE,
        related_name="prescription_items",
    )
    description = models.CharField(
        "Descrição",
        max_length=300,
        blank=True,
        default="",
        help_text="O que executar (ex.: 'Verificar sinais vitais').",
    )
    frequency_hours = models.PositiveSmallIntegerField(
        "Frequência (horas)",
        help_text="Intervalo em horas entre execuções (ex.: 6 = de 6/6h). Base do aprazamento.",
    )
    start_at = models.DateTimeField(
        "Início",
        help_text="Momento da primeira execução; âncora da grade de aprazamento.",
    )
    active = models.BooleanField(default=True, db_index=True)
    created_by = models.ForeignKey(
        "core.User", on_delete=models.PROTECT, related_name="authored_nursing_prescription_items"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["start_at"]
        verbose_name = "Prescrição de Enfermagem (item)"
        verbose_name_plural = "Prescrições de Enfermagem (itens)"
        indexes = [
            models.Index(fields=["active", "start_at"], name="emr_nursingrx_active_idx"),
        ]

    def __str__(self):
        return f"{self.description or 'Prescrição'} {self.frequency_hours}/{self.frequency_hours}h"


# ─── N2-T1: evolução de enfermagem ───────────────────────────────────────────


class NursingEvolution(models.Model):
    """A nursing evolution (evolução) narrative note for a patient/encounter."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey(
        Patient, on_delete=models.CASCADE, related_name="nursing_evolutions"
    )
    encounter = models.ForeignKey(
        Encounter, on_delete=models.PROTECT, related_name="nursing_evolutions"
    )
    # Clinical free-text — sensitive PII, encrypted at rest (LGPD) like SOAPNote.
    text = EncryptedTextField("Evolução", help_text="Texto da evolução de enfermagem.")
    created_by = models.ForeignKey(
        "core.User", on_delete=models.PROTECT, related_name="authored_nursing_evolutions"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Evolução de Enfermagem"
        verbose_name_plural = "Evoluções de Enfermagem"
        indexes = [
            models.Index(fields=["patient", "created_at"], name="emr_nursingevo_pat_idx"),
            models.Index(fields=["encounter"], name="emr_nursingevo_enc_idx"),
        ]

    def __str__(self):
        return f"Evolução — {self.patient} — {self.created_at:%d/%m/%Y %H:%M}"
