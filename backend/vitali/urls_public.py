"""
Vitali — URL Configuration (public schema)
Handles platform-level routes: tenant onboarding, admin, health check.
"""

import logging
import time

from django.contrib import admin
from django.core.cache import cache
from django.db import connection
from django.http import HttpResponse, JsonResponse
from django.urls import include, path
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.core.views import TUSSSyncStatusView

_csp_logger = logging.getLogger("vitali.security.csp")


def health_check(request):
    return JsonResponse({"status": "ok", "service": "vitali"})


def readiness_check(request):
    """Dependency-aware readiness probe for orchestrators and uptime monitors.

    ``/health/`` is intentionally process-only; this endpoint verifies the
    dependencies required to serve requests and returns 503 when one is down.
    It never includes exception details or connection data in the response.
    """
    checks = {}
    try:
        started = time.monotonic()
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        checks["database"] = {
            "ok": True,
            "latency_ms": round((time.monotonic() - started) * 1000, 1),
        }
    except Exception:
        checks["database"] = {"ok": False}
    try:
        cache_key = "_vitali_readiness_probe"
        cache.set(cache_key, "1", timeout=5)
        checks["cache"] = {"ok": cache.get(cache_key) == "1"}
    except Exception:
        checks["cache"] = {"ok": False}
    ready = all(item["ok"] for item in checks.values())
    return JsonResponse(
        {"status": "ready" if ready else "not_ready", "checks": checks},
        status=200 if ready else 503,
    )


@csrf_exempt
@require_POST
def csp_report(request):
    """Collect CSP violation reports (S28-05; activated in #115).

    The CSP header ships report-only with ``report-uri`` pointing here, so violations
    are logged before the policy is promoted to enforcing. No auth (browsers post
    unauthenticated) and no PHI — only the directive/URI metadata the browser sends.
    Always 204 so the browser never retries.
    """
    body = request.body[:4096].decode("utf-8", errors="replace") if request.body else ""
    _csp_logger.warning("csp_violation", extra={"report": body})
    return HttpResponse(status=204)


urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health_check, name="health-check"),
    path("readiness/", readiness_check, name="readiness-check"),
    # Trailing slash: the Next.js API proxy appends one to every forwarded path,
    # so the browser's report-uri (no slash) resolves here after proxying.
    path("api/v1/security/csp-report/", csp_report, name="csp-report"),
    path("api/v1/", include("apps.core.urls_public")),
    # Orthanc PACS webhook (E-012) — PACS-wide feed, must fan out across all
    # tenants, so it runs from the public schema (like the Celery poller).
    path("api/v1/", include("apps.imaging.urls_public")),
    # TUSSSyncLog lives in public schema — must be routable from public schema URL conf
    path(
        "api/v1/ai/tuss-sync-status/", TUSSSyncStatusView.as_view(), name="tuss-sync-status-public"
    ),
]
