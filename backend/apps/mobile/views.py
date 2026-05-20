"""REST views for the mobile primitive."""

from __future__ import annotations

from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.models import User
from apps.core.permissions import HasPermission, ModuleRequiredPermission

from .models import MobileDevice, PushDelivery
from .serializers import (
    MobileDeviceRegisterSerializer,
    MobileDeviceSerializer,
    PushDeliverySerializer,
    PushSendSerializer,
)
from .services.push import MobilePushService

_MOBILE_MODULE = ModuleRequiredPermission("mobile")


# ─── Self surface ────────────────────────────────────────────────────────────


class MyDevicesView(APIView):
    """GET / POST `/api/v1/mobile/devices/me/` — current user's devices."""

    def get_permissions(self):
        return [IsAuthenticated(), _MOBILE_MODULE]

    def get(self, request):
        qs = MobileDevice.objects.filter(user=request.user).order_by("-enrolled_at")
        return Response(MobileDeviceSerializer(qs, many=True).data)

    def post(self, request):
        serializer = MobileDeviceRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        # Idempotent upsert: same (user, device_id) updates the existing row.
        device, _created = MobileDevice.objects.update_or_create(
            user=request.user,
            device_id=data["device_id"],
            defaults={
                "platform": data["platform"],
                "push_token": data["push_token"],
                "app_version": data.get("app_version", ""),
                "os_version": data.get("os_version", ""),
                "is_active": True,
                "last_seen_at": timezone.now(),
            },
        )
        return Response(MobileDeviceSerializer(device).data, status=status.HTTP_201_CREATED)


class MyDeviceDetailView(APIView):
    """DELETE `/api/v1/mobile/devices/me/{device_id}/` — unregister."""

    def get_permissions(self):
        return [IsAuthenticated(), _MOBILE_MODULE]

    def delete(self, request, device_pk):
        try:
            device = MobileDevice.objects.get(pk=device_pk, user=request.user)
        except (MobileDevice.DoesNotExist, ValueError):
            return Response({"detail": "Device not found."}, status=status.HTTP_404_NOT_FOUND)
        device.is_active = False
        device.save(update_fields=["is_active"])
        return Response(status=status.HTTP_204_NO_CONTENT)


# ─── Admin surface ───────────────────────────────────────────────────────────


class AdminDeviceListView(APIView):
    """GET `/api/v1/mobile/devices/` — admin lists all devices."""

    def get_permissions(self):
        return [IsAuthenticated(), _MOBILE_MODULE, HasPermission("mobile.admin")]

    def get(self, request):
        qs = MobileDevice.objects.select_related("user").all()
        user_id = request.query_params.get("user")
        platform = request.query_params.get("platform")
        active = request.query_params.get("active")
        if user_id:
            qs = qs.filter(user_id=user_id)
        if platform:
            qs = qs.filter(platform=platform)
        if active is not None:
            qs = qs.filter(is_active=active.lower() == "true")
        return Response(MobileDeviceSerializer(qs[:200], many=True).data)


class AdminPushSendView(APIView):
    """POST `/api/v1/mobile/push/` — admin sends a push to a user."""

    def get_permissions(self):
        return [IsAuthenticated(), _MOBILE_MODULE, HasPermission("mobile.admin")]

    def post(self, request):
        serializer = PushSendSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            target = User.objects.get(pk=data["user"])
        except (User.DoesNotExist, ValueError):
            return Response({"detail": "User not found."}, status=status.HTTP_404_NOT_FOUND)
        result = MobilePushService.send_to_user(
            target, title=data["title"], body=data.get("body", ""), data=data.get("data", {})
        )
        return Response(
            {
                "delivered": result.delivered,
                "failed": result.failed,
                "no_provider": result.no_provider,
                "delivery_ids": result.delivery_ids,
            }
        )


class AdminPushAuditView(APIView):
    """GET `/api/v1/mobile/push/` — recent push deliveries."""

    def get_permissions(self):
        return [IsAuthenticated(), _MOBILE_MODULE, HasPermission("mobile.admin")]

    def get(self, request):
        qs = PushDelivery.objects.select_related("user", "device").all()
        user_id = request.query_params.get("user")
        status_q = request.query_params.get("status")
        if user_id:
            qs = qs.filter(user_id=user_id)
        if status_q:
            qs = qs.filter(status=status_q)
        return Response(PushDeliverySerializer(qs[:200], many=True).data)
