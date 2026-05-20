from django.contrib import admin

from .models import PatientPortalAccess


@admin.register(PatientPortalAccess)
class PatientPortalAccessAdmin(admin.ModelAdmin):
    list_display = ("patient", "user", "status", "invited_at", "activated_at", "revoked_at")
    list_filter = ("status",)
    search_fields = ("patient__full_name", "user__email", "invite_token")
    readonly_fields = (
        "id",
        "invite_token",
        "invited_at",
        "activated_at",
        "revoked_at",
        "last_seen_at",
        "created_by",
    )
    ordering = ("-invited_at",)
