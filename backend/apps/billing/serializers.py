"""
Billing Serializers — TISS/TUSS
"""

from rest_framework import serializers

from apps.core.models import TUSSCode

from .inpatient_models import InpatientFee
from .models import (
    AccountingCategory,
    AccountingEntry,
    AccountsReceivable,
    BankTransaction,
    CashFlowEntry,
    Glosa,
    InsuranceProvider,
    Payable,
    PriceTable,
    PriceTableItem,
    ProfessionalSettlement,
    TISSBatch,
    TISSGuide,
    TISSGuideItem,
)


class ProfessionalSettlementSerializer(serializers.ModelSerializer):
    professional_name = serializers.CharField(source="professional.user.full_name", read_only=True)

    class Meta:
        model = ProfessionalSettlement
        fields = [
            "id",
            "professional",
            "professional_name",
            "competency",
            "gross_amount",
            "deductions",
            "net_amount",
            "status",
            "calculated_at",
            "paid_at",
        ]
        # ``status`` is read-only so a plain PATCH cannot jump draft→approved→paid
        # without going through approve()/pay() (which lock, recheck and audit).
        read_only_fields = [
            "id",
            "gross_amount",
            "net_amount",
            "status",
            "calculated_at",
            "paid_at",
        ]


# ─── TUSS ─────────────────────────────────────────────────────────────────────


class TUSSCodeSerializer(serializers.ModelSerializer):
    class Meta:
        model = TUSSCode
        fields = ["id", "code", "description", "group", "subgroup", "version", "active"]
        read_only_fields = fields


# ─── Providers / Price Tables ─────────────────────────────────────────────────


class InsuranceProviderSerializer(serializers.ModelSerializer):
    class Meta:
        model = InsuranceProvider
        fields = ["id", "name", "ans_code", "cnpj", "is_active", "created_at"]
        read_only_fields = ["id", "created_at"]


class PriceTableItemSerializer(serializers.ModelSerializer):
    tuss_code_display = serializers.SerializerMethodField()

    class Meta:
        model = PriceTableItem
        fields = ["id", "tuss_code", "tuss_code_display", "negotiated_value"]
        read_only_fields = ["id"]

    def get_tuss_code_display(self, obj):
        return f"{obj.tuss_code.code} — {obj.tuss_code.description[:60]}"


