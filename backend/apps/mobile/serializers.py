"""Serializers for the mobile module."""

from __future__ import annotations

from rest_framework import serializers

from .models import MobileDevice, PushDelivery


class MobileDeviceSerializer(serializers.ModelSerializer):
    platform_display = serializers.CharField(source="get_platform_display", read_only=True)

    class Meta:
        model = MobileDevice
        fields = [
            "id",
            "user",
            "platform",
            "platform_display",
            "device_id",
            "push_token",
            "app_version",
            "os_version",
            "is_active",
            "enrolled_at",
            "last_seen_at",
        ]
        read_only_fields = ["id", "user", "platform_display", "enrolled_at", "last_seen_at"]


class MobileDeviceRegisterSerializer(serializers.Serializer):
    platform = serializers.ChoiceField(choices=MobileDevice.PLATFORM_CHOICES)
    device_id = serializers.CharField(max_length=128)
    push_token = serializers.CharField(max_length=512)
    app_version = serializers.CharField(max_length=32, required=False, allow_blank=True, default="")
    os_version = serializers.CharField(max_length=32, required=False, allow_blank=True, default="")


class PushDeliverySerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = PushDelivery
        fields = [
            "id",
            "device",
            "user",
            "title",
            "body",
            "data",
            "status",
            "status_display",
            "provider_message_id",
            "provider_error",
            "created_at",
        ]
        read_only_fields = fields


class PushSendSerializer(serializers.Serializer):
    user = serializers.UUIDField()
    title = serializers.CharField(max_length=200)
    body = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")
    # DRF's `Serializer.data` is a property — naming a field `data` here
    # produces a benign mypy assignment warning; explicit ignore preserves
    # the API contract (`POST {"user", "title", "data": {...}}`).
    data = serializers.DictField(required=False, default=dict)  # type: ignore[assignment]
