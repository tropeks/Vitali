"""HR onboarding service — Sprint 18 / E-013 Workflow Intelligence v0.

Locked architecture decisions (from /plan-eng-review v2):
  1A — Service-layer orchestrator, NOT Django signals (FK ordering).
  1B — Atomic DB block + transaction.on_commit fail-open for WhatsApp.
  2A — AuditLog correlation_id in new_data JSON for full cascade tracing.

Usage:
    service = EmployeeOnboardingService(requesting_user=request.user)
    employee = service.onboard(serializer.validated_data)
"""

import logging
from uuid import uuid4

from django.db import connection, transaction
from rest_framework.exceptions import ValidationError

from apps.core.models import AuditLog, Role, User
from apps.hr.models import Employee
from apps.hr.tasks import setup_staff_whatsapp_channel

logger = logging.getLogger(__name__)

# Clinical roles that require council registration (CFM, COREN, CRF, etc.)
CLINICAL_ROLES = {"medico", "enfermeiro", "farmaceutico", "dentista"}


class EmployeeOnboardingService:
    """
    Orchestrates Employee + User + (optional) Professional creation in one
    atomic transaction. WhatsApp setup is queued post-commit (fail-open).

    Locked decision 1A: explicit service-layer, NOT signals.
    Locked decision 1B: transaction.on_commit for Celery — DB never rolls back
        due to WhatsApp failure.
    Locked decision 2A: all AuditLog entries share correlation_id.
    """

    def __init__(self, requesting_user: User) -> None:
        self.requesting_user = requesting_user
        self.correlation_id = str(uuid4())

    def onboard(self, payload: dict) -> Employee:
        """
        Main entry point. Creates Employee, User, (optional) Professional
        inside a single atomic transaction. WhatsApp task enqueued on_commit.

        Args:
            payload: validated data from EmployeeOnboardingSerializer

        Returns:
            The created Employee instance (user loaded via select_related).

        Raises:
            ValidationError: if payload fails business-rule validation.
            NotImplementedError: if auth_mode == 'invite' (T6 wires this).
        """
        self._validate(payload)

        with transaction.atomic():
            user = self._create_user(payload)
            employee = Employee.objects.create(
                user=user,
                hire_date=payload["hire_date"],
                employment_status=payload.get("employment_status", "active"),
                contract_type=payload["contract_type"],
            )
            self._audit(
                "employee_created",
                "employee",
                employee.id,
                new_data={
                    "hire_date": str(employee.hire_date),
                    "contract_type": employee.contract_type,
                    "employment_status": employee.employment_status,
                },
            )
            self._audit(
                "user_created",
                "user",
                user.id,
                new_data={
                    "email": user.email,
                    "auth_mode": payload["auth_mode"],
                },
            )

            if payload["role"] in CLINICAL_ROLES:
                from apps.emr.models import Professional

                professional = Professional.objects.create(
                    user=user,
                    council_type=payload["council_type"],
                    council_number=payload["council_number"],
                    council_state=payload["council_state"],
                    specialty=payload.get("specialty", ""),
                )
                self._audit(
                    "professional_created",
                    "professional",
                    professional.id,
                    new_data={
                        "council_type": professional.council_type,
                        "council_number": professional.council_number,
                        "council_state": professional.council_state,
                    },
                )

            phone_value = getattr(user, "phone", "") or ""
            if payload.get("setup_whatsapp") and self._whatsapp_enabled() and phone_value.strip():
                user_id = str(user.id)
                transaction.on_commit(lambda: setup_staff_whatsapp_channel.delay(user_id))
                self._audit("whatsapp_setup_queued", "user", user.id)

        return employee

    # ── Private helpers ──────────────────────────────────────────────────────

    def _validate(self, payload: dict) -> None:
        """
        Business-rule validation (mirrors serializer cross-field checks).
        Called OUTSIDE the atomic block so no partial rows are created if
        validation raises.

        Raises ValidationError for:
          - Clinical role missing council_type / council_number / council_state
          - Non-clinical role with council fields set
        """
        role = payload.get("role", "")
        council_type = payload.get("council_type", "").strip()
        council_number = payload.get("council_number", "").strip()
        council_state = payload.get("council_state", "").strip()

        if role in CLINICAL_ROLES:
            missing = []
            if not council_type:
                missing.append("council_type")
            if not council_number:
                missing.append("council_number")
            if not council_state:
                missing.append("council_state")
            if missing:
                raise ValidationError(
                    {field: f"Este campo é obrigatório para a role '{role}'." for field in missing}
                )
        else:
            # Non-clinical role: reject stray council fields (strict mode)
            if council_type or council_number or council_state:
                raise ValidationError(
                    {
                        "council_type": (
                            f"Campos de conselho profissional não são permitidos "
                            f"para a role '{role}'."
                        )
                    }
                )

    def _create_user(self, payload: dict) -> User:
        """
        Create the User row.

        - typed_password / random_password: sets must_change_password=True.
        - invite: raises NotImplementedError — T6 wires UserInvitation creation.
        """
        auth_mode = payload["auth_mode"]

        if auth_mode == "invite":
            self._create_invitation(payload)  # raises NotImplementedError until T6

        role_obj: Role | None = None
        role_name = payload.get("role", "")
        if role_name:
            role_obj = Role.objects.filter(name=role_name).first()

        must_change = auth_mode in ("typed_password", "random_password")

        user = User.objects.create_user(
            email=payload["email"],
            password=payload.get("password") or None,
            full_name=payload["full_name"],
            cpf=payload.get("cpf", ""),
            role=role_obj,
            must_change_password=must_change,
        )
        # Attach phone as a Python attribute for WhatsApp gate check.
        # No phone column on User — T7 / a future migration may persist it.
        user.phone = payload.get("phone", "")  # type: ignore[attr-defined,unused-ignore]
        return user

    def _create_invitation(self, payload: dict) -> None:
        """
        Stub — T6 wires UserInvitation token generation + email send.
        Raises NotImplementedError so callers know the invite path is pending.
        """
        raise NotImplementedError(
            "T6 wires this — invite mode requires UserInvitation creation + email send"
        )

    def _audit(
        self,
        action: str,
        resource_type: str,
        resource_id: object,
        new_data: dict | None = None,
    ) -> None:
        """Write an AuditLog entry tagged with this service invocation's correlation_id."""
        data = dict(new_data) if new_data else {}
        data["correlation_id"] = self.correlation_id
        AuditLog.objects.create(
            user=self.requesting_user,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id),
            new_data=data,
        )

    def _whatsapp_enabled(self) -> bool:
        """Check if the current tenant has the WhatsApp module enabled via FeatureFlag."""
        try:
            from apps.core.models import FeatureFlag

            # django-tenants attaches `tenant` to the connection wrapper at runtime;
            # mypy's Django stubs don't know about the subclass.
            tenant = connection.tenant  # type: ignore[attr-defined]
            return FeatureFlag.objects.filter(
                tenant=tenant, module_key="whatsapp", is_enabled=True
            ).exists()
        except Exception:
            logger.warning(
                "Could not determine WhatsApp feature flag; defaulting to disabled.",
                exc_info=True,
            )
            return False