class PriceTableSerializer(serializers.ModelSerializer):
    provider_name = serializers.CharField(source="provider.name", read_only=True)
    items = PriceTableItemSerializer(many=True, read_only=True)

    class Meta:
        model = PriceTable
        fields = [
            "id",
            "provider",
            "provider_name",
            "name",
            "valid_from",
            "valid_until",
            "is_active",
            "items",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def validate(self, attrs):
        instance = self.instance
        obj = PriceTable(**attrs)
        if instance:
            obj.pk = instance.pk
        obj.clean()
        return attrs


class PriceTableListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for list view — no nested items."""

    provider_name = serializers.CharField(source="provider.name", read_only=True)
    item_count = serializers.IntegerField(
        read_only=True
    )  # populated by annotate(item_count=Count("items"))

    class Meta:
        model = PriceTable
        fields = [
            "id",
            "provider",
            "provider_name",
            "name",
            "valid_from",
            "valid_until",
            "is_active",
            "item_count",
            "created_at",
        ]
        read_only_fields = fields


# ─── Guides ───────────────────────────────────────────────────────────────────


class TISSGuideItemSerializer(serializers.ModelSerializer):
    tuss_code_display = serializers.SerializerMethodField()

    class Meta:
        model = TISSGuideItem
        fields = [
            "id",
            "tuss_code",
            "tuss_code_display",
            "description",
            "quantity",
            "unit_value",
            "total_value",
        ]
        read_only_fields = ["id", "total_value"]

    def get_tuss_code_display(self, obj):
        return f"{obj.tuss_code.code} — {obj.tuss_code.description[:60]}"


class TISSGuideSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    guide_type_display = serializers.CharField(source="get_guide_type_display", read_only=True)
    # Rótulo legível do dm_tipoFaturamento DESTA guia — mesmo par valor/`_display`
    # que `status`/`guide_type` já expõem. É só o valor gravado; a LISTA de
    # códigos disponíveis não sai daqui, sai de
    # GET /api/v1/billing/guides/tipo-faturamento-options/
    # (TISSGuideViewSet.tipo_faturamento_options).
    #
    # POR QUE O ENDPOINT, E NÃO UM CAMPO DE LISTA NO SERIALIZER: são duas telas
    # que precisam das opções e uma delas não tem guia nenhuma. A tela de guia
    # nova (frontend .../billing/guides/new) monta o select ANTES de existir
    # objeto para serializar — um campo em TISSGuideSerializer é estruturalmente
    # incapaz de atendê-la. O endpoint atende as duas, e não repete a mesma lista
    # estática de quatro itens em toda resposta de guia (inclusive nas listagens).
    #
    # Vale notar o que a UI vai mostrar: os rótulos de TISSGuide.TipoFaturamento
    # são "Código N (rótulo a confirmar no manual ANS)" enquanto o manual de
    # tabelas de domínio não estiver no repo — a pendência aparece na tela de
    # propósito, para ninguém escolher achando que sabe o que escolheu.
    tipo_faturamento_display = serializers.CharField(
        source="get_tipo_faturamento_display", read_only=True
    )
    patient_name = serializers.CharField(source="patient.full_name", read_only=True)
    provider_name = serializers.CharField(source="provider.name", read_only=True)
    items = TISSGuideItemSerializer(many=True, read_only=True)
    # Write-only: UUIDs of GlosaPrediction rows shown before guide submission.
    # The view links them to the newly created guide (see billing/views.py perform_create).
    glosa_prediction_ids = serializers.ListField(
        child=serializers.UUIDField(),
        write_only=True,
        required=False,
        default=list,
    )

    class Meta:
        model = TISSGuide
        fields = [
            "id",
            "guide_number",
            "guide_type",
            "guide_type_display",
            "encounter",
            "patient",
            "patient_name",
            "provider",
            "provider_name",
            "price_table",
            "status",
            "status_display",
            "insured_card_number",
            "authorization_number",
            "authorization_date",
            "requesting_professional",
            "tipo_atendimento",
            "regime_atendimento",
            "tipo_faturamento",
            "tipo_faturamento_display",
            "competency",
            "cid10_codes",
            "total_value",
            "xml_content",
            "items",
            "glosa_prediction_ids",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "guide_number",
            "status",
            "xml_content",
            "total_value",
            "created_at",
            "updated_at",
        ]


class TISSGuideListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for list view."""

    status_display = serializers.CharField(source="get_status_display", read_only=True)
    guide_type_display = serializers.CharField(source="get_guide_type_display", read_only=True)
    patient_name = serializers.CharField(source="patient.full_name", read_only=True)
    provider_name = serializers.CharField(source="provider.name", read_only=True)

    class Meta:
        model = TISSGuide
        fields = [
            "id",
            "guide_number",
            "guide_type",
            "guide_type_display",
            "patient",
            "patient_name",
            "provider",
            "provider_name",
            "competency",
            "total_value",
            "status",
            "status_display",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


# ─── Batches ──────────────────────────────────────────────────────────────────


class TISSBatchSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    provider_name = serializers.CharField(source="provider.name", read_only=True)
    guide_count = serializers.SerializerMethodField()
    guide_ids = serializers.PrimaryKeyRelatedField(
        source="guides",
        many=True,
        queryset=TISSGuide.objects.all(),
        write_only=True,
        required=False,
    )

    class Meta:
        model = TISSBatch
        fields = [
            "id",
            "batch_number",
            "provider",
            "provider_name",
            "status",
            "status_display",
            "guides",
            "guide_ids",
            "guide_count",
            "total_value",
            "xml_file",
            "created_at",
            "closed_at",
        ]
        read_only_fields = [
            "id",
            "batch_number",
            "status",
            "total_value",
            "xml_file",
            "created_at",
            "closed_at",
        ]

    def get_guide_count(self, obj):
        return obj.guides.count()

    def validate_guide_ids(self, guides):
        provider_id = (
            self.instance.provider_id
            if self.instance
            else (self.initial_data.get("provider") or None)
        )
        for guide in guides:
            # Provider homogeneity: all guides must belong to the batch's provider
            if provider_id and guide.provider_id != int(provider_id):
                raise serializers.ValidationError(
                    f"Guia {guide.guide_number} pertence a outra operadora "
                    f"({guide.provider}). Lotes só podem conter guias da mesma operadora."
                )
            # Double-submit protection
            batch = TISSBatch()
            if self.instance:
                batch.pk = self.instance.pk
            batch.check_guide_not_double_submitted(guide)
        return guides


# ─── Glosas ───────────────────────────────────────────────────────────────────


class GlosaSerializer(serializers.ModelSerializer):
    reason_display = serializers.CharField(source="get_reason_code_display", read_only=True)
    appeal_status_display = serializers.CharField(
        source="get_appeal_status_display", read_only=True
    )
    guide_number = serializers.CharField(source="guide.guide_number", read_only=True)

    class Meta:
        model = Glosa
        fields = [
            "id",
            "guide",
            "guide_number",
            "guide_item",
            "reason_code",
            "reason_display",
            "reason_description",
            "value_denied",
            "appeal_status",
            "appeal_status_display",
            "appeal_text",
            "appeal_filed_at",
            "created_at",
        ]
        read_only_fields = ["id", "created_at", "appeal_filed_at"]


class AccountsReceivableSerializer(serializers.ModelSerializer):
    guide_number = serializers.CharField(source="guide.guide_number", read_only=True)
    patient_name = serializers.CharField(source="guide.patient.full_name", read_only=True)
    provider_name = serializers.CharField(source="guide.provider.name", read_only=True)

    class Meta:
        model = AccountsReceivable
        fields = [
            "id",
            "guide",
            "guide_number",
            "patient_name",
            "provider_name",
            "amount",
            "due_date",
            "received_at",
            "status",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "received_at"]


class BankTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = BankTransaction
        fields = "__all__"
        read_only_fields = [
            "id",
            "status",
            "receivable",
            "confidence",
            "matched_at",
            "matched_by",
            "created_at",
        ]


class PayableSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payable
        fields = "__all__"
        # ``status`` is read-only so a payable is always created as 'planned' and
        # can only reach 'approved'/'paid' through approve()/pay() (maker-checker).
        read_only_fields = ["id", "created_by", "status", "created_at", "updated_at", "paid_at"]


class CashFlowEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = CashFlowEntry
        fields = "__all__"
        # ``status``/``realized_at`` are driven by realize() (maker-checker);
        # ``created_by`` is stamped server-side from the request user.
        read_only_fields = ["id", "created_at", "realized_at", "status", "created_by"]


class AccountingCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = AccountingCategory
        fields = "__all__"
        read_only_fields = ["id"]


class AccountingEntrySerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)

    class Meta:
        model = AccountingEntry
        fields = "__all__"
        read_only_fields = ["id", "created_by", "created_at"]

    def validate(self, attrs):
        category = attrs.get("category") or getattr(self.instance, "category", None)
        kind = attrs.get("kind") or getattr(self.instance, "kind", None)
        if category and kind and category.kind != kind:
            raise serializers.ValidationError(
                {"kind": "A categoria não é compatível com o tipo do lançamento."}
            )
        return attrs


# ─── Internação: taxas e gases medicinais (Onda2 2.1/2.2) ─────────────────────


class InpatientFeeSerializer(serializers.ModelSerializer):
    """Taxa/gás medicinal lançado numa internação (B6, exposto na Onda 2).

    A criação NÃO passa por ``ModelSerializer.save()``: é
    ``InpatientFeeViewSet.perform_create`` que delega a
    ``services.inpatient_billing.record_inpatient_fee``, onde moram a validação
    de tabela TUSS/quantidade/internação ativa e a idempotência (mesmo TUSS +
    dia + quantidade + unidade não duplica). Este serializer só valida forma e
    faz a leitura de ida e volta.
    """

    tuss_code_display = serializers.SerializerMethodField()
    created_by_name = serializers.CharField(
        source="created_by.full_name", read_only=True, default=""
    )
    # Opcional na entrada: o serviço default para "hoje" quando omitido.
    service_date = serializers.DateField(required=False)

    class Meta:
        model = InpatientFee
        fields = [
            "id",
            "admission",
            "service_date",
            "tuss_code",
            "tuss_code_display",
            "description",
            "quantity",
            "unit",
            "category",
            "notes",
            "created_by",
            "created_by_name",
            "created_at",
            "updated_at",
        ]
        # description = snapshot do texto TUSS no momento do lançamento;
        # created_by = ator autenticado. Nenhum dos dois é aceito do cliente.
        read_only_fields = ["id", "description", "created_by", "created_at", "updated_at"]

    def get_tuss_code_display(self, obj):
        return f"{obj.tuss_code.code} — {obj.tuss_code.description[:60]}"
