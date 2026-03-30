"""
Billing Admin — TISS/TUSS
"""

from django.contrib import admin

from .models import (
    Glosa,
    InsuranceProvider,
    PriceTable,
    PriceTableItem,
    TISSBatch,
    TISSGuide,
    TISSGuideItem,
)


@admin.register(InsuranceProvider)
class InsuranceProviderAdmin(admin.ModelAdmin):
    list_display = ["name", "ans_code", "cnpj", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["name", "ans_code", "cnpj"]


class PriceTableItemInline(admin.TabularInline):
    model = PriceTableItem
    extra = 0
    autocomplete_fields = []
    fields = ["tuss_code", "negotiated_value"]
    raw_id_fields = ["tuss_code"]


@admin.register(PriceTable)
class PriceTableAdmin(admin.ModelAdmin):
    list_display = ["name", "provider", "valid_from", "valid_until", "is_active"]
    list_filter = ["is_active", "provider"]
    search_fields = ["name", "provider__name"]
    inlines = [PriceTableItemInline]


class TISSGuideItemInline(admin.TabularInline):
    model = TISSGuideItem
    extra = 0
    fields = ["tuss_code", "description", "quantity", "unit_value", "total_value"]
    readonly_fields = ["total_value"]
    raw_id_fields = ["tuss_code"]


@admin.register(TISSGuide)
class TISSGuideAdmin(admin.ModelAdmin):
    list_display = [
        "guide_number", "guide_type", "patient", "provider",
        "competency", "total_value", "status", "created_at",
    ]
    list_filter = ["status", "guide_type", "provider", "competency"]
    search_fields = ["guide_number", "patient__full_name", "insured_card_number"]
    readonly_fields = ["guide_number", "xml_content", "created_at", "updated_at"]
    inlines = [TISSGuideItemInline]
    ordering = ["-created_at"]


class GlosaInline(admin.TabularInline):
    model = Glosa
    extra = 0
    fields = ["reason_code", "reason_description", "value_denied", "appeal_status"]
    readonly_fields = ["created_at"]


@admin.register(TISSBatch)
class TISSBatchAdmin(admin.ModelAdmin):
    list_display = [
        "batch_number", "provider", "status", "total_value", "created_at", "closed_at",
    ]
    list_filter = ["status", "provider"]
    search_fields = ["batch_number", "provider__name"]
    readonly_fields = ["batch_number", "created_at", "closed_at"]
    filter_horizontal = ["guides"]
    ordering = ["-created_at"]


@admin.register(Glosa)
class GlosaAdmin(admin.ModelAdmin):
    list_display = [
        "guide", "reason_code", "get_reason_code_display", "value_denied",
        "appeal_status", "created_at",
    ]
    list_filter = ["reason_code", "appeal_status"]
    search_fields = ["guide__guide_number", "reason_description"]
    readonly_fields = ["created_at", "appeal_filed_at"]
    ordering = ["-created_at"]
