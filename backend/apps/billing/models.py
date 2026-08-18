"""
Billing Models — TISS/TUSS
==========================
Per-tenant (lives in each clinic's schema).

Cross-schema FK note: TUSSCode lives in the public schema. PostgreSQL does not
enforce referential integrity across schemas, so on_delete=PROTECT here is
application-layer enforcement only. A pre-delete signal on TUSSCode (see
apps/core/signals.py) compensates by checking live references.
"""

import uuid
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.db.models import Sum
from django.utils import timezone

# ─── Choices ─────────────────────────────────────────────────────────────────

GUIDE_STATUS = [
    ("draft", "Rascunho"),
    ("pending", "Pendente envio"),
    ("submitted", "Enviado"),
    ("paid", "Pago"),
    ("denied", "Glosado"),
    ("appeal", "Em recurso"),
]

BATCH_STATUS = [
    ("open", "Aberto"),
    ("closed", "Fechado"),
    ("submitted", "Enviado"),
    ("processed", "Processado"),
    ("cancelled", "Cancelado"),
]

# Statuses that make a batch "active" for double-submit purposes: a guide that
# already belongs to a batch in any of these statuses must not be added to a
# different batch (it would be billed twice). "cancelled" is intentionally
# excluded — a cancelled batch never reaches the insurer, so its guides are free
# to be re-batched. "processed" is also excluded for backward compatibility with
# the retorno flow (a processed batch is already settled, not pending billing).
ACTIVE_BATCH_STATUSES = ["open", "closed", "submitted"]

GLOSA_REASON_CODES = [
    ("00", "Não informado"),
    ("01", "Procedimento não coberto"),
    ("02", "Incompatibilidade de sexo"),
    ("03", "Incompatibilidade de idade"),
    ("04", "Prazo de carência"),
    ("05", "Inconsistência nos dados do beneficiário"),
    # ANS TISS 4.01 — Tabela 38 (Terminologia de mensagens: glosas, negativas e
    # outras). "1702" is the standard procedure-level duplicate-billing reason
    # ("Cobrança de procedimento em duplicidade"); it is what the deterministic
    # duplicate check maps to (see GlosaChecker.ANS_CODE_DUPLICATE) and what the
    # retorno parser must recognise instead of downgrading an inbound duplicate
    # glosa to the generic "99".
    ("1702", "Cobrança de procedimento em duplicidade"),
    ("99", "Outro"),
]

APPEAL_STATUS = [
    ("none", "Sem recurso"),
    ("filed", "Recurso enviado"),
    ("accepted", "Recurso aceito"),
    ("rejected", "Recurso rejeitado"),
]


# ─── Price / Provider ─────────────────────────────────────────────────────────


class InsuranceProvider(models.Model):
    """Operadora de saúde (convênio). Per-tenant."""

    name = models.CharField("Nome", max_length=200)
    ans_code = models.CharField("Código ANS", max_length=20, unique=True)
    cnpj = models.CharField("CNPJ", max_length=18, blank=True)
    is_active = models.BooleanField("Ativo", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Operadora"
        verbose_name_plural = "Operadoras"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} (ANS {self.ans_code})"


