"""
ADT/Leitos domain — physical bed hierarchy (Sprint L1)
======================================================

The L1 sprint shipped the governed :class:`~apps.core.adt_catalog_models.BedType`
**catalog** (CNES bed types, master data in the SHARED/public schema). This
module adds the **tenant-side physical structure** that consumes it — the
ala/unidade → quarto → leito hierarchy:

    InpatientUnit (ala/unidade de internação)
        →  Room (quarto)
            →  Bed (leito)   ── status enum + governed BedType FK

No admission / transfer / census here — those are L2/L3. This sprint models only
the static bed structure + its CRUD API and RBAC.

Cross-schema FK pattern (tenant → SHARED catalog)
-------------------------------------------------
PostgreSQL does not enforce FK integrity across schemas (tenant → public), so —
**exactly like** ``emr.NursingDiagnosis.nanda`` / ``organization.Facility.cnes``
— the ``Bed.bed_type`` catalog reference uses ``on_delete=DO_NOTHING`` and relies
on the matching ``pre_delete`` PROTECT signal in :mod:`apps.core.signals`
(``protect_bed_type_deletion``) to block deleting a bed type any tenant
references. The FK is nullable and paired with a ``legacy_bed_type_text`` free
column + a ``bed_type_unmatched`` flag, surfaced through a backward-compatible
``bed_type_code`` string accessor — the same reconcile-safe shape as ``cbo`` /
``cnes`` / ``nanda``.

Kept in a dedicated module (re-exported by ``models.py`` with a single
``from .adt_models import *``) so the parent-worktree merge touches ``models.py``
by exactly one line — mirroring ``sae_models``.
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils import timezone

__all__ = [
    "InpatientUnit",
    "Room",
    "Bed",
    "Admission",
    "AdmissionEvent",
]


# ─── L1: ala/unidade de internação ───────────────────────────────────────────


class InpatientUnit(models.Model):
    """An inpatient unit (ala/unidade de internação) hanging off a Facility.

    The top of the physical bed hierarchy: rooms and beds hang off a unit. An
    optional ``default_bed_type`` seeds the governed type for new beds in the
    unit (e.g. a UTI unit defaults its beds to the UTI bed type).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    facility = models.ForeignKey(
        "organization.Facility",
        on_delete=models.PROTECT,
        related_name="inpatient_units",
        verbose_name="Estabelecimento",
    )
    name = models.CharField("Nome", max_length=200)
    code = models.CharField(
        "Código", max_length=50, help_text="Código da unidade (único por estabelecimento)."
    )
    active = models.BooleanField("Ativa", default=True, db_index=True)

    # ── governed cross-schema FK to the SHARED core.BedType catalog ───────────
    # DO_NOTHING + protect_bed_type_deletion pre_delete signal, mirroring
    # emr.NursingDiagnosis.nanda. Nullable — a unit need not pin a default type.
    default_bed_type = models.ForeignKey(
        "core.BedType",
        on_delete=models.DO_NOTHING,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Tipo de leito padrão",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Unidade de Internação"
        verbose_name_plural = "Unidades de Internação"
        constraints = [
            models.UniqueConstraint(
                fields=["facility", "code"],
                name="uniq_inpatient_unit_code_per_facility",
            ),
        ]
        indexes = [
            models.Index(fields=["facility", "active"], name="emr_inpunit_fac_active_idx"),
        ]

    def __str__(self):
        return f"{self.code} — {self.name}"


# ─── L1: quarto ──────────────────────────────────────────────────────────────


class Room(models.Model):
    """A room (quarto) inside an inpatient unit; beds hang off a room.

    Minimal gender/isolation flags are kept here (they inform bed assignment in
    L2) but no assignment logic lives in L1.
    """

    class Gender(models.TextChoices):
        ANY = "any", "Indiferente"
        MALE = "male", "Masculino"
        FEMALE = "female", "Feminino"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    unit = models.ForeignKey(
        InpatientUnit, on_delete=models.CASCADE, related_name="rooms", verbose_name="Unidade"
    )
    name = models.CharField(
        "Nome/número", max_length=50, help_text="Nome ou número do quarto (único por unidade)."
    )
    gender = models.CharField(
        "Gênero", max_length=8, choices=Gender.choices, default=Gender.ANY, db_index=True
    )
    isolation = models.BooleanField(
        "Isolamento", default=False, help_text="Quarto destinado a isolamento."
    )
    active = models.BooleanField("Ativo", default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Quarto"
        verbose_name_plural = "Quartos"
        constraints = [
            models.UniqueConstraint(
                fields=["unit", "name"],
                name="uniq_room_name_per_unit",
            ),
        ]
        indexes = [
            models.Index(fields=["unit", "active"], name="emr_room_unit_active_idx"),
        ]

    def __str__(self):
        return f"Quarto {self.name} — {self.unit}"


# ─── L1: leito ───────────────────────────────────────────────────────────────


class Bed(models.Model):
    """A physical bed (leito) inside a room.

    Carries the operational ``status`` (livre / ocupado / higienizacao /
    bloqueado / reservado / interditado — default livre) that L2/L3 admission &
    census drive, and a governed cross-schema ``bed_type`` FK to the SHARED
    ``core.BedType`` catalog (reconcile-safe, same shape as ``nanda``). A
    denormalized ``unit`` FK enables fast per-unit queries without joining
    through the room.
    """

    class Status(models.TextChoices):
        LIVRE = "livre", "Livre"
        OCUPADO = "ocupado", "Ocupado"
        HIGIENIZACAO = "higienizacao", "Em higienização"
        BLOQUEADO = "bloqueado", "Bloqueado"
        RESERVADO = "reservado", "Reservado"
        INTERDITADO = "interditado", "Interditado"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room = models.ForeignKey(
        Room, on_delete=models.CASCADE, related_name="beds", verbose_name="Quarto"
    )
    # Denormalized unit FK for fast per-unit census/queries (kept in sync with
    # room.unit at the API layer). PROTECT so a unit with beds can't vanish.
    unit = models.ForeignKey(
        InpatientUnit, on_delete=models.PROTECT, related_name="beds", verbose_name="Unidade"
    )
    identifier = models.CharField(
        "Identificador",
        max_length=50,
        help_text="Código/identificador do leito (único por unidade).",
    )
    status = models.CharField(
        "Situação",
        max_length=16,
        choices=Status.choices,
        default=Status.LIVRE,
        db_index=True,
    )

    # ── governed cross-schema FK to the SHARED core.BedType catalog ───────────
    # DO_NOTHING + protect_bed_type_deletion pre_delete signal, mirroring
    # emr.NursingDiagnosis.nanda exactly (nullable FK + legacy free text +
    # unmatched flag + backward-compatible ``bed_type_code`` accessor).
    bed_type = models.ForeignKey(
        "core.BedType",
        on_delete=models.DO_NOTHING,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Tipo de leito",
    )
    legacy_bed_type_text = models.CharField(
        max_length=32,
        blank=True,
        default="",
        help_text="Código de tipo de leito bruto não reconciliado com core.BedType.",
    )
    bed_type_unmatched = models.BooleanField(
        default=False,
        help_text="True quando legacy_bed_type_text não corresponde a nenhum BedType governado.",
    )

    active = models.BooleanField("Ativo", default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["identifier"]
        verbose_name = "Leito"
        verbose_name_plural = "Leitos"
        constraints = [
            models.UniqueConstraint(
                fields=["unit", "identifier"],
                name="uniq_bed_identifier_per_unit",
            ),
        ]
        indexes = [
            models.Index(fields=["unit", "status"], name="emr_bed_unit_status_idx"),
            models.Index(fields=["room"], name="emr_bed_room_idx"),
        ]

    @property
    def bed_type_code(self) -> str:
        """Bed-type code string: the governed FK's code when linked, else raw legacy text."""
        if self.bed_type_id:
            return self.bed_type.code  # type: ignore[union-attr]
        return self.legacy_bed_type_text

    @bed_type_code.setter
    def bed_type_code(self, value: str) -> None:
        code = (value or "").strip()
        if not code:
            self.bed_type = None
            self.legacy_bed_type_text = ""
            self.bed_type_unmatched = False
            return
        from apps.core.models import BedType

        match = BedType.objects.filter(code=code).first()
        if match is not None:
            self.bed_type = match
            self.legacy_bed_type_text = ""
            self.bed_type_unmatched = False
        else:
            self.bed_type = None
            self.legacy_bed_type_text = code
            self.bed_type_unmatched = True

    def __str__(self):
        return f"Leito {self.identifier} ({self.get_status_display()}) — {self.unit}"


# ─── L2: admissão/internação ─────────────────────────────────────────────────


class Admission(models.Model):
    """An inpatient stay (internação): a patient occupying a Bed over time.

    The bed-occupancy state machine (admit → [transfer] → discharge) is driven
    through :mod:`apps.emr.services.adt` — never by raw ``save`` — so the Bed's
    operational ``status`` and the append-only :class:`AdmissionEvent` log stay
    consistent in one ``transaction.atomic``. A DB partial-unique constraint
    guarantees at most one *active* (status=admitted) admission per bed.

    L3 (transfer/census) consumes this model + :class:`AdmissionEvent`: transfer
    will move ``current_bed`` and append a ``transfer`` event (both from/to bed);
    census reads active admissions per unit via ``current_bed__unit``.
    """

    class AdmissionSource(models.TextChoices):
        EMERGENCIA = "emergencia", "Emergência"
        AMBULATORIO = "ambulatorio", "Ambulatório"
        TRANSFERENCIA_EXTERNA = "transferencia_externa", "Transferência externa"
        CENTRO_CIRURGICO = "centro_cirurgico", "Centro cirúrgico"
        OUTRO = "outro", "Outro"

    class Disposition(models.TextChoices):
        ALTA_MELHORADA = "alta_melhorada", "Alta melhorada"
        ALTA_A_PEDIDO = "alta_a_pedido", "Alta a pedido"
        TRANSFERENCIA_EXTERNA = "transferencia_externa", "Transferência externa"
        OBITO = "obito", "Óbito"
        EVASAO = "evasao", "Evasão"
        OUTRO = "outro", "Outro"

    class Status(models.TextChoices):
        ADMITTED = "admitted", "Internado"
        DISCHARGED = "discharged", "Alta"
        CANCELLED = "cancelled", "Cancelada"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey(
        "emr.Patient", on_delete=models.PROTECT, related_name="admissions", verbose_name="Paciente"
    )
    admitting_professional = models.ForeignKey(
        "emr.Professional",
        on_delete=models.PROTECT,
        related_name="admissions_admitted",
        verbose_name="Profissional internador",
    )
    attending_professional = models.ForeignKey(
        "emr.Professional",
        on_delete=models.PROTECT,
        related_name="admissions_attending",
        verbose_name="Profissional responsável",
    )
    # Nullable: freed on discharge (bed released), set/moved on admit/transfer.
    current_bed = models.ForeignKey(
        Bed,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="admissions",
        verbose_name="Leito atual",
    )
    # Optional link to the admission Encounter (encounter_type=internacao).
    encounter = models.ForeignKey(
        "emr.Encounter",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="admissions",
        verbose_name="Encontro de internação",
    )

    admission_source = models.CharField(
        "Origem da internação",
        max_length=32,
        choices=AdmissionSource.choices,
        default=AdmissionSource.OUTRO,
    )
    admission_datetime = models.DateTimeField("Data/hora da internação", default=timezone.now)
    expected_discharge_datetime = models.DateTimeField("Alta prevista", null=True, blank=True)
    actual_discharge_datetime = models.DateTimeField("Alta efetiva", null=True, blank=True)
    # NULL = ainda sem desfecho (internação ativa); distinto de "" — DJ001 suprimido
    # conforme convenção do repo.
    disposition = models.CharField(  # noqa: DJ001
        "Desfecho",
        max_length=32,
        choices=Disposition.choices,
        null=True,
        blank=True,
    )
    status = models.CharField(
        "Situação",
        max_length=16,
        choices=Status.choices,
        default=Status.ADMITTED,
        db_index=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-admission_datetime"]
        verbose_name = "Internação"
        verbose_name_plural = "Internações"
        constraints = [
            # At most ONE active admission per bed (partial unique on the active
            # status). NULL current_bed rows (discharged) are exempt.
            models.UniqueConstraint(
                fields=["current_bed"],
                condition=models.Q(status="admitted", current_bed__isnull=False),
                name="uniq_active_admission_per_bed",
            ),
        ]
        indexes = [
            models.Index(fields=["patient", "status"], name="emr_adm_patient_status_idx"),
            models.Index(fields=["status", "admission_datetime"], name="emr_adm_status_dt_idx"),
        ]

    def __str__(self):
        return f"Internação {self.patient} ({self.get_status_display()})"


class AdmissionEvent(models.Model):
    """Append-only ADT event log for an :class:`Admission`.

    Mirrors the append-only shape of ``emr.MedicationAdministration`` — rows are
    created, never edited/deleted; the DRF surface is read-only. Every occupancy
    transition (admit / transfer / discharge / cancel) writes exactly one event
    inside the service's ``transaction.atomic``. ``from_bed``/``to_bed`` capture
    the movement (admit: to only; discharge: from only; transfer: both).
    """

    class EventType(models.TextChoices):
        ADMIT = "admit", "Admissão"
        TRANSFER = "transfer", "Transferência"
        DISCHARGE = "discharge", "Alta"
        CANCEL = "cancel", "Cancelamento"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    admission = models.ForeignKey(
        Admission, on_delete=models.PROTECT, related_name="events", verbose_name="Internação"
    )
    event_type = models.CharField(
        "Tipo de evento", max_length=16, choices=EventType.choices, db_index=True
    )
    from_bed = models.ForeignKey(
        Bed,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="admission_events_from",
        verbose_name="Leito de origem",
    )
    to_bed = models.ForeignKey(
        Bed,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="admission_events_to",
        verbose_name="Leito de destino",
    )
    actor = models.ForeignKey(
        "core.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="admission_events",
        verbose_name="Responsável",
    )
    reason = models.TextField("Motivo", blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "Evento ADT"
        verbose_name_plural = "Eventos ADT"
        indexes = [
            models.Index(fields=["admission", "created_at"], name="emr_admevt_adm_dt_idx"),
        ]

    def __str__(self):
        return (
            f"{self.get_event_type_display()} — {self.admission_id} @ {self.created_at:%d/%m %H:%M}"
        )
