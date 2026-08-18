"""
Core serializers for Vitali.
"""

import re

from django.contrib.auth.password_validation import validate_password as _django_validate_password
from django.core.exceptions import ValidationError as _DjangoValidationError
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from .models import AuditLog, FeatureFlag, Role, Tenant, User

# ─── Role & User ──────────────────────────────────────────────────────────────


class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = ("id", "name", "permissions", "is_system")
        read_only_fields = ("id", "is_system")


class AuditTrailEntrySerializer(serializers.ModelSerializer):
    """DPO-facing view of AuditLog (3.4 — Onda 3): WHO accessed WHAT and WHEN,
    never the clinical content itself.

    Deliberately omits ``old_data``/``new_data``: those columns carry full
    field snapshots (e.g. a ``create``/``update`` row on ``Prescription`` can
    embed the entire clinical payload). This endpoint answers "quem acessou o
    prontuário do paciente X", not "o que estava no prontuário" — surfacing the
    snapshots here would turn a metadata/traceability endpoint into a bulk PHI
    export gated only by ``IsTenantAdmin``, bypassing the per-module
    permissions (``emr.read``, ``sae.read``, ...) that normally gate that
    content. See AuditTrailListView for the permission rationale.
    """

    user_email = serializers.SerializerMethodField()

    class Meta:
        model = AuditLog
        fields = (
            "id",
            "user",
            "user_email",
            "action",
            "resource_type",
            "resource_id",
            "ip_address",
            "created_at",
        )
        read_only_fields = fields

    def get_user_email(self, obj):
        return obj.user.email if obj.user_id else None


class TenantScopedRoleField(serializers.PrimaryKeyRelatedField):
    """PrimaryKeyRelatedField restricted to Role.for_current_tenant() (0.4/0.5).

    ``queryset=Role.objects.all()`` bound at class-definition time (module
    import) is evaluated before any request/tenant context exists — it would
    freeze the choice set to whatever schema was active at import, and worse,
    let a tenant-A admin assign a role_id belonging to tenant B (the RBAC
    namespace leak the audit found). Overriding ``get_queryset`` re-resolves
    ``connection.tenant`` on every request/validation instead.
    """

    def get_queryset(self):
        return Role.for_current_tenant()


class UserSerializer(serializers.ModelSerializer):
    role = RoleSerializer(read_only=True)
    role_id = TenantScopedRoleField(source="role", write_only=True, required=False)

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
    # 3.5: was min_length=8 with no strength check at all — an admin could
    # provision a coworker with "password123456". Aligned with the other two
    # password-setting paths (SetPasswordView, ChangePasswordSerializer).
    password = serializers.CharField(write_only=True, min_length=12)
    role_id = TenantScopedRoleField(source="role", required=False)

    class Meta:
        model = User
        fields = ("email", "full_name", "cpf", "password", "role_id")

    def validate_password(self, value: str) -> str:
        # No saved instance yet — build an unsaved pseudo-user so
        # UserAttributeSimilarityValidator can compare against the email/name
        # being provisioned, same as Django does for a real user.
        pseudo_user = User(
            email=self.initial_data.get("email", ""),
            full_name=self.initial_data.get("full_name", ""),
        )
        _validate_strong_password(value, user=pseudo_user)
        return value

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
    permissions = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "full_name",
            "role_name",
            "active_modules",
            "permissions",
            # Platform-admin (superuser) signal for the client Plataforma nav gate.
            # Backend IsPlatformAdmin remains the real barrier; this is UX-only.
            "is_superuser",
        )
        read_only_fields = ("is_superuser",)

    def get_permissions(self, obj) -> list[str]:
        # Mirror HasPermission's tenant-effective role (membership Model B), not
        # merely the user's legacy/global role, so navigation never advertises
        # actions from another tenant membership.
        from apps.core.permissions import role_has_admin_capability

        role = obj.effective_role()
        if not role:
            return []
        perms = list(role.permissions or [])
        # Emit the EFFECTIVE admin capability so the client RBAC (canSee) matches
        # the backend: is_system admin roles carry the capability via is_system +
        # name (role_has_admin_capability), not necessarily the literal "admin"
        # string (their stored list may predate it). Never keyed off role_name.
        if "admin" not in perms and role_has_admin_capability(role):
            perms.append("admin")
        return perms

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
                _(
                    "Slug deve conter apenas letras minúsculas, números e hífens "
                    "(2–63 caracteres, não pode começar ou terminar com hífen)."
                )
            )
        if Tenant.objects.filter(slug=value).exists():
            raise serializers.ValidationError(_("Este slug já está em uso."))
        return value

    def validate_cnpj(self, value: str) -> str:
        if not value:
            return value
        digits = re.sub(r"\D", "", value)
        if len(digits) != 14:
            raise serializers.ValidationError(_("CNPJ deve conter 14 dígitos."))
        if len(set(digits)) == 1:
            raise serializers.ValidationError(_("CNPJ inválido."))
        if not _cnpj_valid(digits):
            raise serializers.ValidationError(_("CNPJ inválido."))
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