class PriceTable(models.Model):
    """Tabela de preços negociada com uma operadora. Per-tenant."""

    provider = models.ForeignKey(
        InsuranceProvider, on_delete=models.CASCADE, related_name="price_tables"
    )
    name = models.CharField("Nome", max_length=100)
    valid_from = models.DateField("Válida a partir de")
    valid_until = models.DateField("Válida até", null=True, blank=True)
    is_active = models.BooleanField("Ativa", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Tabela de Preços"
        verbose_name_plural = "Tabelas de Preços"
        unique_together = [("provider", "valid_from")]
        ordering = ["provider", "-valid_from"]

    def clean(self):
        # Prevent overlapping validity windows for the same provider.
        if self.valid_until and self.valid_until < self.valid_from:
            raise ValidationError(
                {"valid_until": "Data de fim deve ser posterior à data de início."}
            )
        qs = PriceTable.objects.filter(provider=self.provider).exclude(pk=self.pk)
        for other in qs:
            other_end = other.valid_until
            self_end = self.valid_until
            # open-ended table overlaps everything after its start
            if other_end is None or other_end >= self.valid_from:
                if self_end is None or self_end >= other.valid_from:
                    raise ValidationError(f"Tabela de preços sobrepõe período com '{other.name}'")

    def save(self, *args, **kwargs):
        # Guarantee clean() runs on every save path (ORM, fixtures, tests).
        # Prevents overlapping validity windows from slipping past serializer validation.
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        until = self.valid_until.strftime("%m/%Y") if self.valid_until else "em aberto"
        return f"{self.name} ({self.valid_from.strftime('%m/%Y')} – {until})"


class PriceTableItem(models.Model):
    """Preço negociado por código TUSS em uma tabela. Per-tenant."""

    table = models.ForeignKey(PriceTable, on_delete=models.CASCADE, related_name="items")
    # FK to public-schema TUSSCode — app-layer PROTECT only (cross-schema limit)
    tuss_code = models.ForeignKey(
        "core.TUSSCode", on_delete=models.PROTECT, related_name="price_table_items"
    )
    negotiated_value = models.DecimalField(
        "Valor negociado (R$)",
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
    )
    # Per-procedure quantity ceiling negotiated in the contract (glosa wedge G3c).
    # NULL = no ceiling (default): the quantity_exceeds check stays INERT. When
    # set, a guide line whose quantity exceeds this value gets an ADVISE finding
    # (never a block). This is contract TRUTH supplied by the establishment's
    # price-table import/config — never fabricated in code. The MONTHLY aggregate
    # ceiling is deliberately OUT OF SCOPE (race + cost in close()); this is the
    # per-line ceiling only.
    max_per_procedure = models.PositiveIntegerField(
        "Teto de quantidade por procedimento",
        null=True,
        blank=True,
        help_text="Quantidade máxima por procedimento no contrato. Vazio = sem teto.",
    )
    # Does this contracted procedure REQUIRE prior authorization (senha)? (glosa
    # wedge G3d). Default False → the authorization_missing glosa check stays
    # INERT for every item until the establishment explicitly marks the item as
    # requiring authorization. Only when True does the engine demand a valid
    # authorization (guide.authorization_number filled OR a matching approved
    # Authorization row). This keeps procedures that need NO senha (most
    # consultas/SADT) from being false-flagged. Contract TRUTH supplied by the
    # establishment's price-table config — never fabricated in code.
    requires_authorization = models.BooleanField(
        "Exige autorização prévia",
        default=False,
        help_text="Se marcado, o procedimento exige autorização (senha) válida para faturar.",
    )

    class Meta:
        verbose_name = "Item de Tabela"
        verbose_name_plural = "Itens de Tabela"
        unique_together = [("table", "tuss_code")]

    def __str__(self):
        return f"{self.tuss_code.code} — R${self.negotiated_value}"


class Authorization(models.Model):
    """Autorização prévia (senha) de um procedimento por uma operadora. Per-tenant.

    Glosa wedge G3d. Records an operator's prior authorization for a patient. The
    glosa engine consults these (via the orchestrator) ONLY for items whose active
    PriceTableItem is flagged ``requires_authorization=True``; otherwise the check
    is inert.

    A row "covers" a guide line when status=approved, its validity window contains
    the guide's effective date (valid_from <= date <= valid_until-or-open), it
    matches the guide's patient + provider, and either its ``tuss_code`` matches
    the line's TUSS or ``tuss_code`` is NULL (a GENERIC authorization that covers
    any procedure / a generic encounter authorization).

    Cross-schema FK note: ``tuss_code`` points at the PUBLIC-schema TUSSCode.
    PostgreSQL does NOT enforce referential integrity across schemas, so
    on_delete=PROTECT is application-layer only — identical to PriceTableItem and
    TISSGuideItem; a pre-delete signal on TUSSCode compensates (see
    apps/core/signals.py).
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pendente"
        APPROVED = "approved", "Aprovada"
        DENIED = "denied", "Negada"

    patient = models.ForeignKey(
        "emr.Patient", on_delete=models.CASCADE, related_name="authorizations"
    )
    provider = models.ForeignKey(
        InsuranceProvider, on_delete=models.CASCADE, related_name="authorizations"
    )
    # FK to public-schema TUSSCode — app-layer PROTECT only (cross-schema limit).
    # NULL = a GENERIC authorization covering ANY procedure / a generic encounter
    # authorization (the orchestrator treats it as a wildcard).
    tuss_code = models.ForeignKey(
        "core.TUSSCode",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="authorizations",
        help_text="Procedimento autorizado. Vazio = autorização genérica (qualquer procedimento).",
    )
    valid_from = models.DateField("Válida a partir de")
    valid_until = models.DateField(
        "Válida até",
        null=True,
        blank=True,
        help_text="Vazio = sem data de término (autorização em aberto).",
    )
    status = models.CharField(
        "Status", max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    authorization_number = models.CharField("Número da autorização", max_length=20, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Autorização"
        verbose_name_plural = "Autorizações"
        ordering = ["-valid_from"]
        indexes = [
            models.Index(fields=["patient", "provider", "status"]),
            models.Index(fields=["tuss_code"]),
            models.Index(fields=["valid_from", "valid_until"]),
        ]

    def __str__(self):
        target = self.tuss_code.code if self.tuss_code_id else "genérica"
        return f"Autorização {self.authorization_number or '—'} ({target}) — {self.get_status_display()}"


# ─── TISS Guides ─────────────────────────────────────────────────────────────


class TISSGuide(models.Model):
    """
    Guia TISS — SP/SADT ou Consulta. Per-tenant.

    guide_number is generated atomically: YYYYMM + 6-digit sequence per tenant.
    insured_card_number is copied from PatientInsurance.card_number (decrypted)
    at guide-creation time; stored plain here because TISS XML requires it in
    plaintext anyway.
    """

    class TipoFaturamento(models.TextChoices):
        """TISS ``dm_tipoFaturamento`` — filho obrigatório de ``ctm_internacaoDados``
        (``dadosInternacao.tipoFaturamento``), enum fechado ``['1','2','3','4']``
        extraído programaticamente (lxml) de
        ``apps/billing/schemas/tissSimpleTypesV4_01_00.xsd``.

        MORA AQUI, NÃO EM ``emr.Admission`` (diverge de
        docs/research/VITALI_ONDA4_TISS_MODELAGEM.md §5, escrito antes da medição
        do XSD): os irmãos de sequência ``dataInicioFaturamento``/
        ``dataFinalFaturamento`` provam que ``ctm_internacaoDados`` descreve o
        PERÍODO DE FATURAMENTO daquela guia, não a estada. Uma internação longa
        pode render uma guia parcial e depois uma final — e ``tipoFaturamento`` é
        justamente o que as distingue. Se o campo morasse na ``Admission``, as
        duas guias da MESMA internação teriam de compartilhar um único valor, o
        que é uma contradição. É atributo do documento, não do paciente.

        RÓTULOS PENDENTES, DE PROPÓSITO. Os ``xs:enumeration`` do XSD não trazem
        ``xs:documentation`` (zero ocorrências em tissSimpleTypesV4_01_00.xsd e
        tissGuiasV4_01_00.xsd — só ``tissComplexTypesV4_01_00.xsd`` tem 13, todas
        de estruturas de recurso de glosa/protocolo, nenhuma de domínio) e não há
        manual de tabelas de domínio da ANS versionado neste repo. Então só o
        CÓDIGO é confiável. Mesmo tratamento dado aos códigos 41–67 de
        ``emr.Admission.MotivoEncerramento`` e mesma linha vermelha registrada em
        ``import_tuss.py``/``inpatient_models.py``: um rótulo financeiro inventado
        numa tela de faturamento hospitalar é pior que rótulo ausente — quem
        preenche escolhe errado com confiança. Substituir por texto real assim que
        o manual ANS entrar no repo, sem migration de dado (só ``choices``).
        """

        CODIGO_1 = "1", "Código 1 (rótulo a confirmar no manual ANS)"
        CODIGO_2 = "2", "Código 2 (rótulo a confirmar no manual ANS)"
        CODIGO_3 = "3", "Código 3 (rótulo a confirmar no manual ANS)"
        CODIGO_4 = "4", "Código 4 (rótulo a confirmar no manual ANS)"

    guide_number = models.CharField("Número da guia", max_length=20, unique=True, blank=True)
    guide_type = models.CharField(
        "Tipo",
        max_length=20,
        choices=[
            ("sadt", "SP/SADT"),
            ("consulta", "Consulta"),
            ("honorarios", "Honorários"),
            ("internacao", "Resumo de Internação"),
        ],
    )
    encounter = models.ForeignKey(
        "emr.Encounter", on_delete=models.PROTECT, related_name="tiss_guides"
    )
    patient = models.ForeignKey("emr.Patient", on_delete=models.PROTECT, related_name="tiss_guides")
    provider = models.ForeignKey(InsuranceProvider, on_delete=models.PROTECT, related_name="guides")
    # ── S4-T3: Honorários guide (guia de honorários médicos) ─────────────────────
    # The executing professional whose honorário this guide bills. Same-schema FK
    # (emr is per-tenant). NULL for non-honorarios guides.
    executor = models.ForeignKey(
        "emr.Professional",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="honorario_guides",
        help_text="Profissional executor (guia de honorários). Vazio nas demais guias.",
    )
    # Cross-schema FK to public-schema CBHPMItem — app-layer PROTECT only (like
    # PriceTableItem.tuss_code). Drives porte-based valuation of the honorário.
    honorario_cbhpm = models.ForeignKey(
        "core.CBHPMItem",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="honorario_guides",
        help_text="Procedimento CBHPM que valora o honorário (porte × valor-CH).",
    )
    honorario_value = models.DecimalField(
        "Valor do honorário (R$)", max_digits=12, decimal_places=4, default=Decimal("0")
    )
    price_table = models.ForeignKey(
        PriceTable, on_delete=models.SET_NULL, null=True, blank=True, related_name="guides"
    )
    # ── M2-S3-T4: LabOrder → SP/SADT bridge ──────────────────────────────────────
    # Same-schema FK (emr and billing are both tenant apps) linking a SADT guide
    # to the finalized LabOrder that generated it. Nullable — set only on guides
    # auto-generated from the lab. Its uniqueness (enforced below) is what makes
    # the LabOrder→guide generation IDEMPOTENT: at most one guide per lab order.
    lab_order = models.ForeignKey(
        "emr.LabOrder",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tiss_guides",
        help_text="Pedido de exames que originou esta guia (ponte LIS→faturamento).",
    )
    # ── B1: SurgicalCase → SP/SADT bridge ────────────────────────────────────────
    # Same-schema FK (emr and billing are both tenant apps) linking a SADT guide to
    # the FINALIZED SurgicalCase that generated it. Nullable — set only on guides
    # auto-generated from the Centro Cirúrgico. Its uniqueness (enforced below) is
    # what makes SurgicalCase→guide generation IDEMPOTENT: at most one guide per
    # case. SET_NULL so a case delete never destroys the billing record.
    surgical_case = models.ForeignKey(
        "emr.SurgicalCase",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tiss_guides",
        help_text="Caso cirúrgico que originou esta guia (ponte Centro Cirúrgico→faturamento).",
    )
    # ── B3: Admission → Resumo de Internação bridge ──────────────────────────────
    # Same-schema FK (emr and billing are both tenant apps) linking an internação
    # guide to the Admission whose accumulated DailyCharges it bills. Nullable — set
    # only on guides auto-generated from a internação. Its uniqueness (enforced
    # below) is what makes Admission→guide generation IDEMPOTENT: at most one
    # internação guide per admission. SET_NULL so an admission delete never
    # destroys the billing record.
    # Quem SOLICITOU o que a guia SP/SADT cobra — distinto de quem executou.
    #
    # `dadosSolicitante` (ctm_sp-sadtGuia) é obrigatório e exige conselho, número,
    # UF e CBOS do profissional solicitante. O Vitali nunca modelou esse papel: o
    # executante vem de `encounter.professional`, e usar ELE aqui declararia à
    # operadora que quem pediu o exame foi quem o fez — invenção, não placeholder.
    # Por isso um campo próprio, e não um reaproveitamento.
    #
    # Preenchido automaticamente pela ponte de laboratório a partir de
    # `LabOrder.requested_by` (o médico que pediu o exame é literalmente o
    # solicitante). Para guia de cirurgia não há fonte: `SurgicalCase` tem
    # `surgeon` (quem opera), não quem indicou — fica nulo e a emissão falha
    # alto, com o campo editável enquanto a guia é rascunho. Mesma precedência já
    # aprovada para `authorization_date`: fonte automática quando existe,
    # digitação quando não, nunca fabricação.
    requesting_professional = models.ForeignKey(
        "emr.Professional",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="requested_tiss_guides",
        verbose_name="Profissional solicitante",
        help_text=(
            "profissionalSolicitante de dadosSolicitante (SP/SADT). Resolvido de "
            "LabOrder.requested_by quando a guia nasce de um pedido de exame; "
            "informado à mão nos demais casos."
        ),
    )
    admission = models.ForeignKey(
        "emr.Admission",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tiss_guides",
        help_text="Internação que originou esta guia (ponte internação→faturamento).",
    )
    status = models.CharField(
        "Status", max_length=20, choices=GUIDE_STATUS, default="draft", db_index=True
    )
    xml_content = models.TextField("XML da guia", blank=True)
    total_value = models.DecimalField(
        "Valor total (R$)", max_digits=12, decimal_places=2, default=0
    )
    # TISS mandatory fields
    insured_card_number = models.CharField("Número da carteirinha", max_length=20)
    authorization_number = models.CharField("Senha de autorização", max_length=20, blank=True)
    # B10: manual digitação fallback for ct_autorizacaoInternacao.dataAutorizacao
    # (guiaResumoInternacao) when there is NO approved Authorization row covering
    # the guide — decisão do Capitão. Only used together with
    # authorization_number as the last-resort source; a resolved Authorization
    # row always wins. See xml_engine._resolve_internacao_authorization for the
    # precedence.
    authorization_date = models.DateField(
        "Data da autorização (digitada)",
        null=True,
        blank=True,
        help_text=(
            "Data de autorização informada manualmente pelo faturista, conforme "
            "recebida da operadora. Só é usada para preencher dataAutorizacao "
            "da guia de resumo de internação QUANDO não existe uma Authorization "
            "aprovada correspondente (paciente/operadora/janela/TUSS) — o "
            "registro de autorização, quando existe, sempre tem prioridade "
            "sobre esta digitação."
        ),
    )
    # ``dadosInternacao.tipoFaturamento`` da guia de resumo de internação. Só a
    # guia sabe se ela é o faturamento parcial ou o de fechamento da estada — ver
    # o docstring de ``TipoFaturamento`` acima para por que NÃO mora na Admission.
    #
    # ``blank=True, default=""`` (e não ``null``): guias já gravadas continuam
    # válidas sem backfill, exatamente como os campos irmãos de taxonomia TISS em
    # ``emr.Admission`` (carater_atendimento/tipo_internacao/regime_internacao/
    # disposition_ans_code). Não há valor default honesto a atribuir
    # retroativamente — nenhuma guia existente foi emitida declarando um tipo de
    # faturamento, e escolher um por elas seria inventar o que foi transmitido.
    # Vazio significa "ainda não declarado", e o gerador de XML falha alto nesse
    # caso (xml_engine._resolve_internacao_dados) em vez de chutar "1".
    #
    # A ponte automática ``generate_internacao_guide_for_admission`` deliberadamente
    # NÃO preenche este campo: ela roda na alta, mas o endpoint que a chama não é
    # exclusivo da alta e nada no fluxo prova qual dos quatro códigos se aplica.
    # É digitação do faturista, na guia, enquanto rascunho.
    tipo_faturamento = models.CharField(
        "Tipo de faturamento (TISS)",
        max_length=1,
        choices=TipoFaturamento.choices,
        blank=True,
        default="",
        help_text=(
            "dm_tipoFaturamento — declara à operadora se esta guia de resumo de "
            "internação é o faturamento parcial ou o de encerramento da estada. "
            "Obrigatório no XML (ctm_internacaoDados); sem ele a guia de "
            "internação não gera XML."
        ),
    )
    competency = models.CharField("Competência (AAAA-MM)", max_length=7, help_text="Ex: 2026-03")
    cid10_codes = models.JSONField(
        "Códigos CID-10", default=list, help_text='Lista de {"code": "X00"} do SOAPNote'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Guia TISS"
        verbose_name_plural = "Guias TISS"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["provider", "competency"]),
            models.Index(fields=["patient", "created_at"]),
        ]
        constraints = [
            # M2-S3-T4: at most ONE guide per lab order (idempotent generation).
            models.UniqueConstraint(
                fields=["lab_order"],
                condition=models.Q(lab_order__isnull=False),
                name="uniq_tiss_guide_per_lab_order",
            ),
            # B1: at most ONE guide per surgical case (idempotent generation).
            models.UniqueConstraint(
                fields=["surgical_case"],
                condition=models.Q(surgical_case__isnull=False),
                name="uniq_tiss_guide_per_surgical_case",
            ),
            # B3: at most ONE internação guide per admission (idempotent generation).
            models.UniqueConstraint(
                fields=["admission"],
                condition=models.Q(admission__isnull=False),
                name="uniq_tiss_guide_per_admission",
            ),
        ]

    def generate_guide_number(self) -> str:
        """
        Generate sequential guide number: YYYYMM + 6-digit seq.
        Must be called inside an atomic block with select_for_update.
        """
        prefix = timezone.now().strftime("%Y%m")
        last = (
            TISSGuide.objects.select_for_update()
            .filter(guide_number__startswith=prefix)
            .order_by("-guide_number")
            .first()
        )
        seq = int(last.guide_number[6:]) + 1 if last else 1
        return f"{prefix}{seq:06d}"

    def save(self, *args, **kwargs):
        if not self.guide_number:
            from django.db import IntegrityError

            for _attempt in range(3):
                with transaction.atomic():
                    self.guide_number = self.generate_guide_number()
                    try:
                        super().save(*args, **kwargs)
                        return
                    except IntegrityError:
                        self.guide_number = ""
                        continue
            raise IntegrityError("Failed to generate a unique guide number after 3 attempts.")
        super().save(*args, **kwargs)

    def price_honorario(self):
        """Value an honorários guide from its CBHPM porte (porte × valor_ch).

        Sets ``honorario_value`` from :meth:`CBHPMItem.valor` and mirrors it into
        ``total_value`` (the guide-level amount). No-op valuation (0) when no
        CBHPM is linked — never fabricates a value.
        """
        valor = self.honorario_cbhpm.valor() if self.honorario_cbhpm_id else Decimal("0")
        self.honorario_value = valor
        self.total_value = valor
        self.save(update_fields=["honorario_value", "total_value", "updated_at"])
        return self

    def __str__(self):
        return f"Guia {self.guide_number} — {self.patient}"


class ProfessionalSettlement(models.Model):
    """Periodic, idempotent professional payout/accrual."""

    STATUS_CHOICES = [("draft", "Rascunho"), ("approved", "Aprovado"), ("paid", "Pago")]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    professional = models.ForeignKey(
        "emr.Professional", on_delete=models.PROTECT, related_name="settlements"
    )
    competency = models.CharField(max_length=7, help_text="AAAA-MM")
    gross_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    deductions = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    net_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="draft")
    calculated_at = models.DateTimeField(auto_now=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    # Maker-checker (segregation of duties): the creator (maker) cannot be the
    # approver (checker). Enforced in ProfessionalSettlementViewSet.approve.
    created_by = models.ForeignKey(
        "core.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="settlements_created",
    )
    approved_by = models.ForeignKey(
        "core.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="settlements_approved",
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["professional", "competency"], name="uniq_prof_settlement_competency"
            )
        ]
        ordering = ["-competency"]

    def recalculate(self, rate=0):
        from decimal import Decimal

        from django.db.models import Sum

        total = self.professional.encounters.filter(
            encounter_date__startswith=self.competency, status="signed"
        ).aggregate(v=Sum("tiss_guides__total_value"))["v"] or Decimal("0")
        # ``rate`` may arrive as a float/int/str; coerce to Decimal so the
        # multiplication below never raises Decimal * float TypeError.
        rate_dec = Decimal(str(rate)) if rate else Decimal("1")
        self.gross_amount = total
        self.net_amount = max(Decimal("0"), total - self.deductions) * rate_dec
        return self

    def __str__(self):
        return f"Repasse {self.professional} — {self.competency}"


class AccountsReceivable(models.Model):
    """Receivable ledger entry — origin-agnostic (S4-T2).

    A receivable may originate from a TISS guia OR a private bill OR a package OR
    a PIX charge. The ``guide`` link is now nullable/optional and an ``origin``
    discriminator records the source. Partial settlement is tracked via
    ``paid_amount`` vs ``amount`` (status open/partial/received). The cost center
    is a real FK to ``organization.CostCenter``.
    """

    STATUS_CHOICES = [
        ("expected", "Previsto"),
        ("billed", "Faturado"),
        ("partial", "Parcialmente recebido"),
        ("received", "Recebido"),
        ("overdue", "Vencido"),
        ("contested", "Contestado"),
    ]
    ORIGIN_CHOICES = [
        ("tiss", "Guia TISS"),
        ("private", "Particular"),
        ("package", "Pacote"),
        ("pix", "PIX"),
        ("other", "Outro"),
    ]
    # Guia link kept for the existing TISS flow but now OPTIONAL (was OneToOne,
    # PROTECT, non-null). NULL when the receivable originates from a private
    # bill / package / PIX charge instead of a TISS guia.
    guide = models.OneToOneField(
        TISSGuide,
        on_delete=models.PROTECT,
        related_name="receivable",
        null=True,
        blank=True,
    )
    origin = models.CharField(
        "Origem", max_length=12, choices=ORIGIN_CHOICES, default="tiss", db_index=True
    )
    # Optional source discriminators for non-guia origins.
    package = models.ForeignKey(
        "billing.Package",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="receivables",
    )
    pix_charge = models.ForeignKey(
        "billing.PIXCharge",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="receivables",
    )
    cost_center = models.ForeignKey(
        "organization.CostCenter",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="receivables",
    )
    # Denormalized patient link so a receivable is patient-queryable regardless of
    # origin — guia-less private/PIX/package receivables have no guide->patient
    # path. Derived from guide.patient on save when a guia is set (M1 integration).
    patient = models.ForeignKey(
        "emr.Patient",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="receivables",
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    # Partial settlement: cumulative amount received so far. status becomes
    # 'partial' while 0 < paid_amount < amount, 'received' once it reaches amount.
    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    due_date = models.DateField(null=True, blank=True)
    received_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=12, choices=STATUS_CHOICES, default="expected", db_index=True
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "due_date"], name="billing_acc_status_ea3ffa_idx")
        ]

    def save(self, *args, **kwargs):
        # Keep the denormalized patient link in sync from the guia when present.
        if self.patient_id is None and self.guide_id is not None:
            self.patient_id = self.guide.patient_id
        super().save(*args, **kwargs)

    @property
    def remaining_amount(self) -> Decimal:
        """Amount still outstanding: ``amount − paid_amount`` (never negative)."""
        paid = self.paid_amount or Decimal("0")
        remaining = (self.amount or Decimal("0")) - paid
        return remaining if remaining > 0 else Decimal("0.00")

    def register_payment(self, value: Decimal, *, when=None):
        """Record a (possibly partial) payment against this receivable.

        Increments ``paid_amount`` and transitions status: ``partial`` while
        still outstanding, ``received`` (stamping ``received_at``) once the total
        is met or exceeded. Persists via a scoped ``update_fields`` save.
        """
        value = Decimal(str(value))
        self.paid_amount = (self.paid_amount or Decimal("0")) + value
        fields = ["paid_amount", "status", "updated_at"]
        if self.paid_amount >= (self.amount or Decimal("0")):
            self.status = "received"
            self.received_at = when or timezone.now()
            fields.append("received_at")
        elif self.paid_amount > 0:
            self.status = "partial"
        self.save(update_fields=fields)
        return self

    def __str__(self):
        ref = self.guide.guide_number if self.guide_id else self.get_origin_display()
        return f"CR {ref} — R$ {self.amount}"


class BankTransaction(models.Model):
    """Imported bank/PIX movement; immutable source with idempotent external id."""

    STATUS_CHOICES = [("unmatched", "Pendente"), ("matched", "Conciliado"), ("review", "Revisão")]
    external_id = models.CharField(max_length=180, unique=True)
    statement = models.ForeignKey(
        "BankStatementImport",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="transactions",
    )
    occurred_at = models.DateTimeField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    description = models.CharField(max_length=500, blank=True)
    status = models.CharField(
        max_length=12, choices=STATUS_CHOICES, default="unmatched", db_index=True
    )
    receivable = models.ForeignKey(
        AccountsReceivable,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="bank_transactions",
    )
    confidence = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    matched_at = models.DateTimeField(null=True, blank=True)
    matched_by = models.ForeignKey("core.User", null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-occurred_at"]
        constraints = [
            # DB-level guard: at most ONE settled ('matched') bank transaction per
            # receivable. Even if two concurrent approve() calls slipped past the
            # application locks, the second commit would violate this partial
            # unique index and fail loudly instead of double-allocating the
            # receivable. NULL receivables are exempt (they are never 'matched').
            models.UniqueConstraint(
                fields=["receivable"],
                condition=models.Q(status="matched"),
                name="uniq_matched_tx_per_receivable",
            ),
        ]

    def __str__(self):
        return f"{self.external_id} — R$ {self.amount}"


class Payable(models.Model):
    """Contas a pagar, immutable identity and explicit payment transition."""

    STATUS_CHOICES = [
        ("planned", "Prevista"),
        ("approved", "Aprovada"),
        ("paid", "Paga"),
        ("cancelled", "Cancelada"),
    ]
    external_id = models.CharField(
        max_length=180, unique=True, help_text="ID idempotente da origem"
    )
    description = models.CharField(max_length=300)
    category = models.CharField(max_length=120, blank=True)
    # S4-T2: real FK to organization.CostCenter (was a free-text CharField). Same
    # tenant schema, so a DB-enforced FK is fine. Nullable — legacy free-text
    # values with no matching CostCenter.code become NULL in the data migration.
    cost_center = models.ForeignKey(
        "organization.CostCenter",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payables",
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    due_date = models.DateField()
    paid_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=12, choices=STATUS_CHOICES, default="planned", db_index=True
    )
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        "core.User", null=True, on_delete=models.SET_NULL, related_name="payables_created"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["due_date", "-created_at"]
        indexes = [models.Index(fields=["status", "due_date"], name="billing_pay_status_due_idx")]

    def __str__(self):
        return f"CP {self.description} — R$ {self.amount}"


class CashFlowEntry(models.Model):
    """Projected/realized cash entry; external_id makes imports idempotent."""

    KIND_CHOICES = [("inflow", "Entrada"), ("outflow", "Saída")]
    STATUS_CHOICES = [
        ("forecast", "Previsto"),
        ("realized", "Realizado"),
        ("cancelled", "Cancelado"),
    ]
    external_id = models.CharField(max_length=180, unique=True)
    description = models.CharField(max_length=300)
    kind = models.CharField(max_length=8, choices=KIND_CHOICES)
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    due_date = models.DateField()
    realized_at = models.DateTimeField(null=True, blank=True)
    category = models.CharField(max_length=120, blank=True)
    cost_center = models.CharField(max_length=120, blank=True)
    status = models.CharField(
        max_length=10, choices=STATUS_CHOICES, default="forecast", db_index=True
    )
    # Maker-checker: the creator (maker) cannot be the one who realizes (checker)
    # the entry. Enforced in CashFlowEntryViewSet.realize. Nullable because
    # system-generated entries (e.g. Payable.pay's update_or_create) have no user.
    created_by = models.ForeignKey(
        "core.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="cashflow_entries_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["due_date", "-created_at"]

    def __str__(self):
        return f"{self.kind} {self.description} — R$ {self.amount}"


class AccountingCategory(models.Model):
    """Configurable chart-of-accounts category, scoped to a tenant."""

    name = models.CharField(max_length=160)
    code = models.CharField(max_length=40)
    kind = models.CharField(max_length=10, choices=[("revenue", "Receita"), ("expense", "Despesa")])
    active = models.BooleanField(default=True)

    class Meta:
        unique_together = [("code", "kind")]
        ordering = ["code", "name"]

    def __str__(self):
        return f"{self.code} — {self.name}"


class AccountingEntry(models.Model):
    """Accrual accounting entry used by DRE and cash projections."""

    category = models.ForeignKey(
        AccountingCategory, on_delete=models.PROTECT, related_name="entries"
    )
    kind = models.CharField(max_length=10, choices=[("revenue", "Receita"), ("expense", "Despesa")])
    amount = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(0)])
    competency = models.DateField(db_index=True)
    unit = models.CharField(max_length=120, blank=True)
    # S4-T2: real FK to organization.CostCenter (was a free-text CharField). See
    # Payable.cost_center for the migration rationale.
    cost_center = models.ForeignKey(
        "organization.CostCenter",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="accounting_entries",
    )
    description = models.CharField(max_length=300, blank=True)
    receivable = models.ForeignKey(
        AccountsReceivable,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="accounting_entries",
    )
    reconciled = models.BooleanField(default=False)
    created_by = models.ForeignKey("core.User", null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-competency", "-created_at"]
        indexes = [models.Index(fields=["competency", "kind"], name="billing_entry_comp_kind_idx")]

    def __str__(self):
        return f"{self.get_kind_display()} R$ {self.amount} ({self.competency:%m/%Y})"


class TISSGuideItem(models.Model):
    """Procedimento/material em uma guia TISS. Per-tenant."""

    guide = models.ForeignKey(TISSGuide, on_delete=models.CASCADE, related_name="items")
    tuss_code = models.ForeignKey(
        "core.TUSSCode", on_delete=models.PROTECT, related_name="guide_items"
    )
    description = models.CharField("Descrição", max_length=300)
    quantity = models.DecimalField("Quantidade", max_digits=8, decimal_places=2, default=1)
    unit_value = models.DecimalField("Valor unitário (R$)", max_digits=10, decimal_places=2)
    total_value = models.DecimalField("Valor total (R$)", max_digits=12, decimal_places=2)
    # ─── TISS: os dois campos que faltavam para <procedimentosExecutados> ──────
    #
    # dataExecucao (ct_procedimentoExecutadoInt, tissComplexTypesV4_01_00.xsd) é
    # OBRIGATÓRIO por item. A guia já declara o PERÍODO de faturamento
    # (dataInicioFaturamento/dataFinalFaturamento, em ctm_internacaoDados), mas a
    # operadora confere item a item: uma diária no dia 12 e um gás no dia 14 são
    # dois fatos com datas diferentes dentro do mesmo período.
    #
    # null=True porque toda linha faturada ANTES desta migration é, por definição,
    # uma linha sem data — as cinco pontes clínico→faturamento não gravavam nada
    # aqui. Backfill não existe: nem `created_at` nem o período da internação
    # dizem em que dia o item foi executado, e escrever `now()` seria carimbar a
    # data de FATURAMENTO como se fosse data clínica. A consequência é
    # deliberada: `generate_guide_xml` FALHA ALTO num item sem data (ver
    # `xml_engine._resolve_internacao_procedimentos`), do mesmo jeito que já
    # falha para as taxonomias vazias de internações antigas.
    execution_date = models.DateField(
        "Data de execução",
        null=True,
        blank=True,
        help_text=(
            "dataExecucao (ct_procedimentoExecutadoInt) — dia em que ESTE item foi "
            "executado, na data local da clínica. Vazio só em linhas anteriores à "
            "Onda 4; sem ela a guia de resumo de internação não gera XML."
        ),
    )
    # reducaoAcrescimo (ct_procedimentoExecutadoInt) é um FATOR MULTIPLICATIVO, e
    # o neutro é 1.00 — não 0. A evidência, medida com lxml sobre os XSDs deste
    # repo (docs/research/VITALI_ONDA4_TISS_MODELAGEM.md §2 propunha `default 0`,
    # e está corrigido lá):
    #
    #   1. o tipo IRMÃO `ct_procedimentoExecutado` (usado em <outrasDespesas>)
    #      chama o mesmo conceito, na mesma posição da sequência e com o MESMO
    #      tipo, de `fatorReducaoAcrescimo` — a palavra "fator" é da ANS;
    #   2. `st_decimal3-2` = totalDigits 3 + fractionDigits 2 → faixa 0,00–9,99.
    #      Isso é faixa de multiplicador. Percentual precisaria chegar a 100
    #      (0–9,99% não descreve nem uma redução de 10%); valor em reais usaria
    #      `st_decimal8-2`, o mesmo de valorUnitario/valorTotal, e não usa;
    #   3. no tipo irmão o campo é `minOccurs="0"` — omitir significa "não mexe
    #      no valor", que é exatamente o que 1.00 faz e 0.00 não faz;
    #   4. precedente do próprio repo, anterior ao doc de pesquisa:
    #      docs/DATA_MODEL.md já especificava
    #      `TISSGuideItem.reduction_factor: DECIMAL(5,4) DEFAULT 1.0`;
    #   5. com 1.00 fecha a aritmética que a operadora confere sozinha —
    #      valorTotal = valorUnitario × quantidadeExecutada × fator. Com 0.00 a
    #      guia declararia, item a item, que a linha vale ZERO e mesmo assim
    #      cobraria valorTotal: convite a glosa.
    #
    # O que NÃO está conferido: o rótulo ANS. O XSD não traz `xs:documentation`
    # e o manual de tabelas de domínio não está versionado aqui — 1.00 é o neutro
    # por CONSISTÊNCIA ARITMÉTICA, não por rótulo conferido. Mesma disciplina dos
    # "(rótulo a confirmar no manual ANS)" de TISSGuide.TipoFaturamento.
    reduction_increase_factor = models.DecimalField(
        "Fator de redução/acréscimo (TISS)",
        max_digits=3,
        decimal_places=2,
        default=Decimal("1.00"),
        help_text=(
            "reducaoAcrescimo (ct_procedimentoExecutadoInt) / fatorReducaoAcrescimo "
            "(ct_procedimentoExecutado) — multiplicador aplicado ao valor da linha. "
            "1.00 = sem redução nem acréscimo; 0.50 = metade; 1.30 = 30% a mais. "
            "Faixa do XSD: 0,00 a 9,99."
        ),
    )
    # Optional back-link to the SurgicalMaterial that produced this line (B4b OPME/
    # material bridge). Same-schema (TENANT) FK, so a normal FK — SET_NULL so a
    # deleted material does not cascade-remove a billed line. It is the idempotency
    # key the bridge (bill_surgical_materials_for_case) looks up on to avoid
    # duplicating a material line on re-run. NULL for every non-material line
    # (procedures, lab, diárias).
    surgical_material = models.ForeignKey(
        "emr.SurgicalMaterial",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="guide_items",
        verbose_name="Material cirúrgico de origem",
    )

    # ─── Categoria do breakdown de ct_guiaValorTotal ──────────────────────────
    #
    # `<valorTotal>` tem SETE campos opcionais de breakdown além do total geral
    # obrigatório. A operadora confere por eles (glosa por breakdown ausente é
    # prática real de mercado), e a soma dos sete tem de bater com
    # `valorTotalGeral`.
    #
    # POR QUE UM CAMPO, E NÃO CLASSIFICAÇÃO POR TUSS. O doc de pesquisa §4 já
    # media isso e o repo confirma: `TUSSCode.table_number` (dm_tabela) é grosso
    # demais — a tabela 18 contém diárias, taxas E gases medicinais, que são três
    # campos TISS distintos, e `TUSSCode.group` idem. Classificar por eles é
    # adivinhar. Aqui a categoria é FATO DE ORIGEM: cada ponte clínico→
    # faturamento sabe exatamente o que está criando (uma DailyCharge é diária,
    # um SurgicalMaterial.Kind.OPME é OPME, uma dispensação é medicamento) e
    # grava o que sabe, no momento em que sabe.
    #
    # `blank=True` porque nenhuma linha anterior a esta fatia tem categoria e não
    # há backfill honesto. A consequência é deliberada e está em
    # `xml_engine._resolve_valor_total`: **breakdown é tudo-ou-nada**. Se um item
    # da guia estiver sem categoria, sai só `valorTotalGeral` — um breakdown
    # parcial, que não soma o total, é PIOR que nenhum: a operadora vê uma conta
    # que não fecha e glosa a guia inteira.
    class BillingCategory(models.TextChoices):
        PROCEDIMENTOS = "procedimentos", "Procedimentos"
        DIARIAS = "diarias", "Diárias"
        TAXAS_ALUGUEIS = "taxas_alugueis", "Taxas e aluguéis"
        MATERIAIS = "materiais", "Materiais"
        MEDICAMENTOS = "medicamentos", "Medicamentos"
        OPME = "opme", "OPME"
        GASES_MEDICINAIS = "gases_medicinais", "Gases medicinais"

    billing_category = models.CharField(  # noqa: DJ001
        "Categoria no valorTotal (TISS)",
        max_length=20,
        choices=BillingCategory.choices,
        blank=True,
        default="",
        db_index=True,
        help_text=(
            "Campo de ct_guiaValorTotal em que esta linha entra. Gravado pela ponte "
            "que criou o item, nunca inferido do TUSS. Vazio = linha anterior à Onda 4; "
            "uma única assim faz a guia sair sem breakdown."
        ),
    )

    # Idempotência da dispensação de medicamento: UUID solto, NÃO FK.
    #
    # O par natural seria uma FK para ``pharmacy.Dispensation``, como
    # ``surgical_material`` é para ``emr.SurgicalMaterial``. Não dá:
    # ``apps.billing -> apps.pharmacy`` é proibido pelo import-linter e não está
    # na lista de exceções. Guardar só o UUID custa a integridade referencial
    # (apagar a dispensação não limpa nem sinaliza a linha faturada) e preserva a
    # fronteira entre os domínios — que é o que impede o faturamento de virar
    # dependência de tudo. O acoplamento acontece por sinal
    # (``core.dispensation_signals``), com payload primitivo.
    dispensation_source_id = models.UUIDField(
        "Dispensação de origem",
        null=True,
        blank=True,
        db_index=True,
        help_text="UUID da pharmacy.Dispensation que gerou esta linha (sem FK: fronteira de domínio).",
    )

    class Meta:
        verbose_name = "Item de Guia"
        verbose_name_plural = "Itens de Guia"

    def _recalc_guide_total(self):
        total = self.guide.items.aggregate(t=Sum("total_value"))["t"] or 0
        self.guide.total_value = total
        self.guide.save(update_fields=["total_value", "updated_at"])

    def save(self, *args, **kwargs):
        # O fator entra AQUI, e não só no XML, para a invariante que a operadora
        # confere (valorTotal = valorUnitario × quantidadeExecutada ×
        # reducaoAcrescimo) valer por construção, em vez de depender de o
        # template lembrar de multiplicar. Com o default 1.00 o resultado é
        # idêntico ao de antes desta fatia — nenhuma linha existente muda de
        # valor. `quantize` é explícito para o valor em memória ser o MESMO que
        # o Postgres grava em numeric(12,2): sem ele, `unit_value * quantity`
        # pode ter 4 casas e o XML sairia de um número que o banco arredondou.
        factor = self.reduction_increase_factor
        if factor is None:  # defesa: alguém escreveu None por update() direto
            factor = Decimal("1.00")
        self.total_value = (self.unit_value * self.quantity * factor).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        super().save(*args, **kwargs)
        self._recalc_guide_total()

    def delete(self, *args, **kwargs):
        super().delete(*args, **kwargs)
        self._recalc_guide_total()

    def __str__(self):
        return f"{self.tuss_code.code} × {self.quantity} — Guia {self.guide.guide_number}"


# ─── TISS Batches ─────────────────────────────────────────────────────────────


class TISSBatch(models.Model):
    """
    Lote TISS — agrupa guias para envio a uma operadora. Per-tenant.

    Double-submit protection: a guide already in a closed/submitted batch
    cannot be added to another batch (enforced in clean()).
    """

    batch_number = models.CharField("Número do lote", max_length=20, unique=True, blank=True)
    provider = models.ForeignKey(
        InsuranceProvider, on_delete=models.PROTECT, related_name="batches"
    )
    guides = models.ManyToManyField(TISSGuide, related_name="batches", blank=True)
    status = models.CharField(
        "Status", max_length=20, choices=BATCH_STATUS, default="open", db_index=True
    )
    xml_file = models.CharField("Arquivo XML (path)", max_length=500, blank=True)
    retorno_xml_file = models.CharField(
        "Retorno XML (path)",
        max_length=500,
        blank=True,
        help_text="Path to the raw retorno XML from the insurer — stored for audit trail.",
    )
    total_value = models.DecimalField(
        "Valor total (R$)", max_digits=14, decimal_places=2, default=0
    )
    created_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Lote TISS"
        verbose_name_plural = "Lotes TISS"
        ordering = ["-created_at"]

    def generate_batch_number(self) -> str:
        prefix = timezone.now().strftime("%Y%m")
        last = (
            TISSBatch.objects.select_for_update()
            .filter(batch_number__startswith=prefix)
            .order_by("-batch_number")
            .first()
        )
        seq = int(last.batch_number[6:]) + 1 if last else 1
        return f"{prefix}{seq:04d}"

    def save(self, *args, **kwargs):
        if not self.batch_number:
            from django.db import IntegrityError

            for _attempt in range(3):
                with transaction.atomic():
                    self.batch_number = self.generate_batch_number()
                    try:
                        super().save(*args, **kwargs)
                        return
                    except IntegrityError:
                        self.batch_number = ""
                        continue
            raise IntegrityError("Failed to generate a unique batch number after 3 attempts.")
        else:
            super().save(*args, **kwargs)

    def check_guide_not_double_submitted(self, guide: TISSGuide, statuses=None) -> None:
        """
        Raise ValidationError if the guide already belongs to ANOTHER batch in a
        conflicting status.

        By default the conflicting set is ACTIVE_BATCH_STATUSES (open/closed/
        submitted) — i.e. a guide already in any non-cancelled, billable batch
        cannot be added to a different one. This closes the add-time window where
        the same guide could sit in two open batches simultaneously and then be
        closed twice.

        The current batch is always excluded (``.exclude(pk=self.pk)``) so that
        re-saving/editing a batch does not flag its own guides. Cancelled batches
        never conflict, since they are excluded from the status set.

        ``statuses`` can be overridden (e.g. at close time, to check only against
        already-finalised batches) — see TISSBatchViewSet.close.
        """
        if statuses is None:
            statuses = ACTIVE_BATCH_STATUSES
        conflict = (
            TISSBatch.objects.filter(
                guides=guide,
                status__in=statuses,
            )
            .exclude(pk=self.pk)
            .first()
        )
        if conflict:
            raise ValidationError(
                f"Guia {guide.guide_number} já consta no lote {conflict.batch_number} "
                f"(status: {conflict.get_status_display()}). Double-billing bloqueado."
            )

    def __str__(self):
        return f"Lote {self.batch_number} — {self.provider.name}"


def _tissbatch_m2m_changed(sender, instance, action, pk_set, **kwargs):
    """
    Enforce double-submit protection when guides are added via M2M directly
    (bypasses the serializer layer). Runs on m2m_changed signal for
    TISSBatch.guides through-table.

    The handler fires for BOTH directions of the relation:
      • forward  — ``batch.guides.add(guide)``   → instance is a TISSBatch,
                    pk_set holds GUIDE pks.
      • reverse  — ``guide.batches.add(batch)``   → instance is a TISSGuide,
                    pk_set holds BATCH pks.
    We detect which side ``instance`` is and run the check for each
    (batch, guide) pair accordingly. Previously this assumed ``instance`` was
    always a TISSBatch, so the reverse path looked up batch pks as guide pks and
    crashed / silently skipped the check.
    """
    if action != "pre_add" or not pk_set:
        return

    if isinstance(instance, TISSBatch):
        batch = instance
        for guide in TISSGuide.objects.filter(pk__in=pk_set):
            batch.check_guide_not_double_submitted(guide)
    elif isinstance(instance, TISSGuide):
        guide = instance
        for batch in TISSBatch.objects.filter(pk__in=pk_set):
            batch.check_guide_not_double_submitted(guide)


from django.db.models.signals import m2m_changed  # noqa: E402

m2m_changed.connect(_tissbatch_m2m_changed, sender=TISSBatch.guides.through)


# ─── S-055: PIX Payment ───────────────────────────────────────────────────────


class PIXCharge(models.Model):
    """
    Tracks a PIX payment charge created via Asaas for a self-pay appointment.
    Per-tenant schema.

    Lifecycle: pending → paid (via webhook) | expired (via Celery beat at expires_at)
                        ↘ refunded (manual, Phase 2)

    LGPD note: we store asaas_customer_id (not raw CPF). The mapping from
    Patient → Asaas customer ID is maintained in AsaasService.get_or_create_customer().
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Aguardando pagamento"
        PAID = "paid", "Pago"
        EXPIRED = "expired", "Expirado"
        CANCELLED = "cancelled", "Cancelado"
        REFUNDED = "refunded", "Estornado"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    appointment = models.OneToOneField(
        "emr.Appointment",
        on_delete=models.CASCADE,
        related_name="pix_charge",
    )
    # Asaas identifiers — no raw CPF stored
    asaas_charge_id = models.CharField("Asaas Charge ID", max_length=100, unique=True)
    asaas_customer_id = models.CharField("Asaas Customer ID", max_length=100, blank=True)
    # Payment data
    amount = models.DecimalField("Valor (R$)", max_digits=10, decimal_places=2)
    status = models.CharField(
        "Status", max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    pix_copy_paste = models.TextField("Código PIX copia e cola", blank=True)
    pix_qr_code_base64 = models.TextField("QR Code (base64)", blank=True)
    expires_at = models.DateTimeField("Expira em")
    paid_at = models.DateTimeField("Pago em", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Cobrança PIX"
        verbose_name_plural = "Cobranças PIX"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "expires_at"]),
            models.Index(fields=["asaas_charge_id"]),
        ]

    def __str__(self):
        return f"PIX {self.asaas_charge_id} — R${self.amount} ({self.get_status_display()})"


