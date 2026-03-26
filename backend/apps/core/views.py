from django.http import JsonResponse
from rest_framework import generics, permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .models import FeatureFlag, Role, User
from .serializers import (
    FeatureFlagSerializer,
    HealthOSTokenObtainPairSerializer,
    RoleSerializer,
    UserCreateSerializer,
    UserSerializer,
)


class HealthOSTokenObtainPairView(TokenObtainPairView):
    serializer_class = HealthOSTokenObtainPairSerializer


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def me(request):
    """Return current user info."""
    serializer = UserSerializer(request.user)
    return Response(serializer.data)


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def tenant_features(request):
    """Return enabled features for the current tenant."""
    if not hasattr(request, "tenant"):
        return Response({"features": []})
    flags = FeatureFlag.objects.filter(tenant=request.tenant, is_enabled=True)
    return Response({"features": [f.module_key for f in flags]})


class UserListCreateView(generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method == "POST":
            return UserCreateSerializer
        return UserSerializer

    def get_queryset(self):
        return User.objects.select_related("role").filter(is_active=True)


class UserDetailView(generics.RetrieveUpdateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = UserSerializer
    queryset = User.objects.all()
    lookup_field = "id"


class RoleListCreateView(generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = RoleSerializer
    queryset = Role.objects.all()
