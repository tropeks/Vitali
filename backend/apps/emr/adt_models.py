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
    "BedStatusEvent",
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

    class IsolationPrecaution(models.TextChoices):
        NENHUMA = "nenhuma", "Nenhuma"
        CONTATO = "contato", "Contato"
        GOTICULA = "goticula", "Gotícula"
        AEROSSOL = "aerossol", "Aerossol"
        PROTETOR = "protetor", "Protetor (reverso)"

    # ── Taxonomias TISS 4.01.00 (Resumo de Internação, ctm_internacaoResumoGuia) ──
    # Valores extraídos programaticamente (lxml) de
    # apps/billing/schemas/tissSimpleTypesV4_01_00.xsd — os CODES (``value``) são
    # exatos, copiados do ``xs:enumeration`` de cada ``simpleType``. O XSD NÃO traz
    # ``xs:documentation`` para nenhum desses domínios, então os rótulos em
    # português não vêm do schema: são o texto oficial das tabelas de domínio da
    # ANS para os domínios pequenos e estáveis (caráter/tipo/regime, ≤5 valores
    # cada), e ficam explicitamente marcados como "a confirmar" para os códigos de
    # ``dm_motivoSaida`` (34) que não têm precedente testado no repo — não
    # fabricar rótulo clínico/financeiro sem checar o manual ANS (ver
    # docs/research/VITALI_ONDA4_TISS_MODELAGEM.md §5/§8). Mesmo padrão de
    # ``AihAutorizacao.CaraterInternacao``/``MotivoSaida`` (apps/billing/sus_models.py):
    # os códigos SUS daquele precedente ('01'/'02') são DIFERENTES dos códigos TISS
    # aqui ('1'/'2') — não são o mesmo domínio, apesar da semântica parecida.
    class CaraterAtendimento(models.TextChoices):
        """TISS ``dm_caraterAtendimento``. NÃO confundir com o código SUS
        ``AihAutorizacao.CaraterInternacao`` ('01'/'02') — domínios distintos."""

        ELETIVO = "1", "Eletivo"
        URGENCIA_EMERGENCIA = "2", "Urgência/Emergência"

    class TipoInternacao(models.TextChoices):
        """TISS ``dm_tipoInternacao`` — especialidade da internação (não é a
        origem: isso é ``AdmissionSource``)."""

        CLINICO = "1", "Clínico"
        CIRURGICO = "2", "Cirúrgico"
        OBSTETRICO = "3", "Obstétrico"
        PEDIATRICO = "4", "Pediátrico"
        PSIQUIATRICO = "5", "Psiquiátrico"

    class RegimeInternacao(models.TextChoices):
        """TISS ``dm_regimeInternacao``."""

        HOSPITALAR = "1", "Hospitalar"
        HOSPITAL_DIA = "2", "Hospital-dia"
        DOMICILIAR = "3", "Domiciliar"

    class MotivoEncerramento(models.TextChoices):
        """TISS ``dm_motivoSaida`` (28 códigos, tabela de domínio 34 —
        ``dadosSaidaInternacao.motivoEncerramento``). NÃO substitui
        ``Admission.disposition`` (vocabulário clínico da equipe assistencial,
        já usado pela tela de alta) — é um segundo campo, preenchido junto, só
        para a guia TISS.

        Códigos 11–32 têm rótulo confirmado (tabela clássica de motivo de
        saída/permanência, idêntica em estrutura à usada por AihAutorizacao/SUS,
        historicamente estável). Códigos 41–67 são exclusivos do domínio TISS
        (sem equivalente na tabela SUS) e o rótulo NÃO foi conferido contra o
        manual de tabelas de domínio da ANS — marcados explicitamente como
        pendente em vez de arriscar um rótulo clínico/financeiro inventado.
        """

        ALTA_MELHORADO = "11", "Alta melhorado"
        ALTA_A_PEDIDO = "12", "Alta a pedido"
        ALTA_POR_EVASAO = "14", "Alta por evasão"
        ALTA_PREVISAO_RETORNO = "15", "Alta com previsão de retorno para acompanhamento do paciente"
        ALTA_OUTROS_MOTIVOS = "16", "Alta por outros motivos"
        ALTA_PUERPERA_RN = "18", "Alta da puérpera e do recém-nascido"
        ALTA_PUERPERA = "19", "Alta da puérpera"
        TRANSFERENCIA_DOMICILIAR = "21", "Transferência para internação domiciliar"
        PERMANENCIA_DOENCA = "22", "Permanência por características próprias da doença"
        PERMANENCIA_INTERCORRENCIA = "23", "Permanência por intercorrência"
        PERMANENCIA_IMPOSSIBILIDADE_SOCIAL = "24", "Permanência por impossibilidade social"
        TRANSFERENCIA_OUTRO_ESTABELECIMENTO = "25", "Transferência para outro estabelecimento"
        PERMANENCIA_OUTROS_MOTIVOS = "26", "Permanência por outros motivos"
        OBITO_DO_MEDICO_ASSISTENTE = (
            "27",
            "Óbito com declaração de óbito fornecida pelo médico assistente",
        )
        OBITO_DO_IML = "28", "Óbito com declaração de óbito fornecida pelo IML"
        OBITO_DO_SVO = "31", "Óbito com declaração de óbito fornecida pelo SVO"
        ENCERRAMENTO_ADMINISTRATIVO = "32", "Encerramento administrativo"
        # Faixa 41–67: só o código é confiável (extraído do XSD); rótulo pendente.
        CODIGO_41 = "41", "Código 41 (rótulo a confirmar no manual ANS)"
        CODIGO_42 = "42", "Código 42 (rótulo a confirmar no manual ANS)"
        CODIGO_43 = "43", "Código 43 (rótulo a confirmar no manual ANS)"
        CODIGO_51 = "51", "Código 51 (rótulo a confirmar no manual ANS)"
        CODIGO_61 = "61", "Código 61 (rótulo a confirmar no manual ANS)"
        CODIGO_62 = "62", "Código 62 (rótulo a confirmar no manual ANS)"
        CODIGO_63 = "63", "Código 63 (rótulo a confirmar no manual ANS)"
        CODIGO_64 = "64", "Código 64 (rótulo a confirmar no manual ANS)"
        CODIGO_65 = "65", "Código 65 (rótulo a confirmar no manual ANS)"
        CODIGO_66 = "66", "Código 66 (rótulo a confirmar no manual ANS)"
        CODIGO_67 = "67", "Código 67 (rótulo a confirmar no manual ANS)"

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
    # Precaução de isolamento: quando != nenhuma, o leito ocupado DEVE estar num
    # quarto de isolamento (Room.isolation=True). Gateado no admit/transfer.
    isolation_precaution = models.CharField(
        "Precaução de isolamento",
        max_length=16,
        choices=IsolationPrecaution.choices,
        default=IsolationPrecaution.NENHUMA,
        db_index=True,
    )

    # ── Taxonomias TISS 4.01.00 (Resumo de Internação) ────────────────────────
    # Todos opcionais (blank=True, default=""): internações já gravadas continuam
    # válidas sem backfill, e a guia TISS de internação só existe para uma parte
    # das internações (nem toda internação vira faturamento TISS). Capturados na
    # admissão (carater/tipo/regime) e na alta (disposition_ans_code) — mesmo
    # ponto de entrada dos campos clínicos irmãos (admission_source/disposition).
    carater_atendimento = models.CharField(  # noqa: DJ001
        "Caráter do atendimento (TISS)",
        max_length=1,
        choices=CaraterAtendimento.choices,
        blank=True,
        default="",
        help_text="dm_caraterAtendimento — eletivo ou urgência/emergência, para a guia TISS.",
    )
    tipo_internacao = models.CharField(  # noqa: DJ001
        "Tipo de internação (TISS)",
        max_length=1,
        choices=TipoInternacao.choices,
        blank=True,
        default="",
        help_text="dm_tipoInternacao — especialidade da internação, para a guia TISS.",
    )
    regime_internacao = models.CharField(  # noqa: DJ001
        "Regime de internação (TISS)",
        max_length=1,
        choices=RegimeInternacao.choices,
        blank=True,
        default="",
        help_text="dm_regimeInternacao — hospitalar/hospital-dia/domiciliar, para a guia TISS.",
    )
    # NÃO substitui `disposition` (vocabulário clínico da tela de alta) — campo
    # irmão, preenchido na mesma ação, só para <dadosSaidaInternacao> da guia.
    disposition_ans_code = models.CharField(  # noqa: DJ001
        "Motivo de encerramento (TISS)",
        max_length=2,
        choices=MotivoEncerramento.choices,
        blank=True,
        default="",
        help_text="dm_motivoSaida — motivo de encerramento ANS, para a guia TISS de internação.",
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
        PLAN = "plan_discharge", "Alta planejada"

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


class BedStatusEvent(models.Model):
    """Append-only log of a Bed's operational ``status`` transitions.

    Complements :class:`AdmissionEvent` (which tracks the *patient's* movement)
    by tracking the *bed's* housekeeping cycle: a discharge/transfer sends the
    freed bed to ``higienizacao`` (dirty) and the housekeeping release returns it
    to ``livre`` (clean). Each transition writes exactly one row inside the
    service ``transaction.atomic`` so the bed's cycle is fully auditable (who
    cleaned it, when). Rows are created, never edited/deleted; the DRF surface is
    read-only, mirroring :class:`AdmissionEvent`.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    bed = models.ForeignKey(
        Bed, on_delete=models.PROTECT, related_name="status_events", verbose_name="Leito"
    )
    from_status = models.CharField("Situação anterior", max_length=16, choices=Bed.Status.choices)
    to_status = models.CharField(
        "Nova situação", max_length=16, choices=Bed.Status.choices, db_index=True
    )
    actor = models.ForeignKey(
        "core.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bed_status_events",
        verbose_name="Responsável",
    )
    reason = models.TextField("Motivo", blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "Evento de leito"
        verbose_name_plural = "Eventos de leito"
        indexes = [
            models.Index(fields=["bed", "created_at"], name="emr_bedevt_bed_dt_idx"),
        ]

    def __str__(self):
        return (
            f"{self.from_status}→{self.to_status} — {self.bed_id} @ {self.created_at:%d/%m %H:%M}"
        )
