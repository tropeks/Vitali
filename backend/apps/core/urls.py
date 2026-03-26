"""Core URLs — tenant schema routes."""
from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from . import views

app_name = "core"

urlpatterns = [
    # Auth
    path("auth/token/", views.HealthOSTokenObtainPairView.as_view(), name="token-obtain"),
    path("auth/token/refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    path("auth/me/", views.me, name="me"),
    # Users
    path("users/", views.UserListCreateView.as_view(), name="user-list"),
    path("users/<uuid:id>/", views.UserDetailView.as_view(), name="user-detail"),
    # Roles
    path("roles/", views.RoleListCreateView.as_view(), name="role-list"),
    # Tenant features
    path("features/", views.tenant_features, name="tenant-features"),
]
