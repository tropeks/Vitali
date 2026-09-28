from django.contrib import admin, messages

from .models import PatientPortalAccess
from .services import build_activation_url, deliver_portal_invite


@admin.register(PatientPortalAccess)
class PatientPortalAccessAdmin(admin.ModelAdmin):
    list_display = ("patient", "user", "status", "invited_at", "activated_at", "revoked_at")
    list_filter = ("status",)
    search_fields = ("patient__full_name", "user__email")
    readonly_fields = (
        "id",
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
        # The database keeps only the token's hash (order 033), so if no channel
        # delivered, this message is the one time the link can be handed over by
        # hand — the admin twin of the API's 201.
        if is_new and not deliver_portal_invite(obj):
            self.message_user(
                request,
                "Convite NÃO entregue (sem WhatsApp com opt-in nem e-mail). Entregue este "
                f"link ao paciente agora; ele não será mostrado de novo: {build_activation_url(obj)}",
                level=messages.WARNING,
            )
