from django.contrib import admin

from .models import Allergy, EscalationConfig, MedicalHistory, Patient, Professional


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
