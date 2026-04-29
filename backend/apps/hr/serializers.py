"""DRF serializers for HR models."""

import re

from rest_framework import serializers

from apps.core.models import Role, User

from .models import Employee
from .services import CLINICAL_ROLES

CONTRACT_TYPE_ALIASES = {
    "autonomo": "temporary",
    "estagiario": "estagio",
}
EMPLOYMENT_STATUS_ALIASES = {
    "on_leave": "leave",
}


class EmployeeSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(source="user.full_name", read_only=True)
    email = serializers.EmailField(source="user.email", read_only=True)
    role = serializers.CharField(source="user.role.name", read_only=True, default=None)

    class Meta:
        model = Employee
        fields = [
            "id",
            "user",
            "full_name",
            "email",
            "role",
            "hire_date",
            "employment_status",
            "contract_type",
            "terminated_at",
            "created_at",
        ]
        read_only_fields = ["id", "user", "created_at"]


class EmployeeOnboardingSerializer(serializers.Serializer):
    """
    Payload serializer for POST /api/v1/hr/employees/.

    Spans User + Employee + optional Professional — cannot be a ModelSerializer.
    Cross-field validation mirrors the service-layer _validate() for early
    rejection (before the service is called).
    """

    # User fields
    full_name = serializers.CharField(max_length=255)
    email = serializers.EmailField()
    cpf = serializers.CharField(max_length=14)
    phone = serializers.CharField(max_length=20, required=False, allow_blank=True, default="")

    # RBAC
    role = serializers.CharField()

    # Employee fields
    hire_date = serializers.DateField()
    contract_type = serializers.ChoiceField(choices=Employee.CONTRACT_TYPE_CHOICES)
    employment_status = serializers.ChoiceField(
        choices=Employee.EMPLOYMENT_STATUS_CHOICES, default="active"
    )

    # Professional (clinical roles only)
    council_type = serializers.CharField(required=False, allow_blank=True, default="")
    council_number = serializers.CharField(required=False, allow_blank=True, default="")
    council_state = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=2
    )
    specialty = serializers.CharField(required=False, allow_blank=True, default="")

    # Auth
    auth_mode = serializers.ChoiceField(
        choices=[
            ("typed_password", "Definir senha temporária"),
            ("random_password", "Gerar senha aleatória"),
            ("invite", "Enviar convite por email"),
        ]
    )
    password = serializers.CharField(required=False, allow_blank=True, default="", min_length=8)

    # WhatsApp opt-in
    setup_whatsapp = serializers.BooleanField(default=False)

    def to_internal_value(self, data):
        """Normalize legacy frontend enum values before DRF ChoiceField validation."""
        mutable = data.copy() if hasattr(data, "copy") else dict(data)
        contract_type = mutable.get("contract_type")
        employment_status = mutable.get("employment_status")
        if contract_type in CONTRACT_TYPE_ALIASES:
            mutable["contract_type"] = CONTRACT_TYPE_ALIASES[contract_type]
        if employment_status in EMPLOYMENT_STATUS_ALIASES:
            mutable["employment_status"] = EMPLOYMENT_STATUS_ALIASES[employment_status]
        return super().to_internal_value(mutable)

    # ── Field-level validators ───────────────────────────────────────────────

    def validate_email(self, value: str) -> str:
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("Já existe um usuário com este e-mail.")
        return value

    def validate_cpf(self, value: str) -> str:
        pattern = r"^\d{3}\.?\d{3}\.?\d{3}-?\d{2}$"
        if not re.match(pattern, value):
            raise serializers.ValidationError(
                "CPF inválido. Use o formato 000.000.000-00 ou 00000000000."
            )
        return value

    def validate_role(self, value: str) -> str:
        if not Role.objects.filter(name=value).exists():
            raise serializers.ValidationError(f"Role '{value}' não existe neste tenant.")
        return value

    # ── Cross-field validation ───────────────────────────────────────────────

    def validate(self, attrs: dict) -> dict:
        role = attrs.get("role", "")
        auth_mode = attrs.get("auth_mode", "")
        council_type = attrs.get("council_type", "").strip()
        council_number = attrs.get("council_number", "").strip()
        council_state = attrs.get("council_state", "").strip()
        password = attrs.get("password", "").strip()

        errors: dict = {}

        if role in CLINICAL_ROLES:
            if not council_type:
                errors["council_type"] = f"Este campo é obrigatório para a role '{role}'."
            if not council_number:
                errors["council_number"] = f"Este campo é obrigatório para a role '{role}'."
            if not council_state:
                errors["council_state"] = f"Este campo é obrigatório para a role '{role}'."
        else:
            # Non-clinical: strict rejection of stray council fields
            if council_type or council_number or council_state:
                errors["council_type"] = (
                    f"Campos de conselho profissional não são permitidos para a role '{role}'."
                )

        if auth_mode != "invite" and not password:
            errors["password"] = "Este campo é obrigatório quando auth_mode não é 'invite'."

        if errors:
            raise serializers.ValidationError(errors)

        return attrs
