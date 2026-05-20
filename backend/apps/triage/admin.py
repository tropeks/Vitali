from django.contrib import admin

from .models import TriageSession


@admin.register(TriageSession)
class TriageSessionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "patient",
        "contact_phone",
        "status",
        "urgency",
        "red_flags_positive",
        "started_at",
    )
    list_filter = ("status", "urgency")
    search_fields = ("contact_phone", "patient__full_name", "chief_complaint")
    ordering = ("-started_at",)
    readonly_fields = (
        "id",
        "started_at",
        "evaluated_at",
        "escalated_at",
        "closed_at",
        "matched_keywords",
        "rationale",
        "created_by",
    )
