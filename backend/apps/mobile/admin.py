from django.contrib import admin

from .models import MobileDevice, PushDelivery


@admin.register(MobileDevice)
class MobileDeviceAdmin(admin.ModelAdmin):
    list_display = ("user", "platform", "device_id", "is_active", "enrolled_at")
    list_filter = ("platform", "is_active")
    search_fields = ("device_id", "push_token", "user__email")
    readonly_fields = ("id", "enrolled_at", "last_seen_at")


@admin.register(PushDelivery)
class PushDeliveryAdmin(admin.ModelAdmin):
    list_display = ("title", "user", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("title", "user__email", "provider_message_id")
    readonly_fields = (
        "id",
        "device",
        "user",
        "title",
        "body",
        "data",
        "status",
        "provider_message_id",
        "provider_error",
        "created_at",
    )

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False