class SelfServeSignupSerializer(serializers.Serializer):
    """
    Public self-serve signup (S-132). Minimal clinic-facing form: company name,
    CNPJ and contact email — the heavy provisioning (slug, schema, owner, trial)
    is derived server-side so the clinic never deals with infra concepts.
    """

    company_name = serializers.CharField(max_length=255)
    cnpj = serializers.CharField(max_length=18)
    email = serializers.EmailField()
    # Optional: the owner's display name. Falls back to the company name.
    owner_full_name = serializers.CharField(max_length=255, required=False, allow_blank=True)

    def validate_company_name(self, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise serializers.ValidationError("Informe o nome da clínica.")
        return value

    def validate_cnpj(self, value: str) -> str:
        digits = re.sub(r"\D", "", value or "")
        if len(digits) != 14:
            raise serializers.ValidationError("CNPJ deve conter 14 dígitos.")
        if len(set(digits)) == 1 or not _cnpj_valid(digits):
            raise serializers.ValidationError("CNPJ inválido.")
        return f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}"

    def validate_email(self, value: str) -> str:
        return value.strip().lower()


def _validate_strong_password(value: str, user: User | None = None):
    """Enforce: min 12 chars, uppercase, lowercase, digit, special char — plus
    Django's configured AUTH_PASSWORD_VALIDATORS (settings/base.py:135-140:
    UserAttributeSimilarityValidator, MinimumLengthValidator,
    CommonPasswordValidator, NumericPasswordValidator).

    3.5 audit finding: those four validators were defined in settings but
    ``validate_password`` was never called anywhere in the codebase, so they
    were dead code — a regex-only check (as before) doesn't catch a strong-
    looking but leaked/dictionary password (CommonPasswordValidator) or one
    built from the user's own name/e-mail (UserAttributeSimilarityValidator).
    """
    if len(value) < 12:
        raise serializers.ValidationError(_("Senha deve ter no mínimo 12 caracteres."))
    if not re.search(r"[A-Z]", value):
        raise serializers.ValidationError(_("Senha deve conter pelo menos uma letra maiúscula."))
    if not re.search(r"[a-z]", value):
        raise serializers.ValidationError(_("Senha deve conter pelo menos uma letra minúscula."))
    if not re.search(r"\d", value):
        raise serializers.ValidationError(_("Senha deve conter pelo menos um número."))
    if not re.search(r"[^A-Za-z0-9]", value):
        raise serializers.ValidationError(_("Senha deve conter pelo menos um caractere especial."))
    try:
        _django_validate_password(value, user=user)
    except _DjangoValidationError as exc:
        raise serializers.ValidationError(list(exc.messages)) from exc


# ─── Auth ─────────────────────────────────────────────────────────────────────


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, min_length=12)

    def validate_new_password(self, value: str) -> str:
        request = self.context.get("request")
        user = getattr(request, "user", None) if request else None
        _validate_strong_password(value, user=user)
        return value


# ─── Feature flags ────────────────────────────────────────────────────────────


class FeatureFlagSerializer(serializers.ModelSerializer):
    class Meta:
        model = FeatureFlag
        fields = ("id", "module_key", "is_enabled")
