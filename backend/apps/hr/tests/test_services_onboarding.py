"""Sprint 18 / E-013 — EmployeeOnboardingService unit tests.

Covers:
- All auth modes (typed_password, random_password, invite→NotImplementedError)
- Clinical vs. non-clinical role paths
- Validation error + full rollback
- WhatsApp opt-in branches (module enabled/disabled, phone present/absent)
- AuditLog correlation_id chain integrity
- Atomic rollback on DB error

setup_staff_whatsapp_channel is mocked at this layer;
T13 covers the real fail-open integration test.
"""

from datetime import date
from unittest.mock import patch

import pytest
from django.db import IntegrityError
from django.test import override_settings
from rest_framework.exceptions import ValidationError

from apps.core.models import AuditLog, FeatureFlag, Role, User
from apps.emr.models import Professional
from apps.hr.models import Employee
from apps.hr.services import EmployeeOnboardingService
from apps.test_utils import TenantTestCase

# ── Helpers ──────────────────────────────────────────────────────────────────


def _admin_role():
    """Return (or create) the 'admin' Role in the current tenant schema."""
    role, _ = Role.objects.get_or_create(name="admin", defaults={"permissions": ["admin"]})
    return role


def _medico_role():
    """Return (or create) the 'medico' Role in the current tenant schema."""
    role, _ = Role.objects.get_or_create(
        name="medico", defaults={"permissions": ["emr.read", "emr.write"]}
    )
    return role


def _requesting_user():
    """Return a superuser that acts as the requester for AuditLog entries."""
    user, _ = User.objects.get_or_create(
        email="requester@example.com",
        defaults={"full_name": "System Requester", "is_staff": True},
    )
    return user


def _base_payload(**overrides):
    """Build a valid non-clinical onboarding payload."""
    payload = {
        "full_name": "Alice Teste",
        "email": "alice.teste@example.com",
        "cpf": "123.456.789-00",
        "phone": "",
        "role": "admin",
        "hire_date": date(2026, 5, 1),
        "contract_type": "clt",
        "employment_status": "active",
        "council_type": "",
        "council_number": "",
        "council_state": "",
        "specialty": "",
        "auth_mode": "typed_password",
        "password": "StrongPass1!",
        "setup_whatsapp": False,
    }
    payload.update(overrides)
    return payload


def _clinical_payload(**overrides):
    """Build a valid clinical (medico) onboarding payload."""
    payload = {
        "full_name": "Dr. Bruno Medico",
        "email": "bruno.medico@example.com",
        "cpf": "987.654.321-00",
        "phone": "",
        "role": "medico",
        "hire_date": date(2026, 5, 1),
        "contract_type": "pj",
        "employment_status": "active",
        "council_type": "CRM",
        "council_number": "123456",
        "council_state": "SP",
        "specialty": "Clínica Geral",
        "auth_mode": "random_password",
        "password": "RandomP@ss1",
        "setup_whatsapp": False,
    }
    payload.update(overrides)
    return payload


# ── Test class ───────────────────────────────────────────────────────────────


