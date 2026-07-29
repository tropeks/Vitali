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
from django.utils import timezone

__all__ = [
    "OperatingRoom",
    "SurgicalCase",
    "SurgicalProcedure",
    "SurgicalTeamMember",
    "SurgicalTime",
    "SurgicalChecklist",
    "SurgicalMaterial",
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


# ─── C3: equipe cirúrgica do caso ─────────────────────────────────────────────


class SurgicalTeamMember(models.Model):
    """A professional on a :class:`SurgicalCase`'s team, in a given ``role``.

    Per-tenant, fully CRUD via the API (add/remove members). Unique per
    ``(case, professional, role)`` — the same professional may hold two distinct
    roles on a case, but not the same role twice.
    """

    class Role(models.TextChoices):
        CIRURGIAO = "cirurgiao", "Cirurgião"
        PRIMEIRO_AUXILIAR = "primeiro_auxiliar", "Primeiro auxiliar"
        ANESTESISTA = "anestesista", "Anestesista"
        INSTRUMENTADOR = "instrumentador", "Instrumentador"
        CIRCULANTE = "circulante", "Circulante"
        OUTRO = "outro", "Outro"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey(
        SurgicalCase,
        on_delete=models.CASCADE,
        related_name="team",
        verbose_name="Caso cirúrgico",
    )
    professional = models.ForeignKey(
        "emr.Professional",
        on_delete=models.PROTECT,
        related_name="surgical_team_memberships",
        verbose_name="Profissional",
    )
    role = models.CharField("Função", max_length=24, choices=Role.choices)
    notes = models.TextField("Observações", blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["role", "created_at"]
        verbose_name = "Membro da Equipe Cirúrgica"
        verbose_name_plural = "Equipe Cirúrgica"
        constraints = [
            models.UniqueConstraint(
                fields=["case", "professional", "role"],
                name="uniq_surg_team_case_prof_role",
            ),
        ]
        indexes = [
            models.Index(fields=["case"], name="emr_surgteam_case_idx"),
        ]

    def __str__(self):
        return f"{self.get_role_display()} — {self.professional_id} ({self.case_id})"


# ─── C3: registro de tempos (append-only) ─────────────────────────────────────


class SurgicalTime(models.Model):
    """Append-only intra-op time-stamp log for a :class:`SurgicalCase`.

    Mirrors the append-only shape of ``emr.AdmissionEvent`` /
    ``emr.MedicationAdministration`` — rows are created (via the intra-op
    service), never edited/deleted; the DRF surface is read-only. Certain events
    also advance the case status (documented in
    :mod:`apps.emr.services.surgery_intraop`): ``sala_entrada`` → ``em_sala``,
    ``incisao`` → ``em_andamento``, ``sala_saida`` → ``finalizada``.
    """

    class Event(models.TextChoices):
        SALA_ENTRADA = "sala_entrada", "Entrada na sala"
        ANESTESIA_INICIO = "anestesia_inicio", "Início da anestesia"
        ANESTESIA_FIM = "anestesia_fim", "Fim da anestesia"
        INCISAO = "incisao", "Incisão"
        FECHAMENTO = "fechamento", "Fechamento"
        SALA_SAIDA = "sala_saida", "Saída da sala"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey(
        SurgicalCase,
        on_delete=models.PROTECT,
        related_name="times",
        verbose_name="Caso cirúrgico",
    )
    event = models.CharField("Evento", max_length=20, choices=Event.choices, db_index=True)
    recorded_at = models.DateTimeField("Registrado em", default=timezone.now)
    recorded_by = models.ForeignKey(
        "core.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="surgical_times",
        verbose_name="Registrado por",
    )
    notes = models.TextField("Observações", blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["recorded_at", "created_at"]
        verbose_name = "Tempo Cirúrgico"
        verbose_name_plural = "Tempos Cirúrgicos"
        indexes = [
            models.Index(fields=["case", "recorded_at"], name="emr_surgtime_case_dt_idx"),
        ]

    def __str__(self):
        return f"{self.get_event_display()} — {self.case_id} @ {self.recorded_at:%d/%m %H:%M}"


# ─── C3: checklist de cirurgia segura (OMS), append-only por fase ─────────────


class SurgicalChecklist(models.Model):
    """The WHO safe-surgery checklist confirmed for one phase of a case.

    Per-tenant, append-only per phase: a ``(case, phase)`` pair is confirmed
    exactly once (unique constraint) and never edited afterwards; the DRF
    surface is read-only (confirmed via the intra-op service action). ``items``
    holds the confirmed checklist items for the phase as a JSON object, e.g.
    ``{"identidade_confirmada": true, "sitio_marcado": true, ...}``.
    """

    class Phase(models.TextChoices):
        SIGN_IN = "sign_in", "Sign in (antes da anestesia)"
        TIME_OUT = "time_out", "Time out (antes da incisão)"
        SIGN_OUT = "sign_out", "Sign out (antes de sair da sala)"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey(
        SurgicalCase,
        on_delete=models.PROTECT,
        related_name="checklists",
        verbose_name="Caso cirúrgico",
    )
    phase = models.CharField("Fase", max_length=12, choices=Phase.choices, db_index=True)
    items = models.JSONField("Itens confirmados", default=dict, blank=True)
    confirmed_at = models.DateTimeField("Confirmado em", default=timezone.now)
    confirmed_by = models.ForeignKey(
        "core.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="surgical_checklists",
        verbose_name="Confirmado por",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["confirmed_at", "created_at"]
        verbose_name = "Checklist de Cirurgia Segura"
        verbose_name_plural = "Checklists de Cirurgia Segura"
        constraints = [
            models.UniqueConstraint(
                fields=["case", "phase"],
                name="uniq_surg_checklist_case_phase",
            ),
        ]
        indexes = [
            models.Index(fields=["case", "phase"], name="emr_surgcl_case_phase_idx"),
        ]

    def __str__(self):
        return f"{self.get_phase_display()} — {self.case_id}"


# ─── C6: OPME / materiais planejados + consumidos do caso ─────────────────────


class SurgicalMaterial(models.Model):
    """A planned/consumed material or OPME of a :class:`SurgicalCase`. Per-tenant.

    Tracks both the *planned* quantity (``quantity_planned``) and the *consumed*
    quantity (``quantity_consumed``, advanced only through
    :func:`apps.emr.services.surgery_materials.record_consumption`). ``stock_item``
    optionally maps the material to a catalogued pharmacy lot
    (``pharmacy.StockItem``) — both models are TENANT-schema, so a normal FK is
    fine (no cross-schema DO_NOTHING dance, which is only for tenant→SHARED). It
    uses ``PROTECT`` so a referenced stock lot cannot be deleted while a surgical
    material points at it. When ``stock_item`` is null the material is an
    uncatalogued OPME whose free-text ``description`` / ``lot`` / ``serial`` carry
    the rastreabilidade.
    """

    class Kind(models.TextChoices):
        OPME = "opme", "OPME"
        MATERIAL = "material", "Material"
        MEDICAMENTO = "medicamento", "Medicamento"
        OUTRO = "outro", "Outro"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey(
        SurgicalCase,
        on_delete=models.CASCADE,
        related_name="materials",
        verbose_name="Caso cirúrgico",
    )
    kind = models.CharField("Tipo", max_length=12, choices=Kind.choices, db_index=True)
    # Optional link to a catalogued pharmacy lot. Same-schema (TENANT) FK, so a
    # normal FK — PROTECT so a referenced stock lot can't be deleted.
    stock_item = models.ForeignKey(
        "pharmacy.StockItem",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="surgical_materials",
        verbose_name="Lote de estoque",
    )
    # Optional link to the Simpro price catalog (SHARED/public schema, B4a). It is
    # the material's national price reference, off which the billing bridge (B4b,
    # apps.billing.services.material_billing.bill_surgical_materials_for_case)
    # resolves the negotiated value per convênio. PostgreSQL does not enforce FK
    # integrity across schemas (tenant → public), so — exactly like
    # ``SurgicalProcedure.tuss_code`` → ``core.TUSSCode`` — it uses
    # ``on_delete=DO_NOTHING`` and relies on the ``protect_simpro_material_deletion``
    # pre_delete signal (apps/core/signals.py), extended in B4b to cover this FK, to
    # block deleting a Simpro item any tenant references. A null ``simpro`` is an
    # uncatalogued OPME/material — not billable, flagged as glosa risk by the bridge.
    simpro = models.ForeignKey(
        "core.SimproMaterial",
        on_delete=models.DO_NOTHING,
        null=True,
        blank=True,
        related_name="surgical_materials",
        verbose_name="Material Simpro (catálogo)",
    )
    description = models.CharField("Descrição", max_length=300, blank=True)
    quantity_planned = models.PositiveIntegerField("Quantidade planejada", default=1)
    quantity_consumed = models.PositiveIntegerField("Quantidade consumida", default=0)
    laterality = models.CharField(
        "Lateralidade",
        max_length=16,
        choices=SurgicalProcedure.Laterality.choices,
        blank=True,
        default="",
    )
    # OPME rastreabilidade.
    lot = models.CharField("Lote (OPME)", max_length=100, blank=True)
    serial = models.CharField("Número de série (OPME)", max_length=100, blank=True)
    manufacturer = models.CharField("Fabricante", max_length=200, blank=True)
    notes = models.TextField("Observações", blank=True)

    created_by = models.ForeignKey(
        "core.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="surgical_materials_created",
        verbose_name="Criado por",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "Material / OPME Cirúrgico"
        verbose_name_plural = "Materiais / OPME Cirúrgicos"
        indexes = [
            models.Index(fields=["case"], name="emr_surgmat_case_idx"),
            models.Index(fields=["case", "kind"], name="emr_surgmat_case_kind_idx"),
        ]

    def __str__(self):
        label = self.description or self.get_kind_display()
        return f"{label} — {self.case_id} ({self.quantity_consumed}/{self.quantity_planned})"
