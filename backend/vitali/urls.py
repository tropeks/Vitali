"""
Vitali — URL Configuration (tenant schemas)
"""

from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

from vitali.urls_public import csp_report, readiness_check


def health(request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("health/", health, name="health"),
    path("readiness/", readiness_check, name="readiness-check"),
    path("admin/", admin.site.urls),
    path("api/v1/security/csp-report/", csp_report, name="csp-report"),
    # API v1
    path("api/v1/", include("apps.core.urls")),
    path("api/v1/", include("apps.emr.urls")),
    path("api/v1/", include("apps.billing.urls")),
    path("api/v1/", include("apps.pharmacy.urls")),
    path("api/v1/analytics/", include("apps.analytics.urls")),
    path("api/v1/", include("apps.ai.urls")),
    path("api/v1/", include("apps.whatsapp.urls")),
    path("api/v1/", include("apps.hr.urls")),
    path("api/v1/", include("apps.signatures.urls")),
    path("api/v1/", include("apps.fhir.urls")),
    path("api/v1/", include("apps.imaging.urls")),
    path("api/v1/", include("apps.telemedicine.urls")),
    path("api/v1/", include("apps.patient_portal.urls")),
    path("api/v1/", include("apps.pharmacy_ai.urls")),
    path("api/v1/", include("apps.smart_scheduling.urls")),
    path("api/v1/", include("apps.triage.urls")),
    path("api/v1/", include("apps.mobile.urls")),
    path("api/v1/", include("apps.organization.urls")),
    path("api/v1/", include("apps.governance.urls")),
    # OpenAPI docs
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
]
