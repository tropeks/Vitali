"""Core URLs — tenant schema routes."""
from django.urls import path

from . import views
from .views_platform import TenantSubscriptionView
from .views_onboarding import OnboardingView

app_name = "core"

urlpatterns = [
    # Auth
    path("auth/login", views.LoginView.as_view(), name="login"),
    path("auth/logout", views.LogoutView.as_view(), name="logout"),
    path("auth/refresh", views.TokenRefreshView.as_view(), name="token-refresh"),
    path("auth/password", views.ChangePasswordView.as_view(), name="change-password"),
    # Current user
    path("me", views.MeView.as_view(), name="me"),
    # Users
    path("users/", views.UserListCreateView.as_view(), name="user-list"),
    path("users/<uuid:id>/", views.UserDetailView.as_view(), name="user-detail"),
    # Roles
    path("roles/", views.RoleListCreateView.as_view(), name="role-list"),
    # Tenant features
    path("features/", views.TenantFeaturesView.as_view(), name="tenant-features"),
    # Tenant subscription status
    path("subscription/", TenantSubscriptionView.as_view(), name="tenant-subscription"),
    # Onboarding checklist
    path("onboarding/", OnboardingView.as_view(), name="onboarding"),
    # AI: TUSS sync status (admin-only)
    path("ai/tuss-sync-status/", views.TUSSSyncStatusView.as_view(), name="tuss-sync-status"),
]
