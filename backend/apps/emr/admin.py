from django.contrib import admin

from .models import (
    Allergy,
    EscalationConfig,
    LabOrder,
    LabOrderItem,
    LabTest,
    MedicalHistory,
    Patient,
    Professional,
)


@admin.register(EscalationConfig)
class EscalationConfigAdmin(admin.ModelAdmin):
    list_display = ["__str__", "is_active", "min_severity", "created_at"]
    list_filter = ["is_active", "min_severity"]
    readonly_fields = ["id", "created_at", "updated_at"]


class AllergyInline(admin.TabularInline):
    model = Allergy
    extra = 0
    readonly_fields = ["created_at"]


class MedicalHistoryInline(admin.TabularInline):
    model = MedicalHistory
    extra = 0
    readonly_fields = ["created_at"]


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = [
        "medical_record_number",
        "full_name",
        "birth_date",
        "gender",
        "phone",
        "is_active",
    ]
    list_filter = ["gender", "blood_type", "is_active"]
    # full_name is encrypted at rest (LGPD) and cannot be matched by the admin's
    # SQL search; only the plaintext routing keys remain searchable here.
    search_fields = ["medical_record_number", "whatsapp"]
    readonly_fields = ["id", "medical_record_number", "created_at", "updated_at"]
    inlines = [AllergyInline, MedicalHistoryInline]


@admin.register(Professional)
class ProfessionalAdmin(admin.ModelAdmin):
    list_display = ["__str__", "council_type", "council_state", "specialty", "is_active"]
    list_filter = ["council_type", "council_state", "is_active"]
    search_fields = ["user__full_name", "council_number"]


@admin.register(LabTest)
class LabTestAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "specimen_type", "unit", "active", "updated_at"]
    list_filter = ["active", "specimen_type"]
    search_fields = ["code", "name"]
    readonly_fields = ["id", "created_at", "updated_at"]


class LabOrderItemInline(admin.TabularInline):
    model = LabOrderItem
    extra = 0
    fields = [
        "test",
        "test_name",
        "unit",
        "reference_range",
        "abnormal_flag",
        "resulted_at",
        "validated_at",
        "validated_by",
    ]
    readonly_fields = ["test_name", "unit", "reference_range", "resulted_at", "validated_at"]


@admin.register(LabOrder)
class LabOrderAdmin(admin.ModelAdmin):
    list_display = ["id", "patient", "status", "requested_by", "requested_at", "completed_at"]
    list_filter = ["status", "requested_at", "completed_at"]
    search_fields = ["patient__medical_record_number"]
    raw_id_fields = ["patient", "encounter", "requested_by"]
    readonly_fields = ["id", "requested_at", "collected_at", "completed_at"]
    inlines = [LabOrderItemInline]


@admin.register(LabOrderItem)
class LabOrderItemAdmin(admin.ModelAdmin):
    list_display = [
        "test_name",
        "order",
        "abnormal_flag",
        "resulted_at",
        "validated_at",
        "validated_by",
    ]
    list_filter = ["abnormal_flag", "resulted_at", "validated_at"]
    search_fields = ["test_name", "order__patient__medical_record_number"]
    raw_id_fields = ["order", "test", "validated_by"]
    readonly_fields = ["id", "test_name", "unit", "reference_range", "resulted_at", "validated_at"]
