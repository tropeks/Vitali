"""
Centro Cirúrgico domain — surgical case structure (Sprint C1)
============================================================

The C1 sprint models the *estrutura* of the operating room plus the surgical
case itself:

    OperatingRoom (sala cirúrgica)      ── hangs off a Facility
    SurgicalCase (o caso cirúrgico)     ── patient + surgeon (+ optional room)
        →  SurgicalProcedure (procedimento planejado, TUSS)

No scheduling-conflict / overlap logic here (that is C2 — ``scheduled_start`` /
``scheduled_end`` are plain nullable fields for now). No checklist / times / team
(C3) and no OPME (C6). This sprint models only the static structure + its CRUD
API and RBAC.

Cross-schema FK pattern (tenant → SHARED catalog)
-------------------------------------------------
PostgreSQL does not enforce FK integrity across schemas (tenant → public), so —
**exactly like** ``emr.EncounterProcedure.tuss_code`` — the
``SurgicalProcedure.tuss_code`` catalog reference uses ``on_delete=DO_NOTHING``
and relies on the ``pre_delete`` PROTECT signal in :mod:`apps.core.signals`
(``protect_tuss_code_deletion``, extended in C1 to cover SurgicalProcedure) to
block deleting a TUSS code any tenant references. PROTECT is unusable here:
Django's deletion Collector runs in the public schema and would query the
(non-existent) ``public.emr_surgicalprocedure`` table → ProgrammingError 500
BEFORE the pre_delete signal can raise a graceful ProtectedError.

Kept in a dedicated module (re-exported by ``models.py`` with a single
``from .surgery_models import *``) so the parent-worktree merge touches
``models.py`` by exactly one line — mirroring ``adt_models`` / ``sae_models``.
"""

from __future__ import annotations

import uuid

from django.db import models

__all__ = [
    "OperatingRoom",
    "SurgicalCase",
    "SurgicalProcedure",
]


# ─── C1: sala cirúrgica ───────────────────────────────────────────────────────


