"""Core URLs — public schema routes (platform admin + tenant onboarding)."""
from django.urls import path
from rest_framework import generics, permissions

from .models import Tenant
from .serializers import TenantSerializer
from .views import TenantRegistrationView
from .views_platform import (
    ActivateModuleView,
    DeactivateModuleView,
    PlanDetailView,
    PlanListCreateView,
    SubscriptionDetailView,
    SubscriptionListCreateView,
)
from .permissions import IsPlatformAdmin


class TenantListView(generics.ListAPIView):
    serializer_class = TenantSerializer
    permission_classes = [permissions.IsAuthenticated, IsPlatformAdmin]
    queryset = Tenant.objects.all()


urlpatterns = [
    # Tenant provisioning
    path("platform/tenants", TenantRegistrationView.as_view(), name="tenant-register"),
    path("platform/tenants/", TenantListView.as_view(), name="tenant-list"),

    # Plans
    path("platform/plans/", PlanListCreateView.as_view(), name="platform-plan-list"),
    path("platform/plans/<uuid:pk>/", PlanDetailView.as_view(), name="platform-plan-detail"),

    # Subscriptions
    path("platform/subscriptions/", SubscriptionListCreateView.as_view(), name="platform-subscription-list"),
    path("platform/subscriptions/<uuid:pk>/", SubscriptionDetailView.as_view(), name="platform-subscription-detail"),
    path("platform/subscriptions/<uuid:pk>/activate-module/", ActivateModuleView.as_view(), name="platform-activate-module"),
    path("platform/subscriptions/<uuid:pk>/deactivate-module/", DeactivateModuleView.as_view(), name="platform-deactivate-module"),
]
