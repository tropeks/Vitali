"""
Platform admin views — Plans, Subscriptions, module activation, pilot health.
All endpoints gated with IsPlatformAdmin (requires is_superuser).
These models live in the public schema — no schema switching needed.
"""

import logging
import time

from django.db import connection, transaction
from rest_framework import generics, status
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .constants import ALLOWED_MODULE_KEYS
from .models import FeatureFlag, Plan, Subscription, Tenant
from .permissions import IsPlatformAdmin
from .serializers_platform import (
    PlanSerializer,
    SubscriptionSerializer,
    TenantSubscriptionSerializer,
)

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
            return Response(
                {"detail": "module_key is required."}, status=status.HTTP_400_BAD_REQUEST
            )
        if module_key not in ALLOWED_MODULE_KEYS:
            return Response(
                {
                    "detail": f"Unknown module key '{module_key}'. Allowed: {', '.join(sorted(ALLOWED_MODULE_KEYS))}."
                },
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
            request.user.email,
            action,
            module_key,
            subscription.tenant.schema_name,
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
            return Response(
                {"detail": "module_key is required."}, status=status.HTTP_400_BAD_REQUEST
            )
        if module_key not in ALLOWED_MODULE_KEYS:
            return Response(
                {
                    "detail": f"Unknown module key '{module_key}'. Allowed: {', '.join(sorted(ALLOWED_MODULE_KEYS))}."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        FeatureFlag.objects.update_or_create(
            tenant=subscription.tenant,
            module_key=module_key,
            defaults={"is_enabled": False},
        )
        logger.info(
            "Platform admin %s deactivated module '%s' for tenant '%s'",
            request.user.email,
            module_key,
            subscription.tenant.schema_name,
        )

        # Keep Subscription.active_modules in sync (lock held — no concurrent write loss)
        if module_key in subscription.active_modules:
            subscription.active_modules = [
                m for m in subscription.active_modules if m != module_key
            ]
            subscription.save(update_fields=["active_modules"])

        return Response({"module_key": module_key, "is_enabled": False})


# ─── Pilot Health Dashboard (S-061) ──────────────────────────────────────────


class PilotHealthView(APIView):
    """
    GET /api/v1/platform/pilot-health/

    Behavioral KPIs + system health for the first-pilot monitoring dashboard.
    Platform admin only. Iterates all active tenant schemas via schema_context.
    Response shape is stable — add new KPI keys without removing old ones.

    Latency: O(tenants) DB queries. Acceptable for < 10 pilot tenants.
    """

    permission_classes = _PLATFORM_PERMS

    def get(self, request):
        from django.utils import timezone

        tenants = list(Tenant.objects.exclude(schema_name="public"))

        tenant_stats = []
        for tenant in tenants:
            stat = self._tenant_kpis(tenant)
            tenant_stats.append(stat)

        system = self._system_health()

        return Response(
            {
                "generated_at": timezone.now().isoformat(),
                "tenants": tenant_stats,
                "system": system,
            }
        )

    def _tenant_kpis(self, tenant) -> dict:
        """Per-tenant behavioral KPIs queried inside schema_context."""
        from django.utils import timezone
        from django_tenants.utils import schema_context

        now = timezone.now()
        today = now.date()
        week_ago = now - timezone.timedelta(days=7)
        month_ago = now - timezone.timedelta(days=30)

        kpis = {
            "schema": tenant.schema_name,
            "name": tenant.name,
            "created_at": tenant.created_at.isoformat()
            if hasattr(tenant, "created_at") and tenant.created_at
            else None,
        }

        try:
            with schema_context(tenant.schema_name):
                from apps.billing.models import PIXCharge
                from apps.emr.models import Appointment, Patient

                # Appointments today
                kpis["appointments_today"] = Appointment.objects.filter(
                    start_time__date=today
                ).count()

                # Appointments this week
                kpis["appointments_week"] = Appointment.objects.filter(
                    start_time__gte=week_ago
                ).count()

                # Show rate (completed / (completed + no_show)) this month
                completed = Appointment.objects.filter(
                    start_time__gte=month_ago, status="completed"
                ).count()
                no_show = Appointment.objects.filter(
                    start_time__gte=month_ago, status="no_show"
                ).count()
                total_closed = completed + no_show
                kpis["show_rate_30d"] = round(completed / total_closed, 3) if total_closed else None

                # Active patients (had an appointment in last 30 days)
                kpis["active_patients_30d"] = (
                    Appointment.objects.filter(start_time__gte=month_ago)
                    .values("patient")
                    .distinct()
                    .count()
                )

                # Total patients
                kpis["total_patients"] = Patient.objects.count()

                # PIX: charges created and paid this month
                kpis["pix_charges_month"] = PIXCharge.objects.filter(
                    created_at__gte=month_ago
                ).count()
                kpis["pix_paid_month"] = PIXCharge.objects.filter(
                    status=PIXCharge.Status.PAID, paid_at__gte=month_ago
                ).count()

        except Exception as exc:
            logger.error("pilot_health.tenant_kpi_error tenant=%s err=%s", tenant.schema_name, exc)
            kpis["error"] = str(exc)

        return kpis

    def _system_health(self) -> dict:
        """System-level health: DB latency, cache, worker."""
        health = {}

        # DB round-trip latency
        t0 = time.monotonic()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            health["db_latency_ms"] = round((time.monotonic() - t0) * 1000, 1)
            health["db_ok"] = True
        except Exception as exc:
            health["db_ok"] = False
            health["db_error"] = str(exc)

        # Cache ping
        try:
            from django.core.cache import cache

            cache.set("_pilot_health_ping", "1", timeout=5)
            health["cache_ok"] = cache.get("_pilot_health_ping") == "1"
        except Exception:
            health["cache_ok"] = False

        # Active tenant count
        health["tenant_count"] = Tenant.objects.exclude(schema_name="public").count()

        return health


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
            subscription = Subscription.objects.select_related("plan").get(tenant=request.tenant)
        except Subscription.DoesNotExist:
            return Response(
                {"detail": "Nenhuma assinatura ativa. Entre em contato com o suporte."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(TenantSubscriptionSerializer(subscription).data)