class OperatingRoom(models.Model):
    """A physical operating room (sala cirúrgica) hanging off a Facility.

    The anchor for scheduling in C2 (``SurgicalCase.operating_room``). ``code`` is
    unique per facility; ``room_type`` is a small optional classification.
    """

    class RoomType(models.TextChoices):
        GERAL = "geral", "Geral"
        HIBRIDA = "hibrida", "Híbrida"
        AMBULATORIAL = "ambulatorial", "Ambulatorial"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    facility = models.ForeignKey(
        "organization.Facility",
        on_delete=models.PROTECT,
        related_name="operating_rooms",
        verbose_name="Estabelecimento",
    )
    code = models.CharField(
        "Código", max_length=50, help_text="Código da sala (único por estabelecimento)."
    )
    name = models.CharField("Nome", max_length=200)
    room_type = models.CharField(
        "Tipo de sala",
        max_length=16,
        choices=RoomType.choices,
        blank=True,
        default="",
    )
    active = models.BooleanField("Ativa", default=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["code"]
        verbose_name = "Sala Cirúrgica"
        verbose_name_plural = "Salas Cirúrgicas"
        constraints = [
            models.UniqueConstraint(
                fields=["facility", "code"],
                name="uniq_operating_room_code_per_facility",
            ),
        ]
        indexes = [
            models.Index(fields=["facility", "active"], name="emr_or_fac_active_idx"),
        ]

    def __str__(self):
        return f"{self.code} — {self.name}"


# ─── C1: caso cirúrgico ───────────────────────────────────────────────────────


class SurgicalCase(models.Model):
    """A surgical case (o caso cirúrgico): a patient + surgeon (+ optional room).

    The scheduling fields (``scheduled_start`` / ``scheduled_end`` /
    ``operating_room``) are nullable now and set at scheduling time in C2, which
    will add the overlap-guard. The status lifecycle (agendada → confirmada →
    em_sala → em_andamento → finalizada / cancelada) is a plain field here; the
    transition service is out of scope for C1.
    """

    class Priority(models.TextChoices):
        ELETIVA = "eletiva", "Eletiva"
        URGENCIA = "urgencia", "Urgência"
        EMERGENCIA = "emergencia", "Emergência"

    class Status(models.TextChoices):
        AGENDADA = "agendada", "Agendada"
        CONFIRMADA = "confirmada", "Confirmada"
        EM_SALA = "em_sala", "Em sala"
        EM_ANDAMENTO = "em_andamento", "Em andamento"
        FINALIZADA = "finalizada", "Finalizada"
        CANCELADA = "cancelada", "Cancelada"

    class AnesthesiaType(models.TextChoices):
        GERAL = "geral", "Geral"
        RAQUI = "raqui", "Raquianestesia"
        PERIDURAL = "peridural", "Peridural"
        LOCAL = "local", "Local"
        SEDACAO = "sedacao", "Sedação"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey(
        "emr.Patient",
        on_delete=models.PROTECT,
        related_name="surgical_cases",
        verbose_name="Paciente",
    )
    # Optional link to the surgical Encounter (the intra-op clinical anchor).
    encounter = models.ForeignKey(
        "emr.Encounter",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="surgical_cases",
        verbose_name="Encontro cirúrgico",
    )
    # Optional inpatient anchor: the admission the surgery belongs to.
    admission = models.ForeignKey(
        "emr.Admission",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="surgical_cases",
        verbose_name="Internação",
    )
    surgeon = models.ForeignKey(
        "emr.Professional",
        on_delete=models.PROTECT,
        related_name="surgical_cases",
        verbose_name="Cirurgião",
    )
    # Set at scheduling in C2 (with the overlap-guard); nullable now.
    operating_room = models.ForeignKey(
        OperatingRoom,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="surgical_cases",
        verbose_name="Sala cirúrgica",
    )
    scheduled_start = models.DateTimeField("Início agendado", null=True, blank=True)
    scheduled_end = models.DateTimeField("Fim agendado", null=True, blank=True)

    priority = models.CharField(
        "Prioridade",
        max_length=16,
        choices=Priority.choices,
        default=Priority.ELETIVA,
    )
    status = models.CharField(
        "Situação",
        max_length=16,
        choices=Status.choices,
        default=Status.AGENDADA,
        db_index=True,
    )
    # NULL = ainda não definido; distinto de "" — DJ001 suprimido conforme
    # convenção do repo (ver Admission.disposition).
    anesthesia_type = models.CharField(  # noqa: DJ001
        "Tipo de anestesia",
        max_length=16,
        choices=AnesthesiaType.choices,
        null=True,
        blank=True,
    )
    notes = models.TextField("Observações", blank=True)

    created_by = models.ForeignKey(
        "core.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="surgical_cases_created",
        verbose_name="Criado por",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Caso Cirúrgico"
        verbose_name_plural = "Casos Cirúrgicos"
        indexes = [
            models.Index(fields=["patient", "status"], name="emr_surgcase_pat_status_idx"),
            models.Index(fields=["status", "scheduled_start"], name="emr_surgcase_status_dt_idx"),
            models.Index(
                fields=["operating_room", "scheduled_start"], name="emr_surgcase_or_dt_idx"
            ),
        ]

    def __str__(self):
        return f"Cirurgia {self.patient} ({self.get_status_display()})"


# ─── C1: procedimento planejado do caso ───────────────────────────────────────


class SurgicalProcedure(models.Model):
    """A planned procedure (TUSS) of a :class:`SurgicalCase`. Per-tenant.

    ``tuss_code`` points to ``core.TUSSCode`` (SHARED/public schema). PostgreSQL
    does not enforce FK integrity across schemas, so — exactly like
    ``emr.EncounterProcedure.tuss_code`` — it uses ``on_delete=DO_NOTHING`` and the
    ``protect_tuss_code_deletion`` pre_delete signal (apps/core/signals.py) blocks
    deleting a code any tenant references.
    """

    class Laterality(models.TextChoices):
        ESQUERDA = "esquerda", "Esquerda"
        DIREITA = "direita", "Direita"
        BILATERAL = "bilateral", "Bilateral"
        NA = "na", "Não se aplica"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey(
        SurgicalCase,
        on_delete=models.CASCADE,
        related_name="procedures",
        verbose_name="Caso cirúrgico",
    )
    # FK to PUBLIC-schema TUSSCode from a TENANT-schema model. DO_NOTHING + the
    # protect_tuss_code_deletion pre_delete signal, mirroring EncounterProcedure
    # (PROTECT would crash the cross-schema deletion Collector — see module docstring).
    tuss_code = models.ForeignKey(
        "core.TUSSCode",
        on_delete=models.DO_NOTHING,
        related_name="surgical_procedures",
        verbose_name="Procedimento (TUSS)",
    )
    quantity = models.PositiveIntegerField("Quantidade", default=1)
    laterality = models.CharField(
        "Lateralidade",
        max_length=16,
        choices=Laterality.choices,
        blank=True,
        default="",
    )
    notes = models.TextField("Observações", blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "Procedimento Cirúrgico"
        verbose_name_plural = "Procedimentos Cirúrgicos"
        indexes = [
            models.Index(fields=["case"], name="emr_surgproc_case_idx"),
        ]

    @property
    def tuss_code_value(self) -> str:
        """Null-safe read accessor for the linked TUSS code string (else '')."""
        if self.tuss_code_id:
            return self.tuss_code.code
        return ""

    def __str__(self):
        return f"{self.tuss_code_id} × {self.quantity} — {self.case_id}"