class TestEmployeeOnboardingService(TenantTestCase):
    """Unit tests for EmployeeOnboardingService."""

    def setUp(self):
        super().setUp()
        _admin_role()
        _medico_role()
        self.requester = _requesting_user()

    # ── T1: admin role, typed_password ────────────────────────────────────────

    def test_onboard_admin_role_typed_password(self):
        """Non-clinical mode=typed_password creates Employee + User, NO Professional."""
        service = EmployeeOnboardingService(requesting_user=self.requester)
        payload = _base_payload()

        employee = service.onboard(payload)

        # Employee created
        assert Employee.objects.filter(id=employee.id).exists()
        # User created with must_change_password=True
        user = User.objects.get(email="alice.teste@example.com")
        assert user.must_change_password is True
        # No Professional
        assert (
            not hasattr(user, "professional") or not Professional.objects.filter(user=user).exists()
        )
        # Exactly 2 AuditLog entries (employee_created + user_created)
        logs = AuditLog.objects.filter(new_data__correlation_id=service.correlation_id)
        assert logs.count() == 2
        actions = set(logs.values_list("action", flat=True))
        assert actions == {"employee_created", "user_created"}
        # All share same correlation_id
        for log in logs:
            assert log.new_data["correlation_id"] == service.correlation_id

    # ── T2: medico role, random_password ──────────────────────────────────────

    def test_onboard_clinical_role_random_password(self):
        """Clinical role=medico, mode=random_password creates Employee+User+Professional."""
        service = EmployeeOnboardingService(requesting_user=self.requester)
        payload = _clinical_payload()

        service.onboard(payload)

        user = User.objects.get(email="bruno.medico@example.com")
        assert user.must_change_password is True

        # Professional created
        professional = Professional.objects.get(user=user)
        assert professional.council_type == "CRM"
        assert professional.council_number == "123456"
        assert professional.council_state == "SP"

        # 3 AuditLog entries
        logs = AuditLog.objects.filter(new_data__correlation_id=service.correlation_id)
        assert logs.count() == 3
        actions = set(logs.values_list("action", flat=True))
        assert actions == {"employee_created", "user_created", "professional_created"}

        # Password must NOT be stored in plaintext
        assert user.password != payload["password"]  # should be hashed
        assert (
            user.password.startswith(("pbkdf2_sha256$", "argon2$", "bcrypt$"))
            or len(user.password) > 20
        )

    # ── T3: invite mode now wired (T6) ───────────────────────────────────────

    @patch("apps.core.services.email.EmailService.send_user_invitation")
    def test_onboard_invite_mode_creates_invitation(self, mock_send):
        """auth_mode=invite creates Employee + User + UserInvitation (T6 wired)."""
        from apps.core.models import UserInvitation

        service = EmployeeOnboardingService(requesting_user=self.requester)
        payload = _base_payload(
            auth_mode="invite",
            password="",
            email="invite.user@example.com",
        )

        employee = service.onboard(payload)

        # Employee + User created
        assert Employee.objects.filter(id=employee.id).exists()
        user = User.objects.get(email="invite.user@example.com")
        # Invite mode: must_change_password stays False (user sets via link)
        assert user.must_change_password is False
        # UserInvitation row created
        assert UserInvitation.objects.filter(user=user).exists()
        # Email sent once
        mock_send.assert_called_once()
        # AuditLog includes invitation entry
        from apps.core.models import AuditLog

        assert AuditLog.objects.filter(
            action="user_invitation_sent",
            new_data__correlation_id=service.correlation_id,
        ).exists()

    # ── T4: clinical role missing council fields → ValidationError + rollback ──

    def test_validation_clinical_missing_council_fields(self):
        """Clinical role with missing council_number raises ValidationError, no rows."""
        service = EmployeeOnboardingService(requesting_user=self.requester)
        payload = _clinical_payload(
            council_number="",
            email="clinical.missing@example.com",
        )

        with pytest.raises(ValidationError):
            service.onboard(payload)

        assert not User.objects.filter(email="clinical.missing@example.com").exists()
        assert not Employee.objects.filter(user__email="clinical.missing@example.com").exists()
        assert not Professional.objects.filter(user__email="clinical.missing@example.com").exists()

    # ── T5: non-clinical role with council fields → ValidationError ───────────

    def test_validation_non_clinical_with_council_fields(self):
        """Non-clinical role with stray council_type raises ValidationError."""
        service = EmployeeOnboardingService(requesting_user=self.requester)
        payload = _base_payload(
            council_type="CRM",
            email="nonclinical.council@example.com",
        )

        with pytest.raises(ValidationError) as exc_info:
            service.onboard(payload)

        detail = exc_info.value.detail
        assert "council_type" in detail
        assert not User.objects.filter(email="nonclinical.council@example.com").exists()

    # ── T6: WhatsApp module disabled → no Celery enqueue ─────────────────────

    @patch("apps.hr.services.setup_staff_whatsapp_channel")
    def test_whatsapp_module_disabled_no_queue(self, mock_task):
        """opt-in=True but no FeatureFlag(whatsapp) → no delay() call, no audit entry."""
        # Ensure no whatsapp flag
        FeatureFlag.objects.filter(tenant=self.__class__.tenant, module_key="whatsapp").delete()

        service = EmployeeOnboardingService(requesting_user=self.requester)
        payload = _base_payload(
            email="wa.disabled@example.com",
            phone="+5511999990001",
            setup_whatsapp=True,
        )

        service.onboard(payload)

        mock_task.delay.assert_not_called()
        # No whatsapp_setup_queued audit entry
        assert not AuditLog.objects.filter(
            action="whatsapp_setup_queued",
            new_data__correlation_id=service.correlation_id,
        ).exists()

    # ── T7: WhatsApp module enabled + phone → Celery enqueue ─────────────────

    @override_settings(CELERY_TASK_ALWAYS_EAGER=False)
    @patch("apps.hr.services.setup_staff_whatsapp_channel")
    def test_whatsapp_module_enabled_with_phone_queues_celery(self, mock_task):
        """FeatureFlag(whatsapp)+phone+opt-in → delay() called once, audit entry written."""
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key="whatsapp",
            defaults={"is_enabled": True},
        )

        service = EmployeeOnboardingService(requesting_user=self.requester)
        user_email = "wa.enabled@example.com"
        payload = _base_payload(
            email=user_email,
            phone="+5511999990002",
            setup_whatsapp=True,
        )

        # captureOnCommitCallbacks(execute=True) forces on_commit hooks to fire
        # inside the test's wrapping transaction — required for TestCase subclasses.
        with self.captureOnCommitCallbacks(execute=True):
            service.onboard(payload)

        user = User.objects.get(email=user_email)
        mock_task.delay.assert_called_once_with(str(user.id))

        assert AuditLog.objects.filter(
            action="whatsapp_setup_queued",
            new_data__correlation_id=service.correlation_id,
        ).exists()

    # ── T8: WhatsApp opt-in but no phone → no enqueue ─────────────────────────

    @patch("apps.hr.services.setup_staff_whatsapp_channel")
    def test_whatsapp_opt_in_but_no_phone_no_queue(self, mock_task):
        """opt-in=True, WhatsApp enabled, but no phone → no delay() call."""
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key="whatsapp",
            defaults={"is_enabled": True},
        )

        service = EmployeeOnboardingService(requesting_user=self.requester)
        payload = _base_payload(
            email="wa.nophone@example.com",
            phone="",  # no phone
            setup_whatsapp=True,
        )

        service.onboard(payload)

        mock_task.delay.assert_not_called()

    # ── T9: correlation_id is unique per service call ─────────────────────────

    def test_correlation_id_uuid_unique_per_call(self):
        """Each EmployeeOnboardingService instantiation gets its own correlation_id."""
        s1 = EmployeeOnboardingService(requesting_user=self.requester)
        s2 = EmployeeOnboardingService(requesting_user=self.requester)

        assert s1.correlation_id != s2.correlation_id
        # Both must be valid UUID4 strings (36 chars, 4 hyphens)
        import uuid

        uuid.UUID(s1.correlation_id, version=4)
        uuid.UUID(s2.correlation_id, version=4)

    # ── T10: atomic rollback on Employee creation failure ─────────────────────

    @patch("apps.hr.models.Employee.objects.create")
    def test_atomic_rollback_on_db_error(self, mock_create):
        """If Employee.objects.create raises IntegrityError, User must roll back too."""
        mock_create.side_effect = IntegrityError("duplicate key")

        service = EmployeeOnboardingService(requesting_user=self.requester)
        payload = _base_payload(email="rollback.test@example.com")

        with pytest.raises(IntegrityError):
            service.onboard(payload)

        # User created inside atomic block must have rolled back
        assert not User.objects.filter(email="rollback.test@example.com").exists()
