from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import FeatureFlag, Role, Tenant, User


class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = ("id", "name", "permissions", "is_system")
        read_only_fields = ("id", "is_system")


class UserSerializer(serializers.ModelSerializer):
    role = RoleSerializer(read_only=True)
    role_id = serializers.PrimaryKeyRelatedField(
        queryset=Role.objects.all(), source="role", write_only=True, required=False
    )

    class Meta:
        model = User
        fields = (
            "id", "email", "full_name", "role", "role_id",
            "is_active", "last_login", "created_at",
        )
        read_only_fields = ("id", "last_login", "created_at")


class UserCreateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)
    role_id = serializers.PrimaryKeyRelatedField(
        queryset=Role.objects.all(), source="role", required=False
    )

    class Meta:
        model = User
        fields = ("email", "full_name", "cpf", "password", "role_id")

    def create(self, validated_data):
        password = validated_data.pop("password")
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user


class HealthOSTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Custom JWT payload with user info."""

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["email"] = user.email
        token["full_name"] = user.full_name
        token["role"] = user.role.name if user.role else None
        return token


class TenantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tenant
        fields = (
            "id", "name", "slug", "schema_name", "cnpj",
            "status", "trial_ends_at", "created_at",
        )
        read_only_fields = ("id", "schema_name", "created_at")


class FeatureFlagSerializer(serializers.ModelSerializer):
    class Meta:
        model = FeatureFlag
        fields = ("id", "module_key", "is_enabled")
