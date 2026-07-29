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
    "AnestheticRecord",
    "AnestheticEvent",
    "PacuRecord",
    "PacuAssessment",
    "RoomTurnover",
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
    turnover_minutes = models.PositiveSmallIntegerField(
        "Turnover (min)",
        default=30,
        help_text="Intervalo mínimo de higienização/preparo entre cirurgias, em minutos.",
    )

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


# ─── CC2: ficha anestésica (registro do ato anestésico intraoperatório) ───────


class AnestheticRecord(models.Model):
    """The anesthetic record (ficha anestésica) of a :class:`SurgicalCase`.

    One per case (``OneToOneField``): the clinical documentation of the
    *anesthetic act* itself, distinct from ``SurgicalCase.anesthesia_type`` (which
    is only the planned *type*) and from ``SurgicalCase.porte_anestesico`` (the
    billing/catalog code). It holds the responsible anesthesiologist, the applied
    ``technique``, the ASA physical-status classification (anesthetic risk),
    the anesthesia start/end window and free-text notes. The intra-op timeline
    (drugs, vitals, events) lives in the append-only :class:`AnestheticEvent`.

    ``technique`` reuses ``SurgicalCase.AnesthesiaType.choices`` on purpose — the
    ficha's applied technique is the same vocabulary as the case's planned type,
    keeping a single source of truth (they can legitimately differ, e.g. a planned
    ``geral`` converted to ``sedacao`` intra-op, so it is a separate field).
    """

    class ASAClassification(models.TextChoices):
        # ASA physical status (American Society of Anesthesiologists). The ``_E``
        # suffix marks an emergency procedure (per the ASA spec), so each class
        # has a plain and an emergency variant.
        ASA_I = "I", "ASA I — paciente saudável"
        ASA_II = "II", "ASA II — doença sistêmica leve"
        ASA_III = "III", "ASA III — doença sistêmica grave"
        ASA_IV = "IV", "ASA IV — doença sistêmica grave, ameaça constante à vida"
        ASA_V = "V", "ASA V — moribundo, não sobrevive sem cirurgia"
        ASA_VI = "VI", "ASA VI — morte encefálica (doador de órgãos)"
        ASA_I_E = "IE", "ASA I-E — emergência"
        ASA_II_E = "IIE", "ASA II-E — emergência"
        ASA_III_E = "IIIE", "ASA III-E — emergência"
        ASA_IV_E = "IVE", "ASA IV-E — emergência"
        ASA_V_E = "VE", "ASA V-E — emergência"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.OneToOneField(
        SurgicalCase,
        on_delete=models.CASCADE,
        related_name="anesthetic_record",
        verbose_name="Caso cirúrgico",
    )
    anesthesiologist = models.ForeignKey(
        "emr.Professional",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="anesthetic_records",
        verbose_name="Anestesista responsável",
    )
    # Applied anesthetic technique — reuses SurgicalCase.AnesthesiaType vocabulary.
    technique = models.CharField(
        "Técnica anestésica",
        max_length=16,
        choices=SurgicalCase.AnesthesiaType.choices,
        blank=True,
        default="",
    )
    asa_classification = models.CharField(
        "Classificação ASA",
        max_length=8,
        choices=ASAClassification.choices,
        blank=True,
        default="",
    )
    anesthesia_start = models.DateTimeField("Início da anestesia", null=True, blank=True)
    anesthesia_end = models.DateTimeField("Fim da anestesia", null=True, blank=True)
    notes = models.TextField("Observações", blank=True)

    created_by = models.ForeignKey(
        "core.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="anesthetic_records_created",
        verbose_name="Criado por",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Ficha Anestésica"
        verbose_name_plural = "Fichas Anestésicas"
        indexes = [
            models.Index(fields=["case"], name="emr_anestrec_case_idx"),
        ]

    def __str__(self):
        return f"Ficha anestésica — {self.case_id}"


class AnestheticEvent(models.Model):
    """An append-only entry on an :class:`AnestheticRecord`'s intra-op timeline.

    Mirrors the append-only shape of ``SurgicalTime`` — rows are created, never
    edited/deleted. A ``kind`` classifies the entry (drug administered, vital
    sign noted, intercorrência/marco, ventilation change); ``dose`` (e.g.
    ``"2mg/kg"``) and ``value`` (e.g. ``"PA 120/80, FC 72"``) are free-text
    qualifiers whose meaning depends on the ``kind``.
    """

    class Kind(models.TextChoices):
        DROGA = "droga", "Droga / medicamento"
        VITAL = "vital", "Sinal vital"
        EVENTO = "evento", "Evento / intercorrência"
        VENTILACAO = "ventilacao", "Ventilação"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    record = models.ForeignKey(
        AnestheticRecord,
        on_delete=models.CASCADE,
        related_name="events",
        verbose_name="Ficha anestésica",
    )
    timestamp = models.DateTimeField("Horário", default=timezone.now)
    kind = models.CharField("Tipo", max_length=16, choices=Kind.choices, db_index=True)
    description = models.CharField("Descrição", max_length=300)
    dose = models.CharField("Dose", max_length=100, blank=True)
    value = models.CharField("Valor", max_length=200, blank=True)
    recorded_by = models.ForeignKey(
        "core.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="anesthetic_events",
        verbose_name="Registrado por",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["timestamp", "created_at"]
        verbose_name = "Evento Anestésico"
        verbose_name_plural = "Eventos Anestésicos"
        indexes = [
            models.Index(fields=["record", "timestamp"], name="emr_anestevt_rec_dt_idx"),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} — {self.record_id} @ {self.timestamp:%d/%m %H:%M}"


# ─── CS2: SRPA / PACU — recuperação pós-anestésica ────────────────────────────


class PacuRecord(models.Model):
    """The post-anesthesia recovery (SRPA / PACU) record of a :class:`SurgicalCase`.

    One per case (``OneToOneField``): after the surgery the patient is admitted to
    the SRPA (Sala de Recuperação Pós-Anestésica), assessed with the Aldrete score
    and eventually discharged to the ward / ICU / home. This holds the admission
    (who received the patient, entry time, admission Aldrete), the discharge
    (destination, time, discharge Aldrete, criteria-met flag) and free-text notes.
    The periodic assessments during the stay live in the append-only
    :class:`PacuAssessment` timeline.

    The classic SRPA discharge criterion is an Aldrete score ≥ 9; this is **not**
    enforced here — ``aldrete_discharge`` is a free field and the clinical
    decision is captured by the explicit ``discharge_criteria_met`` boolean, so a
    site may apply its own protocol (e.g. modified Aldrete, PADSS).
    """

    class DischargeDestination(models.TextChoices):
        ENFERMARIA = "enfermaria", "Enfermaria"
        UTI = "uti", "UTI"
        ALTA = "alta", "Alta (casa)"
        OBITO = "obito", "Óbito"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.OneToOneField(
        SurgicalCase,
        on_delete=models.CASCADE,
        related_name="pacu_record",
        verbose_name="Caso cirúrgico",
    )
    admitted_at = models.DateTimeField("Entrada na SRPA", null=True, blank=True)
    # Nurse who received the patient in the SRPA. PROTECT so a professional with
    # SRPA admissions cannot be deleted.
    admitted_by = models.ForeignKey(
        "emr.Professional",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="pacu_admissions",
        verbose_name="Recebido por",
    )
    aldrete_admission = models.PositiveSmallIntegerField(
        "Aldrete na entrada",
        null=True,
        blank=True,
        help_text="Escore de Aldrete na admissão à SRPA (0–10).",
    )
    aldrete_discharge = models.PositiveSmallIntegerField(
        "Aldrete na alta",
        null=True,
        blank=True,
        help_text="Escore de Aldrete na alta da SRPA (0–10; ≥ 9 é o critério clássico de alta).",
    )
    discharged_at = models.DateTimeField("Alta da SRPA", null=True, blank=True)
    discharge_destination = models.CharField(
        "Destino na alta",
        max_length=16,
        choices=DischargeDestination.choices,
        blank=True,
        default="",
    )
    discharge_criteria_met = models.BooleanField(
        "Critérios de alta atingidos",
        default=False,
        help_text="Critérios de alta da SRPA atingidos (decisão clínica).",
    )
    notes = models.TextField("Observações", blank=True)

    created_by = models.ForeignKey(
        "core.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pacu_records_created",
        verbose_name="Criado por",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Registro de SRPA (Recuperação Pós-Anestésica)"
        verbose_name_plural = "Registros de SRPA (Recuperação Pós-Anestésica)"
        indexes = [
            models.Index(fields=["case"], name="emr_pacurec_case_idx"),
        ]

    def __str__(self):
        return f"SRPA — {self.case_id}"


class PacuAssessment(models.Model):
    """An append-only periodic assessment on a :class:`PacuRecord`'s SRPA timeline.

    Mirrors the append-only shape of ``AnestheticEvent`` / ``SurgicalTime`` — rows
    are created, never edited/deleted. Each row is one Aldrete evaluation during
    the recovery stay. The 5 Aldrete components (``activity`` / ``respiration`` /
    ``circulation`` / ``consciousness`` / ``oxygen``) are each scored 0–2 (their
    sum is the Aldrete score, 0–10); they are optional so a site may record only
    the aggregate ``aldrete_score`` + ``notes`` instead of the breakdown.
    ``pain_score`` is a 0–10 pain scale captured alongside.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    record = models.ForeignKey(
        PacuRecord,
        on_delete=models.CASCADE,
        related_name="assessments",
        verbose_name="Registro de SRPA",
    )
    assessed_at = models.DateTimeField("Avaliado em", default=timezone.now)
    aldrete_score = models.PositiveSmallIntegerField(
        "Escore de Aldrete",
        null=True,
        blank=True,
        help_text="Escore de Aldrete agregado (0–10).",
    )
    # The 5 Aldrete components, each 0–2 (optional; their sum = aldrete_score).
    consciousness = models.PositiveSmallIntegerField(
        "Consciência", null=True, blank=True, help_text="Componente Aldrete (0–2)."
    )
    respiration = models.PositiveSmallIntegerField(
        "Respiração", null=True, blank=True, help_text="Componente Aldrete (0–2)."
    )
    circulation = models.PositiveSmallIntegerField(
        "Circulação", null=True, blank=True, help_text="Componente Aldrete (0–2)."
    )
    activity = models.PositiveSmallIntegerField(
        "Atividade", null=True, blank=True, help_text="Componente Aldrete (0–2)."
    )
    oxygen = models.PositiveSmallIntegerField(
        "Saturação de O₂", null=True, blank=True, help_text="Componente Aldrete (0–2)."
    )
    pain_score = models.PositiveSmallIntegerField(
        "Escore de dor", null=True, blank=True, help_text="Escala de dor (0–10)."
    )
    notes = models.CharField("Observações", max_length=300, blank=True)
    recorded_by = models.ForeignKey(
        "emr.Professional",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pacu_assessments",
        verbose_name="Registrado por",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["assessed_at", "created_at"]
        verbose_name = "Avaliação de SRPA"
        verbose_name_plural = "Avaliações de SRPA"
        indexes = [
            models.Index(fields=["record", "assessed_at"], name="emr_pacuassess_rec_dt_idx"),
        ]

    def __str__(self):
        return f"Aldrete {self.aldrete_score} — {self.record_id} @ {self.assessed_at:%d/%m %H:%M}"


# ─── CS3: turnover de sala (limpeza/preparo entre duas cirurgias) ──────────────


class RoomTurnover(models.Model):
    """The turnover (higienização/preparo) of an :class:`OperatingRoom` between
    two surgical cases.

    Records the cleaning/preparation window a room needs between the case that
    just left (``case_out``) and the next one (``case_in``): when the room was
    freed (``started_at``), when cleaning finished (``cleaning_done_at``) and when
    it became ready again (``ready_at``), plus who performed it (``performed_by``).
    The minimum required gap itself is ``OperatingRoom.turnover_minutes``, enforced
    by the scheduling service (``_assert_turnover_respected``); this model is the
    operational *log* of an actual turnover.

    Both case links are ``SET_NULL`` (a turnover survives a case being detached)
    and optional — a turnover may be opened for a room with only the outgoing case
    known, the incoming one filled in later.
    """

    class Status(models.TextChoices):
        AGUARDANDO = "aguardando", "Aguardando limpeza"
        EM_LIMPEZA = "em_limpeza", "Em limpeza"
        PRONTA = "pronta", "Pronta"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    operating_room = models.ForeignKey(
        OperatingRoom,
        on_delete=models.PROTECT,
        related_name="turnovers",
        verbose_name="Sala cirúrgica",
    )
    case_out = models.ForeignKey(
        SurgicalCase,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="turnover_out",
        verbose_name="Cirurgia que saiu",
    )
    case_in = models.ForeignKey(
        SurgicalCase,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="turnover_in",
        verbose_name="Próxima cirurgia",
    )
    started_at = models.DateTimeField(
        "Início do turnover",
        default=timezone.now,
        help_text="Momento em que a sala foi liberada / início do turnover.",
    )
    cleaning_done_at = models.DateTimeField("Limpeza concluída em", null=True, blank=True)
    ready_at = models.DateTimeField("Sala pronta em", null=True, blank=True)
    status = models.CharField(
        "Situação",
        max_length=12,
        choices=Status.choices,
        default=Status.AGUARDANDO,
        db_index=True,
    )
    performed_by = models.ForeignKey(
        "emr.Professional",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="room_turnovers",
        verbose_name="Higienizado por",
    )
    notes = models.TextField("Observações", blank=True)

    created_by = models.ForeignKey(
        "core.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="room_turnovers_created",
        verbose_name="Criado por",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-started_at", "-created_at"]
        verbose_name = "Turnover de Sala"
        verbose_name_plural = "Turnovers de Sala"
        indexes = [
            models.Index(fields=["operating_room", "started_at"], name="emr_turnover_or_dt_idx"),
        ]

    def __str__(self):
        return f"Turnover {self.operating_room_id} @ {self.started_at:%d/%m %H:%M} ({self.status})"
