"""
Vitali — URL Configuration (public schema)
Handles platform-level routes: tenant onboarding, admin, health check.
"""

import logging

from django.contrib import admin
from django.http import HttpResponse, JsonResponse
from django.urls import include, path
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.core.views import TUSSSyncStatusView

_csp_logger = logging.getLogger("vitali.security.csp")


def health_check(request):
    return JsonResponse({"status": "ok", "service": "vitali"})


@csrf_exempt
@require_POST
def csp_report(request):
    """Collect CSP violation reports (S28-05).

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
    path("api/v1/security/csp-report", csp_report, name="csp-report"),
    path("api/v1/", include("apps.core.urls_public")),
    # Orthanc PACS webhook (E-012) — PACS-wide feed, must fan out across all
    # tenants, so it runs from the public schema (like the Celery poller).
    path("api/v1/", include("apps.imaging.urls_public")),
    # TUSSSyncLog lives in public schema — must be routable from public schema URL conf
    path(
        "api/v1/ai/tuss-sync-status/", TUSSSyncStatusView.as_view(), name="tuss-sync-status-public"
    ),
]
