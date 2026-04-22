"""
Core serializers for Vitali.
"""

import re

from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import FeatureFlag, Role, Tenant, User

# ─── Role & User ──────────────────────────────────────────────────────────────


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
            "id",
            "email",
            "full_name",
            "role",
            "role_id",
            "is_active",
            "last_login",
            "created_at",
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


class UserDTOSerializer(serializers.ModelSerializer):
    """Lightweight user representation returned in JWT responses."""

    role_name = serializers.CharField(source="role.name", read_only=True, default=None)
    active_modules = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ("id", "email", "full_name", "role_name", "active_modules")

    def get_active_modules(self, obj) -> list:
        """Return active modules for the current tenant via FeatureFlag."""
        request = self.context.get("request")
        if request and hasattr(request, "tenant"):
            return list(
                FeatureFlag.objects.filter(tenant=request.tenant, is_enabled=True).values_list(
                    "module_key", flat=True
                )
            )
        return []


# ─── JWT ──────────────────────────────────────────────────────────────────────


class HealthOSTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Custom JWT payload with user info (legacy — used by the token endpoint)."""

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["email"] = user.email
        token["full_name"] = user.full_name
        token["role"] = user.role.name if user.role else None
        return token


# ─── DPA (S-070) ─────────────────────────────────────────────────────────────


class DPAStatusSerializer(serializers.Serializer):
    is_signed = serializers.BooleanField()
    signed_at = serializers.DateField(allow_null=True)
    signed_by_name = serializers.CharField(allow_null=True)
    ai_scribe_enabled = serializers.BooleanField()


# ─── Tenant ───────────────────────────────────────────────────────────────────


class TenantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tenant
        fields = (
            "id",
            "name",
            "slug",
            "schema_name",
            "cnpj",
            "status",
            "trial_ends_at",
            "created_at",
        )
        read_only_fields = ("id", "schema_name", "created_at")


class TenantRegistrationSerializer(serializers.Serializer):
    """Validates input for new tenant onboarding (S-005)."""

    # Tenant fields
    name = serializers.CharField(max_length=255)
    slug = serializers.SlugField(max_length=63)
    cnpj = serializers.CharField(max_length=18, required=False, allow_blank=True)

    # Admin user fields
    admin_email = serializers.EmailField()
    admin_full_name = serializers.CharField(max_length=255)
    admin_password = serializers.CharField(write_only=True, min_length=12)

    def validate_slug(self, value: str) -> str:
        value = value.lower().strip()
        if not re.match(r"^[a-z0-9][a-z0-9\-]{1,61}[a-z0-9]$", value):
            raise serializers.ValidationError(
                "Slug deve conter apenas letras minúsculas, números e hífens "
                "(2–63 caracteres, não pode começar ou terminar com hífen)."
            )
        if Tenant.objects.filter(slug=value).exists():
            raise serializers.ValidationError("Este slug já está em uso.")
        return value

    def validate_cnpj(self, value: str) -> str:
        if not value:
            return value
        digits = re.sub(r"\D", "", value)
        if len(digits) != 14:
            raise serializers.ValidationError("CNPJ deve conter 14 dígitos.")
        if len(set(digits)) == 1:
            raise serializers.ValidationError("CNPJ inválido.")
        if not _cnpj_valid(digits):
            raise serializers.ValidationError("CNPJ inválido.")
        # Format: XX.XXX.XXX/XXXX-XX
        return f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}"

    def validate_admin_password(self, value: str) -> str:
        _validate_strong_password(value)
        return value


def _cnpj_valid(digits: str) -> bool:
    """Validate CNPJ check digits."""

    def _calc(digits, weights):
        total = sum(int(d) * w for d, w in zip(digits, weights, strict=False))
        remainder = total % 11
        return 0 if remainder < 2 else 11 - remainder

    weights1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    weights2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    return _calc(digits[:12], weights1) == int(digits[12]) and _calc(digits[:13], weights2) == int(
        digits[13]
    )


def _validate_strong_password(value: str):
    """Enforce: min 12 chars, uppercase, lowercase, digit, special char."""
    if len(value) < 12:
        raise serializers.ValidationError("Senha deve ter no mínimo 12 caracteres.")
    if not re.search(r"[A-Z]", value):
        raise serializers.ValidationError("Senha deve conter pelo menos uma letra maiúscula.")
    if not re.search(r"[a-z]", value):
        raise serializers.ValidationError("Senha deve conter pelo menos uma letra minúscula.")
    if not re.search(r"\d", value):
        raise serializers.ValidationError("Senha deve conter pelo menos um número.")
    if not re.search(r"[^A-Za-z0-9]", value):
        raise serializers.ValidationError("Senha deve conter pelo menos um caractere especial.")


# ─── Auth ─────────────────────────────────────────────────────────────────────


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, min_length=12)

    def validate_new_password(self, value: str) -> str:
        _validate_strong_password(value)
        return value


# ─── Feature flags ────────────────────────────────────────────────────────────


class FeatureFlagSerializer(serializers.ModelSerializer):
    class Meta:
        model = FeatureFlag
        fields = ("id", "module_key", "is_enabled")
