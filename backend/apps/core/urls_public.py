"""Core URLs — public schema routes (platform admin)."""
from django.urls import path
from .serializers import TenantSerializer
from rest_framework import generics, permissions
from .models import Tenant


class TenantListView(generics.ListAPIView):
    serializer_class = TenantSerializer
    permission_classes = [permissions.IsAdminUser]
    queryset = Tenant.objects.all()


urlpatterns = [
    path("tenants/", TenantListView.as_view(), name="tenant-list"),
]
