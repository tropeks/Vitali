"""
Platform admin views — Plans, Subscriptions, module activation.
All endpoints gated with IsPlatformAdmin (requires is_superuser).
These models live in the public schema — no schema switching needed.
"""
import logging

from django.db import transaction
from rest_framework import generics, status
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .constants import ALLOWED_MODULE_KEYS
from .models import FeatureFlag, Plan, Subscription, Tenant
from .permissions import IsPlatformAdmin
from .serializers_platform import PlanSerializer, SubscriptionSerializer, TenantSubscriptionSerializer

logger = logging.getLogger(__name__)

_PLATFORM_PERMS = (IsAuthenticated, IsPlatformAdmin)


def _get_subscription(pk, lock=False):
    """Module-level helper — used by both ActivateModuleView and DeactivateModuleView.
    Pass lock=True inside a transaction to prevent concurrent active_modules updates."""
    try:
        qs = Subscription.objects.select_related("tenant")
        if lock:
            qs = qs.select_for_update()
        return qs.get(pk=pk)
    except Subscription.DoesNotExist:
        return None


# ─── Plans ────────────────────────────────────────────────────────────────────

class PlanListCreateView(generics.ListCreateAPIView):
    """GET/POST /api/v1/platform/plans/"""
    serializer_class = PlanSerializer
    permission_classes = _PLATFORM_PERMS
    queryset = Plan.objects.prefetch_related("modules").order_by("name")


class PlanDetailView(generics.RetrieveUpdateAPIView):
    """GET/PATCH /api/v1/platform/plans/{id}/"""
    serializer_class = PlanSerializer
    permission_classes = _PLATFORM_PERMS
    queryset = Plan.objects.prefetch_related("modules")
    lookup_field = "pk"


# ─── Subscriptions ────────────────────────────────────────────────────────────

class SubscriptionListCreateView(generics.ListCreateAPIView):
    """GET/POST /api/v1/platform/subscriptions/"""
    serializer_class = SubscriptionSerializer
    permission_classes = _PLATFORM_PERMS
    queryset = Subscription.objects.select_related("tenant", "plan").order_by("-created_at")


class SubscriptionDetailView(generics.RetrieveUpdateAPIView):
    """GET/PATCH /api/v1/platform/subscriptions/{id}/"""
    serializer_class = SubscriptionSerializer
    permission_classes = _PLATFORM_PERMS
    queryset = Subscription.objects.select_related("tenant", "plan")
    lookup_field = "pk"

    @transaction.atomic
    def perform_update(self, serializer):
        """Sync FeatureFlag rows when active_modules is changed via PATCH.
        Atomic: if any FeatureFlag upsert fails, the Subscription save rolls back too.
        Re-reads the row with select_for_update before computing old_modules to prevent
        a TOCTOU race where two concurrent PATCHes read the same old state, then one
        overwrites the other's FeatureFlag changes."""
        locked = Subscription.objects.select_for_update().get(pk=serializer.instance.pk)
        old_modules = set(locked.active_modules)
        subscription = serializer.save()
        new_modules = set(subscription.active_modules)

        added = new_modules - old_modules
        removed = old_modules - new_modules

        for module_key in added:
            FeatureFlag.objects.update_or_create(
                tenant=subscription.tenant,
                module_key=module_key,
                defaults={"is_enabled": True},
            )
        for module_key in removed:
            FeatureFlag.objects.update_or_create(
                tenant=subscription.tenant,
                module_key=module_key,
                defaults={"is_enabled": False},
            )


class ActivateModuleView(APIView):
    """
    POST /api/v1/platform/subscriptions/{id}/activate-module/
    Body: {"module_key": "billing"}
    Creates/enables a FeatureFlag for the subscription's tenant.
    FeatureFlag is in SHARED_APPS (public schema) — no schema switching needed.
    """
    permission_classes = _PLATFORM_PERMS

    @transaction.atomic
    def post(self, request, pk):
        subscription = _get_subscription(pk, lock=True)
        if subscription is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        module_key = request.data.get("module_key", "").strip()
        if not module_key:
            return Response({"detail": "module_key is required."}, status=status.HTTP_400_BAD_REQUEST)
        if module_key not in ALLOWED_MODULE_KEYS:
            return Response(
                {"detail": f"Unknown module key '{module_key}'. Allowed: {', '.join(sorted(ALLOWED_MODULE_KEYS))}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        flag, created = FeatureFlag.objects.update_or_create(
            tenant=subscription.tenant,
            module_key=module_key,
            defaults={"is_enabled": True},
        )
        action = "created" if created else "enabled"
        logger.info(
            "Platform admin %s %s module '%s' for tenant '%s'",
            request.user.email, action, module_key, subscription.tenant.schema_name,
        )

        # Keep Subscription.active_modules in sync (lock held — no concurrent write loss)
        if module_key not in subscription.active_modules:
            subscription.active_modules = subscription.active_modules + [module_key]
            subscription.save(update_fields=["active_modules"])

        return Response({"module_key": module_key, "is_enabled": True})


class DeactivateModuleView(APIView):
    """
    POST /api/v1/platform/subscriptions/{id}/deactivate-module/
    Body: {"module_key": "billing"}
    Disables a FeatureFlag for the subscription's tenant.
    """
    permission_classes = _PLATFORM_PERMS

    @transaction.atomic
    def post(self, request, pk):
        subscription = _get_subscription(pk, lock=True)
        if subscription is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        module_key = request.data.get("module_key", "").strip()
        if not module_key:
            return Response({"detail": "module_key is required."}, status=status.HTTP_400_BAD_REQUEST)
        if module_key not in ALLOWED_MODULE_KEYS:
            return Response(
                {"detail": f"Unknown module key '{module_key}'. Allowed: {', '.join(sorted(ALLOWED_MODULE_KEYS))}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        FeatureFlag.objects.update_or_create(
            tenant=subscription.tenant,
            module_key=module_key,
            defaults={"is_enabled": False},
        )
        logger.info(
            "Platform admin %s deactivated module '%s' for tenant '%s'",
            request.user.email, module_key, subscription.tenant.schema_name,
        )

        # Keep Subscription.active_modules in sync (lock held — no concurrent write loss)
        if module_key in subscription.active_modules:
            subscription.active_modules = [m for m in subscription.active_modules if m != module_key]
            subscription.save(update_fields=["active_modules"])

        return Response({"module_key": module_key, "is_enabled": False})


# ─── Tenant-facing subscription status (S-041) ────────────────────────────────

class TenantSubscriptionView(APIView):
    """
    GET /api/v1/core/subscription/
    Returns the current tenant's subscription details including pricing.
    Restricted to staff/admin users — pricing data is business-sensitive.
    """
    permission_classes = [IsAuthenticated, IsAdminUser]

    def get(self, request):
        if not hasattr(request, "tenant"):
            return Response(
                {"detail": "Nenhuma assinatura ativa. Entre em contato com o suporte."},
                status=status.HTTP_404_NOT_FOUND,
            )
        try:
            subscription = Subscription.objects.select_related("plan").get(
                tenant=request.tenant
            )
        except Subscription.DoesNotExist:
            return Response(
                {"detail": "Nenhuma assinatura ativa. Entre em contato com o suporte."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(TenantSubscriptionSerializer(subscription).data)
