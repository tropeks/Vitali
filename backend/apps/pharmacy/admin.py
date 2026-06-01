from django.contrib import admin

from .models import (
    Dispensation,
    DispensationLot,
    DoseRule,
    Drug,
    Material,
    MedicationFormulary,
    StockItem,
    StockMovement,
)


@admin.register(Drug)
class DrugAdmin(admin.ModelAdmin):
    list_display = ["name", "generic_name", "controlled_class", "dosage_form", "is_active"]
    list_filter = ["controlled_class", "is_active", "dosage_form"]
    search_fields = ["name", "generic_name", "anvisa_code", "barcode"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(Material)
class MaterialAdmin(admin.ModelAdmin):
    list_display = ["name", "category", "unit_of_measure", "is_active"]
    list_filter = ["category", "is_active"]
    search_fields = ["name", "barcode"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(StockItem)
class StockItemAdmin(admin.ModelAdmin):
    list_display = ["__str__", "lot_number", "expiry_date", "quantity", "min_stock", "location"]
    list_filter = ["drug", "material"]
    search_fields = ["lot_number", "drug__name", "material__name"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ["stock_item", "movement_type", "quantity", "performed_by", "created_at"]
    list_filter = ["movement_type"]
    readonly_fields = ["id", "created_at"]

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class DispensationLotInline(admin.TabularInline):
    model = DispensationLot
    extra = 0
    readonly_fields = ["dispensation", "stock_item", "quantity"]

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Dispensation)
class DispensationAdmin(admin.ModelAdmin):
    list_display = ["id", "patient", "dispensed_by", "dispensed_at"]
    readonly_fields = ["id", "dispensed_at"]
    inlines = [DispensationLotInline]

    def has_change_permission(self, request, obj=None):
        return False


class DoseRuleInline(admin.TabularInline):
    model = DoseRule
    extra = 0
    fields = [
        "basis",
        "age_min_years",
        "age_max_years",
        "weight_min_kg",
        "weight_max_kg",
        "dose_unit",
        "min_per_dose",
        "max_per_dose",
        "max_per_day",
        "route",
        "active",
    ]


@admin.register(MedicationFormulary)
class MedicationFormularyAdmin(admin.ModelAdmin):
    list_display = [
        "drug",
        "strength_value",
        "strength_unit",
        "route",
        "is_injectable",
        "is_high_alert",
        "active",
    ]
    list_filter = ["route", "is_injectable", "is_high_alert", "active"]
    search_fields = ["drug__name", "drug__generic_name"]
    readonly_fields = ["id", "created_at", "updated_at"]
    autocomplete_fields = ["drug"]
    inlines = [DoseRuleInline]


@admin.register(DoseRule)
class DoseRuleAdmin(admin.ModelAdmin):
    list_display = [
        "formulary",
        "basis",
        "age_min_years",
        "age_max_years",
        "min_per_dose",
        "max_per_dose",
        "max_per_day",
        "dose_unit",
        "active",
    ]
    list_filter = ["basis", "active"]
    search_fields = ["formulary__drug__name", "notes"]
    readonly_fields = ["id", "created_at", "updated_at"]
