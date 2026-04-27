"""Core URLs — tenant schema routes."""

from django.urls import path

from . import views
from .views_dpa import DPASignView, DPAStatusView
from .views_mfa import (
    MFADisableView,
    MFALoginView,
    MFASetupView,
    MFAStatusView,
    MFAVerifyView,
)
from .views_onboarding import OnboardingView
from .views_platform import TenantSubscriptionView
from .views_test_helpers import IssueInvitationTokenView

app_name = "core"

urlpatterns = [
    # Auth
    path("auth/login", views.LoginView.as_view(), name="login"),
    path("auth/logout", views.LogoutView.as_view(), name="logout"),
    path("auth/refresh", views.TokenRefreshView.as_view(), name="token-refresh"),
    path("auth/password", views.ChangePasswordView.as_view(), name="change-password"),
    # T6: invite-by-email flow
    path("auth/invite/", views.UserInvitationView.as_view(), name="auth-invite"),
    path(
        "auth/set-password/<str:token>/",
        views.SetPasswordView.as_view(),
        name="auth-set-password",
    ),
    # MFA (S-062)
    path("auth/mfa/status/", MFAStatusView.as_view(), name="mfa-status"),
    path("auth/mfa/setup/", MFASetupView.as_view(), name="mfa-setup"),
    path("auth/mfa/verify/", MFAVerifyView.as_view(), name="mfa-verify"),
    path("auth/mfa/login/", MFALoginView.as_view(), name="mfa-login"),
    path("auth/mfa/disable/", MFADisableView.as_view(), name="mfa-disable"),
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
    # DPA (S-070)
    path("settings/dpa/", DPAStatusView.as_view(), name="dpa-status"),
    path("settings/dpa/sign/", DPASignView.as_view(), name="dpa-sign"),
    # Test-only — gated by E2E_MODE + superuser + _test DB suffix (S-084)
    path(
        "_test/invitations/issue-token/",
        IssueInvitationTokenView.as_view(),
        name="test-issue-invitation-token",
    ),
]
