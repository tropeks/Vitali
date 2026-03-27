"""Core URLs — public schema routes (platform admin + tenant onboarding)."""
from django.urls import path
from rest_framework import generics, permissions

from .models import Tenant
from .serializers import TenantSerializer
from .views import TenantRegistrationView


class TenantListView(generics.ListAPIView):
    serializer_class = TenantSerializer
    permission_classes = [permissions.IsAdminUser]
    queryset = Tenant.objects.all()


urlpatterns = [
    path("platform/tenants", TenantRegistrationView.as_view(), name="tenant-register"),
    path("platform/tenants/", TenantListView.as_view(), name="tenant-list"),
]
