"""
Vitali — URL Configuration (public schema)
Handles platform-level routes: tenant onboarding, admin, health check.
"""

from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path

from apps.core.views import TUSSSyncStatusView


def health_check(request):
    return JsonResponse({"status": "ok", "service": "vitali"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health_check, name="health-check"),
    path("api/v1/", include("apps.core.urls_public")),
    # TUSSSyncLog lives in public schema — must be routable from public schema URL conf
    path(
        "api/v1/ai/tuss-sync-status/", TUSSSyncStatusView.as_view(), name="tuss-sync-status-public"
    ),
]
