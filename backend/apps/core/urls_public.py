"""Core URLs — public schema routes (platform admin + tenant onboarding)."""

from django.urls import path

from .views import SetPasswordView, TenantRegistrationView
from .views_platform import (
    ActivateModuleView,
    DeactivateModuleView,
    PilotHealthView,
    PlanDetailView,
    PlanListCreateView,
    ResendWelcomeView,
    SubscriptionDetailView,
    SubscriptionListCreateView,
    SubscriptionWebhookView,
    TenantAdminListView,
    WedgeValueDashboardView,
)
from .views_signup import SelfServeSignupView

urlpatterns = [
    # S-132: Public self-serve signup (no auth) + subscription billing webhook.
    path("public/signup/", SelfServeSignupView.as_view(), name="self-serve-signup"),
    path(
        "public/billing/subscription-webhook/",
        SubscriptionWebhookView.as_view(),
        name="subscription-webhook",
    ),
    # Owner activation: welcome link lands on the main (public) domain, so the
    # set-password endpoint must resolve here too (User lives in public schema).
    path(
        "auth/set-password/<str:token>/",
        SetPasswordView.as_view(),
        name="auth-set-password-public",
    ),
    # Tenant provisioning (engineer/platform-admin flow)
    path("platform/tenants", TenantRegistrationView.as_view(), name="tenant-register"),
    path("platform/tenants/", TenantAdminListView.as_view(), name="tenant-list"),
    path(
        "platform/tenants/<uuid:pk>/resend-welcome/",
        ResendWelcomeView.as_view(),
        name="tenant-resend-welcome",
    ),
    # Plans
    path("platform/plans/", PlanListCreateView.as_view(), name="platform-plan-list"),
    path("platform/plans/<uuid:pk>/", PlanDetailView.as_view(), name="platform-plan-detail"),
    # Subscriptions
    path(
        "platform/subscriptions/",
        SubscriptionListCreateView.as_view(),
        name="platform-subscription-list",
    ),
    path(
        "platform/subscriptions/<uuid:pk>/",
        SubscriptionDetailView.as_view(),
        name="platform-subscription-detail",
    ),
    path(
        "platform/subscriptions/<uuid:pk>/activate-module/",
        ActivateModuleView.as_view(),
        name="platform-activate-module",
    ),
    path(
        "platform/subscriptions/<uuid:pk>/deactivate-module/",
        DeactivateModuleView.as_view(),
        name="platform-deactivate-module",
    ),
    # S-061: Pilot health dashboard
    path("platform/pilot-health/", PilotHealthView.as_view(), name="platform-pilot-health"),
    # Issue #123: Wedge business-value (ROI) dashboard
    path(
        "platform/wedge-value/",
        WedgeValueDashboardView.as_view(),
        name="platform-wedge-value",
    ),
]
