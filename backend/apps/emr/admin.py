from django.contrib import admin

from .models import Allergy, MedicalHistory, Patient, Professional


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
    search_fields = ["full_name", "medical_record_number", "whatsapp"]
    readonly_fields = ["id", "medical_record_number", "created_at", "updated_at"]
    inlines = [AllergyInline, MedicalHistoryInline]


@admin.register(Professional)
class ProfessionalAdmin(admin.ModelAdmin):
    list_display = ["__str__", "council_type", "council_state", "specialty", "is_active"]
    list_filter = ["council_type", "council_state", "is_active"]
    search_fields = ["user__full_name", "council_number"]
