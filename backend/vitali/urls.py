"""
Vitali — URL Configuration (tenant schemas)
"""
from django.contrib import admin
from django.urls import path, include
from django.http import JsonResponse
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
    SpectacularRedocView,
)

def health(request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("health/", health, name="health"),
    path("admin/", admin.site.urls),
    # API v1
    path("api/v1/", include("apps.core.urls")),
    path("api/v1/", include("apps.emr.urls")),
    path("api/v1/", include("apps.billing.urls")),
    path("api/v1/", include("apps.pharmacy.urls")),
    path("api/v1/analytics/", include("apps.analytics.urls")),
    path("api/v1/", include("apps.ai.urls")),
    # OpenAPI docs
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
]
