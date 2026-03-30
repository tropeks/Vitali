"""
Billing Serializers — TISS/TUSS
"""

from django.contrib.postgres.search import SearchQuery, SearchRank
from rest_framework import serializers

from apps.core.models import TUSSCode

from .models import (
    Glosa,
    InsuranceProvider,
    PriceTable,
    PriceTableItem,
    TISSBatch,
    TISSGuide,
    TISSGuideItem,
)


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
            "id", "provider", "provider_name", "name",
            "valid_from", "valid_until", "is_active", "items", "created_at",
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
    item_count = serializers.IntegerField(read_only=True)  # populated by annotate(item_count=Count("items"))

    class Meta:
        model = PriceTable
        fields = [
            "id", "provider", "provider_name", "name",
            "valid_from", "valid_until", "is_active", "item_count", "created_at",
        ]
        read_only_fields = fields


# ─── Guides ───────────────────────────────────────────────────────────────────

class TISSGuideItemSerializer(serializers.ModelSerializer):
    tuss_code_display = serializers.SerializerMethodField()

    class Meta:
        model = TISSGuideItem
        fields = [
            "id", "tuss_code", "tuss_code_display", "description",
            "quantity", "unit_value", "total_value",
        ]
        read_only_fields = ["id", "total_value"]

    def get_tuss_code_display(self, obj):
        return f"{obj.tuss_code.code} — {obj.tuss_code.description[:60]}"


class TISSGuideSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    guide_type_display = serializers.CharField(source="get_guide_type_display", read_only=True)
    patient_name = serializers.CharField(source="patient.full_name", read_only=True)
    provider_name = serializers.CharField(source="provider.name", read_only=True)
    items = TISSGuideItemSerializer(many=True, read_only=True)

    class Meta:
        model = TISSGuide
        fields = [
            "id", "guide_number", "guide_type", "guide_type_display",
            "encounter", "patient", "patient_name",
            "provider", "provider_name", "price_table",
            "status", "status_display",
            "insured_card_number", "authorization_number",
            "competency", "cid10_codes",
            "total_value", "xml_content",
            "items",
            "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "guide_number", "status", "xml_content", "total_value",
            "created_at", "updated_at",
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
            "id", "guide_number", "guide_type", "guide_type_display",
            "patient", "patient_name", "provider", "provider_name",
            "competency", "total_value", "status", "status_display",
            "created_at", "updated_at",
        ]
        read_only_fields = fields


# ─── Batches ──────────────────────────────────────────────────────────────────

class TISSBatchSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    provider_name = serializers.CharField(source="provider.name", read_only=True)
    guide_count = serializers.SerializerMethodField()
    guide_ids = serializers.PrimaryKeyRelatedField(
        source="guides", many=True, queryset=TISSGuide.objects.all(), write_only=True,
        required=False,
    )

    class Meta:
        model = TISSBatch
        fields = [
            "id", "batch_number", "provider", "provider_name",
            "status", "status_display",
            "guides", "guide_ids", "guide_count",
            "total_value", "xml_file",
            "created_at", "closed_at",
        ]
        read_only_fields = [
            "id", "batch_number", "total_value", "xml_file",
            "created_at", "closed_at",
        ]

    def get_guide_count(self, obj):
        return obj.guides.count()

    def validate_guide_ids(self, guides):
        for guide in guides:
            # build a temporary batch to run double-submit check (provider not needed)
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
            "id", "guide", "guide_number", "guide_item",
            "reason_code", "reason_display",
            "reason_description", "value_denied",
            "appeal_status", "appeal_status_display",
            "appeal_text", "appeal_filed_at",
            "created_at",
        ]
        read_only_fields = ["id", "created_at", "appeal_filed_at"]
