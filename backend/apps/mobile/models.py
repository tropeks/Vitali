"""
Phase 3 Mobile backend primitive.

Two models:

- `MobileDevice` — one row per (user, device_id). Carries the platform's
  push token (FCM/APNS/web) so the dispatcher can address pushes to a
  specific install. `device_id` is the stable install UUID the mobile
  client mints on first launch; the same physical device installed
  twice gets two rows.

- `PushDelivery` — append-only audit log of every push that the platform
  attempted to send. Records target, payload, transport result, and
  any provider error. Even when the FCM/APNS adapter is not configured
  (no credentials), the delivery is recorded with `status=no_provider`
  so operations have full visibility.

The actual React-Native client and the FCM/APNS adapter wiring are
follow-up deploy-time work. The contract here is the swap-in point:
once a `FirebasePushAdapter` lands in `apps.mobile.services.adapters`,
plug it into `MobilePushService.set_adapter()` and the same REST surface
starts delivering real pushes.
"""

import uuid

from django.db import models

from apps.core.models import User


class MobileDevice(models.Model):
    PLATFORM_IOS = "ios"
    PLATFORM_ANDROID = "android"
    PLATFORM_WEB = "web"

    PLATFORM_CHOICES = [
        (PLATFORM_IOS, "iOS"),
        (PLATFORM_ANDROID, "Android"),
        (PLATFORM_WEB, "Web (browser push)"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="mobile_devices")
    platform = models.CharField(max_length=10, choices=PLATFORM_CHOICES)
    # The install-stable UUID the mobile client mints on first launch.
    # Two reinstalls of the app on the same hardware produce two rows.
    device_id = models.CharField(max_length=128, db_index=True)
    push_token = models.CharField(max_length=512)
    app_version = models.CharField(max_length=32, blank=True)
    os_version = models.CharField(max_length=32, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    enrolled_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-enrolled_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "device_id"], name="mobile_user_device_unique"),
        ]
        indexes = [
            models.Index(fields=["user", "is_active"], name="mobile_user_active_idx"),
            models.Index(fields=["platform", "is_active"], name="mobile_plat_active_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.platform} device for {self.user_id} ({self.device_id[:8]})"


class PushDelivery(models.Model):
    STATUS_SENT = "sent"
    STATUS_FAILED = "failed"
    STATUS_NO_PROVIDER = "no_provider"

    STATUS_CHOICES = [
        (STATUS_SENT, "Enviado"),
        (STATUS_FAILED, "Falhou"),
        (STATUS_NO_PROVIDER, "Sem provider"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    device = models.ForeignKey(
        MobileDevice, on_delete=models.CASCADE, related_name="push_deliveries"
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="push_deliveries")
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    data = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_NO_PROVIDER, db_index=True
    )
    provider_message_id = models.CharField(max_length=200, blank=True)
    provider_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "-created_at"], name="push_user_idx"),
            models.Index(fields=["status", "-created_at"], name="push_status_idx"),
        ]

    def __str__(self) -> str:
        return f"Push '{self.title}' → {self.device_id} ({self.status})"
