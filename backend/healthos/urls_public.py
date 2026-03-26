"""
Vitali — URL Configuration (public schema)
Handles platform-level routes: tenant onboarding, admin, health check.
"""
from django.contrib import admin
from django.urls import path, include
from django.http import JsonResponse


def health_check(request):
    return JsonResponse({"status": "ok", "service": "vitali"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health_check, name="health-check"),
    path("api/v1/", include("apps.core.urls_public")),
]
