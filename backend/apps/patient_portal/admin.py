from django.contrib import admin

from .models import PatientPortalAccess
from .services import deliver_portal_invite


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

    def save_model(self, request, obj, form, change):
        is_new = not change
        if is_new and not obj.created_by_id:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
        # On creation, deliver the activation link (WhatsApp → email fallback).
        if is_new:
            deliver_portal_invite(obj)