# ─── Glosas ───────────────────────────────────────────────────────────────────


class Glosa(models.Model):
    """Registro de glosa (negativa/ajuste) de uma guia pela operadora. Per-tenant."""

    guide = models.ForeignKey(TISSGuide, on_delete=models.CASCADE, related_name="glosas")
    guide_item = models.ForeignKey(
        TISSGuideItem, on_delete=models.SET_NULL, null=True, blank=True, related_name="glosas"
    )
    reason_code = models.CharField("Código de motivo", max_length=5, choices=GLOSA_REASON_CODES)
    reason_description = models.TextField("Descrição do motivo")
    value_denied = models.DecimalField("Valor glosado (R$)", max_digits=12, decimal_places=2)
    appeal_status = models.CharField(
        "Status do recurso", max_length=20, choices=APPEAL_STATUS, default="none"
    )
    appeal_text = models.TextField("Texto do recurso", blank=True)
    appeal_filed_at = models.DateTimeField("Recurso enviado em", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Glosa"
        verbose_name_plural = "Glosas"
        ordering = ["-created_at"]

    def __str__(self):
        return (
            f"Glosa {self.get_reason_code_display()} — Guia {self.guide.guide_number} "
            f"R${self.value_denied}"
        )


# ─── Glosa-safety wedge (PR G1): deterministic engine verdict ──────────────────


class GlosaSafetyAlert(models.Model):
    """Verdict do motor determinístico de glosa (wedge PR G1). Per-tenant.

    DEDICATED engine-verdict row — deliberately NOT a reuse of
    ``apps.ai.GlosaPrediction`` (decision A-1). GlosaPrediction is the LLM
    artifact for the flywheel, generated on guide edit and tied to AIUsageLog;
    mixing a deterministic verdict there would conflict lifecycles and risk
    clobbering the LLM ground-truth. This model mirrors ``emr.AISafetyAlert``:
    a ``source`` split (``engine`` today, ``llm`` reserved for later), a
    ``unique_together`` so re-evaluation update_or_create()s in place instead of
    spawning duplicates, and ack fields so an override-with-justification stands.

    Item-level vs guide-level: ``guide_item`` is set for per-line checks
    (duplicate / not_in_table / stale_price) and left NULL for the guide-level
    structural-completeness check.
    """

    class CheckCode(models.TextChoices):
        DUPLICATE = "duplicate", "Procedimento duplicado"
        STALE_PRICE = "stale_price", "Valor diverge da tabela vigente"
        NOT_IN_TABLE = "not_in_table", "Procedimento não tabelado"
        INCOMPLETE = "incomplete", "Dados incompletos"
        # Fail-open / engine-error advisory. A DISTINCT code so the defensive
        # fail-open write can never collide with a real "incomplete" finding on
        # the same (guide, NULL item, source) key.
        ENGINE_ERROR = "engine_error", "Verificação indisponível"
        # Table-unresolved advisory: coverage could not be verified because no
        # active price table could be confidently resolved for the provider.
        # Emitted INSTEAD of blocking every line with not_in_table.
        TABLE_UNRESOLVED = "table_unresolved", "Cobertura não verificada"
        # Clinical-compatibility advisory (G3b): the procedure's ANS metadata
        # (age window / sex / CID whitelist on the public TUSS row) is
        # incompatible with the patient. ALWAYS advise, never blocks — and inert
        # until the TUSS row has ANS-sourced metadata populated.
        CLINICAL_INCOMPAT = "clinical_incompat", "Incompatibilidade clínica"
        # Per-procedure quantity ceiling advisory (G3c): the line quantity exceeds
        # the contract's PriceTableItem.max_per_procedure. ALWAYS advise, never
        # blocks — and inert until a ceiling is configured on the active table.
        QUANTITY_EXCEEDS = "quantity_exceeds", "Quantidade acima do teto"
        # Authorization-required advisory (G3d): the line's active PriceTableItem
        # is flagged requires_authorization=True but NO valid authorization was
        # found (neither guide.authorization_number filled NOR a matching approved,
        # in-window Authorization row). ALWAYS advise, never blocks — and inert
        # until an item is explicitly marked requires_authorization.
        AUTHORIZATION_MISSING = "authorization_missing", "Autorização ausente"

    class Severity(models.TextChoices):
        BLOCK = "block", "Bloqueia"
        ADVISE = "advise", "Avisa"

    class Source(models.TextChoices):
        ENGINE = "engine", "Motor determinístico"
        # Reserved: a future LLM glosa-explainer would write source="llm" here,
        # mirroring the AISafetyAlert engine|llm split. Keeps this row safe to
        # update_or_create() without clobbering an LLM-authored sibling.
        LLM = "llm", "LLM (explicação)"

    class Status(models.TextChoices):
        FLAGGED = "flagged", "Alertado"
        ACKNOWLEDGED = "acknowledged", "Reconhecido"
        RESOLVED = "resolved", "Resolvido"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    guide = models.ForeignKey(
        TISSGuide, on_delete=models.CASCADE, related_name="glosa_safety_alerts"
    )
    guide_item = models.ForeignKey(
        TISSGuideItem,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="glosa_safety_alerts",
        help_text="Set for per-line checks; NULL for guide-level structural checks.",
    )
    check_code = models.CharField(max_length=30, choices=CheckCode.choices)
    severity = models.CharField(max_length=10, choices=Severity.choices)
    source = models.CharField(
        max_length=10,
        choices=Source.choices,
        default=Source.ENGINE,
        help_text="Which checker produced this row: 'engine' verdict or (future) 'llm'.",
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.FLAGGED)
    message = models.TextField("Mensagem (pt-BR)")
    recommendation = models.TextField("Recomendação (pt-BR)", blank=True)
    ans_glosa_code = models.CharField(
        "Código de glosa ANS",
        max_length=5,
        blank=True,
        help_text="Mapped ANS reason code (see GLOSA_REASON_CODES). Blank = unmapped.",
    )
    acknowledged_by = models.ForeignKey(
        "core.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="acknowledged_glosa_alerts",
    )
    override_reason = models.TextField(blank=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    # Flywheel label, backfilled later from the retorno parser at guide_item/TUSS
    # level (decision A-5). Left NULL now — never set by G1.
    was_denied = models.BooleanField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Alerta de Glosa (motor)"
        verbose_name_plural = "Alertas de Glosa (motor)"
        ordering = ["-created_at"]
        # One row per (guide, item, check, source) so re-evaluation
        # update_or_create()s in place and never clobbers an acknowledged
        # override with a duplicate. A plain unique_together (Postgres unique
        # index) treats NULL guide_item as DISTINCT, so guide-level alerts
        # (guide_item IS NULL) would accumulate duplicate rows and later brick
        # update_or_create with MultipleObjectsReturned. nulls_distinct=False
        # (Django 5.0+ / Postgres 15+) makes NULL compare EQUAL so uniqueness
        # holds for guide-level alerts too.
        constraints = [
            models.UniqueConstraint(
                fields=["guide", "guide_item", "check_code", "source"],
                nulls_distinct=False,
                name="uniq_glosa_alert",
            ),
        ]
        indexes = [
            models.Index(fields=["guide", "status", "severity"]),
        ]

    def __str__(self):
        return (
            f"{self.get_severity_display()} — {self.get_check_code_display()} "
            f"(Guia {self.guide_id})"
        )

    def acknowledge(self, user, reason=""):
        self.acknowledged_by = user
        self.override_reason = reason
        self.acknowledged_at = timezone.now()
        self.status = self.Status.ACKNOWLEDGED
        self.save(update_fields=["acknowledged_by", "override_reason", "acknowledged_at", "status"])


class BankStatementImport(models.Model):
    """Uploaded bank statement, retained for audit and idempotent ingestion."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    filename = models.CharField(max_length=255)
    file_sha256 = models.CharField(max_length=64, unique=True)
    format = models.CharField(max_length=8, choices=[("csv", "CSV"), ("ofx", "OFX")])
    status = models.CharField(
        max_length=20,
        choices=[("pending", "Pendente"), ("processed", "Processado"), ("failed", "Falhou")],
        default="pending",
    )
    error = models.TextField(blank=True)
    imported_by = models.ForeignKey(
        "core.User", on_delete=models.SET_NULL, null=True, related_name="bank_statement_imports"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.filename} ({self.created_at:%Y-%m-%d})"


from .inpatient_models import *  # noqa: E402,F401,F403
from .material_models import *  # noqa: E402,F401,F403
from .revenue_models import *  # noqa: E402,F401,F403
from .sus_models import *  # noqa: E402,F401,F403
