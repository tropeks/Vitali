"""
Platform admin views — Plans, Subscriptions, module activation, pilot health.
All endpoints gated with IsPlatformAdmin (requires is_superuser).
These models live in the public schema — no schema switching needed.
"""

import hmac
import logging
import time
from typing import Any

from django.conf import settings
from django.db import connection, transaction
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .constants import ALLOWED_MODULE_KEYS
from .models import FeatureFlag, Plan, Subscription, Tenant, User
from .permissions import IsPlatformAdmin
from .serializers_platform import (
    PlanSerializer,
    SubscriptionSerializer,
    TenantAdminSerializer,
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
        from datetime import timedelta

        from django.utils import timezone
        from django_tenants.utils import schema_context

        now = timezone.now()
        today = now.date()
        week_ago = now - timedelta(days=7)
        month_ago = now - timedelta(days=30)

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

                # Active patients (had an appointment in last 30 days).
                # Assign the starting manager to Any first — the .values().distinct().count()
                # chain crashes mypy 1.15's django-stubs plugin.
                appt_mgr: Any = Appointment.objects
                kpis["active_patients_30d"] = (
                    appt_mgr.filter(start_time__gte=month_ago).values("patient").distinct().count()
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
        health: dict[str, Any] = {}

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


# ─── Wedge business-value dashboard (issue #123) ─────────────────────────────


class WedgeValueDashboardView(APIView):
    """
    GET /api/v1/platform/wedge-value/

    Business-value (ROI) metrics per AI wedge per tenant for the platform
    operator. Platform admin only. Serves the daily ``WedgeValueSnapshot`` rows
    written by the ``core.snapshot_wedge_value`` Celery Beat task — O(1) schema,
    no per-request fan-out.

    Query params:
      ``live=1``  — recompute on the fly across tenant schemas instead of reading
                    snapshots (slower; useful before the first beat run or in dev).
      ``window``  — rolling window in days for the ``live`` path (default 30).

    Fallback: if no snapshot exists yet for ANY tenant, transparently computes
    live so the page is never blank before the first nightly run.
    """

    permission_classes = _PLATFORM_PERMS

    def get(self, request):
        from django.utils import timezone

        live = request.query_params.get("live") in ("1", "true", "True")
        try:
            window_days = int(request.query_params.get("window", 30))
        except (TypeError, ValueError):
            window_days = 30
        window_days = max(1, min(window_days, 365))

        if not live:
            payload = self._from_snapshots()
            if payload is not None:
                return Response(payload)
            # No snapshots yet — fall through to a live compute so the page works.

        return Response(self._compute_live(window_days, generated_at=timezone.now()))

    def _from_snapshots(self) -> dict | None:
        """Latest snapshot per tenant; None when no snapshot rows exist at all."""
        from apps.core.models import WedgeValueSnapshot

        snapshots = list(WedgeValueSnapshot.objects.all())
        if not snapshots:
            return None

        # Keep the newest snapshot per schema (rows are ordered -snapshot_date).
        latest_by_schema: dict[str, Any] = {}
        for snap in snapshots:
            existing = latest_by_schema.get(snap.schema_name)
            if existing is None or snap.snapshot_date > existing.snapshot_date:
                latest_by_schema[snap.schema_name] = snap

        tenants = [
            {
                "schema": snap.schema_name,
                "name": snap.tenant_name or snap.schema_name,
                "snapshot_date": snap.snapshot_date.isoformat(),
                "generated_at": snap.generated_at.isoformat(),
                "window_days": snap.window_days,
                "metrics": snap.metrics,
            }
            for snap in sorted(
                latest_by_schema.values(), key=lambda s: (s.tenant_name or s.schema_name)
            )
        ]
        newest = max(latest_by_schema.values(), key=lambda s: s.snapshot_date)
        return {
            "source": "snapshot",
            "generated_at": newest.generated_at.isoformat(),
            "snapshot_date": newest.snapshot_date.isoformat(),
            "tenants": tenants,
            "totals": self._totals(tenants),
        }

    def _compute_live(self, window_days: int, generated_at) -> dict:
        from apps.core.services.wedge_value import compute_wedge_value_for_tenant

        tenants_qs = Tenant.objects.exclude(schema_name="public")
        tenants = []
        for tenant in tenants_qs:
            try:
                metrics = compute_wedge_value_for_tenant(
                    tenant, window_days=window_days, now=generated_at
                )
                tenants.append(
                    {
                        "schema": tenant.schema_name,
                        "name": tenant.name,
                        "snapshot_date": generated_at.date().isoformat(),
                        "generated_at": generated_at.isoformat(),
                        "window_days": window_days,
                        "metrics": metrics,
                    }
                )
            except Exception as exc:
                logger.error(
                    "wedge_value.live_compute_failed tenant=%s err=%s",
                    tenant.schema_name,
                    exc,
                )
                tenants.append(
                    {
                        "schema": tenant.schema_name,
                        "name": tenant.name,
                        "error": str(exc),
                        "metrics": {},
                    }
                )

        tenants.sort(key=lambda t: t["name"])
        return {
            "source": "live",
            "generated_at": generated_at.isoformat(),
            "snapshot_date": generated_at.date().isoformat(),
            "tenants": tenants,
            "totals": self._totals(tenants),
        }

    @staticmethod
    def _totals(tenants: list[dict]) -> dict:
        """Aggregate headline numbers across all tenants for the summary band."""
        roi_brl = 0.0
        glosa_blocked = 0
        dose_fired = 0
        slots_recovered = 0
        stockout_intercepted = 0
        for t in tenants:
            m = t.get("metrics") or {}
            roi_brl += float((m.get("glosa_safety") or {}).get("blocked_value_brl", 0) or 0)
            glosa_blocked += int((m.get("glosa_safety") or {}).get("blocked_count", 0) or 0)
            dose_fired += int((m.get("dose_safety") or {}).get("fired", 0) or 0)
            slots_recovered += int(
                (m.get("no_show_prediction") or {}).get("slots_recovered", 0) or 0
            )
            stockout_intercepted += int((m.get("stockout_safety") or {}).get("intercepted", 0) or 0)
        return {
            "roi_brl": round(roi_brl, 2),
            "glosa_blocked_count": glosa_blocked,
            "dose_alerts_fired": dose_fired,
            "no_show_slots_recovered": slots_recovered,
            "stockout_intercepted": stockout_intercepted,
            "tenant_count": len(tenants),
        }


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


# ─── S-132: Self-serve admin panel + subscription billing ─────────────────────


class TenantAdminListView(APIView):
    """
    GET /api/v1/platform/tenants/

    Admin panel listing of clinics with lifecycle status + subscription summary.
    Supports ``?status=pending|trial|active|suspended|cancelled`` filtering and
    always returns per-status counts so the UI can render tabs without a second
    request. Platform admin only.
    """

    permission_classes = _PLATFORM_PERMS

    def get(self, request):
        qs = (
            Tenant.objects.exclude(schema_name="public")
            .select_related("subscription", "subscription__plan")
            .order_by("-created_at")
        )

        counts = {value: 0 for value, _ in Tenant.Status.choices}
        for value in qs.values_list("status", flat=True):
            if value in counts:
                counts[value] += 1
        counts["total"] = sum(c for k, c in counts.items() if k != "total")

        status_filter = request.query_params.get("status", "").strip().lower()
        valid_statuses = {value for value, _ in Tenant.Status.choices}
        if status_filter and status_filter in valid_statuses:
            qs = qs.filter(status=status_filter)

        return Response({"counts": counts, "results": TenantAdminSerializer(qs, many=True).data})


class ResendWelcomeView(APIView):
    """
    POST /api/v1/platform/tenants/{id}/resend-welcome/

    Re-issues the owner's set-password welcome email — for tenants stuck in
    PENDING because the original email bounced or was lost. Platform admin only.
    """

    permission_classes = _PLATFORM_PERMS

    def post(self, request, pk):
        try:
            tenant = Tenant.objects.get(pk=pk)
        except Tenant.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        owner = self._resolve_owner(tenant)
        if owner is None:
            return Response(
                {"detail": "Nenhum usuário owner encontrado para esta clínica."},
                status=status.HTTP_404_NOT_FOUND,
            )

        from .services.invitations import issue_password_set_invitation

        issue_password_set_invitation(owner, tenant=tenant, created_by=request.user)
        logger.info(
            "platform.resend_welcome by=%s tenant=%s owner=%s",
            request.user.email,
            tenant.schema_name,
            owner.email,
        )
        return Response({"detail": "E-mail de boas-vindas reenviado.", "owner_email": owner.email})

    def _resolve_owner(self, tenant) -> User | None:
        """The clinic owner = the admin-role member bound to this tenant."""
        memberships = tenant.user_memberships.filter(is_active=True).select_related("user", "role")
        admin_membership = memberships.filter(role__name="admin").first() or memberships.first()
        return admin_membership.user if admin_membership else None


class SubscriptionWebhookView(APIView):
    """
    POST /api/v1/public/billing/subscription-webhook/

    Asaas posts recurring-subscription payment events here. On the first
    confirmed/received payment we flip the tenant TRIAL → ACTIVE. Public
    endpoint — secured by the shared ``asaas-access-token`` header.

    Tenant/Subscription live in the public schema, so no schema switching is
    needed to resolve the tenant. Always returns 200 (except auth) to stop
    Asaas retry storms; idempotent on duplicate delivery.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    _ACTIVATING_EVENTS = {"PAYMENT_RECEIVED", "PAYMENT_CONFIRMED"}

    def post(self, request):
        token = request.headers.get("asaas-access-token", "")
        expected = getattr(settings, "ASAAS_WEBHOOK_TOKEN", "")
        if not expected or not hmac.compare_digest(token.encode(), expected.encode()):
            logger.warning(
                "subscription.webhook.invalid_token ip=%s", request.META.get("REMOTE_ADDR")
            )
            return Response({"status": "ok"}, status=status.HTTP_401_UNAUTHORIZED)

        event = request.data.get("event", "")
        payment = request.data.get("payment", {}) or {}
        asaas_subscription_id = payment.get("subscription", "")
        if event not in self._ACTIVATING_EVENTS or not asaas_subscription_id:
            return Response({"status": "ok"})

        with transaction.atomic():
            try:
                subscription = Subscription.objects.select_for_update().get(
                    asaas_subscription_id=asaas_subscription_id
                )
            except Subscription.DoesNotExist:
                logger.warning("subscription.webhook.unknown sub=%s", asaas_subscription_id)
                return Response({"status": "ok"})

            tenant = subscription.tenant
            # Only onboarding tenants (PENDING/TRIAL) get flipped live on first
            # payment. SUSPENDED/CANCELLED are deliberate ops states (abuse,
            # churn, fraud) — a late/retried Asaas payment event must NOT silently
            # reinstate them, or a suspension could be undone by a straggler
            # webhook. Reinstatement of those is a manual ops decision; we just
            # audit-log the ignored event here.
            if tenant.status not in (Tenant.Status.PENDING, Tenant.Status.TRIAL):
                logger.warning(
                    "subscription.webhook.reactivation_ignored tenant=%s sub=%s status=%s event=%s",
                    tenant.schema_name,
                    asaas_subscription_id,
                    tenant.status,
                    event,
                )
                return Response({"status": "ok"})

            if tenant.status != Tenant.Status.ACTIVE:
                tenant.status = Tenant.Status.ACTIVE
                tenant.save(update_fields=["status", "updated_at"])
            if subscription.status != Subscription.Status.ACTIVE:
                subscription.status = Subscription.Status.ACTIVE
                subscription.save(update_fields=["status"])

        logger.info(
            "subscription.webhook.activated tenant=%s sub=%s",
            tenant.schema_name,
            asaas_subscription_id,
        )
        return Response({"status": "ok"})
