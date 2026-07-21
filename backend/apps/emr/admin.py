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
    list_display = [
        "code",
        "name",
        "category",
        "result_type",
        "specimen_type",
        "method",
        "active",
        "updated_at",
    ]
    list_filter = ["active", "category", "result_type", "specimen_type"]
    search_fields = ["code", "name", "loinc_code", "method"]
    readonly_fields = ["id", "created_at", "updated_at"]


class LabOrderItemInline(admin.TabularInline):
    model = LabOrderItem
    extra = 0
    fields = [
        "test",
        "test_name",
        "category",
        "result_type",
        "specimen_type",
        "method",
        "loinc_code",
        "unit",
        "reference_range",
        "components",
        "reference_ranges",
        "abnormal_flag",
        "resulted_at",
        "validated_at",
        "validated_by",
    ]
    readonly_fields = [
        "test_name",
        "category",
        "result_type",
        "specimen_type",
        "method",
        "loinc_code",
        "unit",
        "reference_range",
        "components",
        "reference_ranges",
        "resulted_at",
        "validated_at",
    ]


@admin.register(LabOrder)
class LabOrderAdmin(admin.ModelAdmin):
    list_display = [
        "accession_number",
        "patient",
        "status",
        "requested_by",
        "collected_by",
        "requested_at",
        "completed_at",
    ]
    list_filter = ["status", "requested_at", "completed_at"]
    search_fields = ["accession_number", "patient__medical_record_number"]
    raw_id_fields = ["patient", "encounter", "requested_by", "collected_by"]
    readonly_fields = ["id", "accession_number", "requested_at", "collected_at", "completed_at"]
    inlines = [LabOrderItemInline]


@admin.register(LabOrderItem)
class LabOrderItemAdmin(admin.ModelAdmin):
    list_display = [
        "test_name",
        "category",
        "result_type",
        "order",
        "abnormal_flag",
        "resulted_at",
        "validated_at",
        "validated_by",
    ]
    list_filter = ["category", "result_type", "abnormal_flag", "resulted_at", "validated_at"]
    search_fields = [
        "test_name",
        "loinc_code",
        "order__accession_number",
        "order__patient__medical_record_number",
    ]
    raw_id_fields = ["order", "test", "validated_by"]
    readonly_fields = [
        "id",
        "test_name",
        "category",
        "result_type",
        "specimen_type",
        "method",
        "loinc_code",
        "unit",
        "reference_range",
        "components",
        "reference_ranges",
        "resulted_at",
        "validated_at",
    ]
