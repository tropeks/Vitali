from django.contrib import admin

from .models import TelemedicineSession


@admin.register(TelemedicineSession)
class TelemedicineSessionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "patient",
        "professional",
        "status",
        "scheduled_for",
        "duration_seconds",
    )
    list_filter = ("status",)
    search_fields = ("room_uid", "patient__full_name")
    ordering = ("-scheduled_for",)
    readonly_fields = (
        "id",
        "room_uid",
        "started_at",
        "ended_at",
        "duration_seconds",
        "created_at",
        "created_by",
    )
