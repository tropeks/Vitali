"""Sprint 18 / E-013 — setup_staff_whatsapp_channel Celery task unit tests.

Covers decision 1B (fail-open cascade):
  1. Success path → AuditLog `whatsapp_channel_created` written + correlation_id propagated.
  2. No-phone (blank string) → task returns early, no AuditLog, no gateway call.
  3. No-phone (None / missing attr) → same skip behaviour.
  4. User doesn't exist → task logs + returns, no retry.
  5. Transient error → gateway is called and no `whatsapp_channel_created` log.
  6. Max retries exceeded → AuditLog `whatsapp_setup_failed` written + correlation_id propagated.
  7. correlation_id None → both AuditLog payloads carry None (backward compat).

Gateway is mocked at apps.hr.tasks.get_gateway for all tests.
T13 covers the real fail-open integration test with a live Celery worker.
"""

import uuid
from unittest.mock import MagicMock, patch

from celery.exceptions import MaxRetriesExceededError
from django.test import override_settings

from apps.core.models import AuditLog, User
from apps.hr.tasks import setup_staff_whatsapp_channel
from apps.test_utils import TenantTestCase

# ── Constants ─────────────────────────────────────────────────────────────────

_GW_PATCH = "apps.hr.tasks.get_gateway"
_USER_PATCH = "apps.hr.tasks.User"

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_user(email="task.test@example.com", full_name="Task Tester") -> User:
    """Create a plain User (no phone column) in the current tenant schema."""
    return User.objects.create_user(
        email=email,
        password="TestPass1!",
        full_name=full_name,
    )


def _mock_user(user: User, phone: str | None) -> MagicMock:
    """Build a MagicMock that quacks like User with .phone attached."""
    m = MagicMock(spec=User)
    m.id = user.id
    m.full_name = user.full_name
    m.phone = phone
    return m


# ── Test class ────────────────────────────────────────────────────────────────


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=False)
class TestSetupStaffWhatsappChannel(TenantTestCase):
    """Unit tests for the setup_staff_whatsapp_channel Celery task."""

    # ── 1. Success path ───────────────────────────────────────────────────────

    def test_success_writes_whatsapp_channel_created_audit_log(self):
        """
        When gateway.send_text succeeds, AuditLog `whatsapp_channel_created`
        must be written and gateway.send_text called once with correct args.
        correlation_id from the service must be propagated into the AuditLog.
        """
        user = _make_user(email="wa.success@example.com")
        correlation_id = "test-correlation-uuid-success"

        with patch(_GW_PATCH) as mock_get_gw:
            mock_gateway = MagicMock()
            mock_gateway.send_text.return_value = None
            mock_get_gw.return_value = mock_gateway

            with patch(_USER_PATCH) as MockUser:
                MockUser.objects.get.return_value = _mock_user(user, "+5511999990001")
                MockUser.DoesNotExist = User.DoesNotExist

                setup_staff_whatsapp_channel(str(user.id), correlation_id)

        mock_gateway.send_text.assert_called_once_with(
            "+5511999990001",
            f"Olá {user.full_name}! Sua conta no Vitali foi configurada. "
            f"Use este canal para comunicação interna da clínica.",
        )

        success_log = AuditLog.objects.get(
            action="whatsapp_channel_created",
            resource_type="user",
            resource_id=str(user.id),
        )
        assert success_log.new_data["correlation_id"] == correlation_id, (
            "correlation_id must be propagated into whatsapp_channel_created AuditLog"
        )

    # ── 2. No phone (blank) → skip ────────────────────────────────────────────

    def test_blank_phone_skips_without_gateway_call_or_audit_log(self):
        """
        phone="" → task returns immediately: no gateway call, no AuditLog.
        """
        user = _make_user(email="wa.nophone@example.com")

        with patch(_GW_PATCH) as mock_get_gw:
            mock_gateway = MagicMock()
            mock_get_gw.return_value = mock_gateway

            with patch(_USER_PATCH) as MockUser:
                MockUser.objects.get.return_value = _mock_user(user, "")
                MockUser.DoesNotExist = User.DoesNotExist

                setup_staff_whatsapp_channel(str(user.id))

            mock_get_gw.assert_not_called()
            mock_gateway.send_text.assert_not_called()

        assert not AuditLog.objects.filter(
            resource_type="user",
            resource_id=str(user.id),
        ).exists()

    # ── 3. No phone (None / missing attr) → skip ─────────────────────────────

    def test_none_phone_skips(self):
        """phone=None also skips gracefully — getattr fallback to None."""
        user = _make_user(email="wa.nonephone@example.com")

        with patch(_GW_PATCH) as mock_get_gw:
            mock_gateway = MagicMock()
            mock_get_gw.return_value = mock_gateway

            with patch(_USER_PATCH) as MockUser:
                MockUser.objects.get.return_value = _mock_user(user, None)
                MockUser.DoesNotExist = User.DoesNotExist

                setup_staff_whatsapp_channel(str(user.id))

            mock_get_gw.assert_not_called()

    # ── 4. User doesn't exist → log + return, no retry ───────────────────────

    def test_user_does_not_exist_returns_without_retry(self):
        """
        If user_id doesn't resolve to a User, task logs an error and returns.
        No retry should be triggered (this is not a transient error) and no
        AuditLog entry is created.
        """
        nonexistent_id = str(uuid.uuid4())

        with patch(_GW_PATCH) as mock_get_gw:
            mock_gateway = MagicMock()
            mock_get_gw.return_value = mock_gateway

            # Don't patch User — let the real ORM raise DoesNotExist
            setup_staff_whatsapp_channel(nonexistent_id)

            mock_get_gw.assert_not_called()
            mock_gateway.send_text.assert_not_called()

        assert not AuditLog.objects.filter(
            resource_type="user",
            resource_id=nonexistent_id,
        ).exists()

    # ── 5. Transient error → retry triggered, no success log ─────────────────

    def test_transient_gateway_error_triggers_retry(self):
        """
        When gateway.send_text raises a transient error, the task must call
        self.retry(). We verify this by patching self.retry and asserting it
        was called. The actual Celery retry machinery is bypassed to keep the
        test deterministic and avoid re-running the task inline.
        """
        user = _make_user(email="wa.retry@example.com")

        with patch(_GW_PATCH) as mock_get_gw:
            mock_gateway = MagicMock()
            mock_gateway.send_text.side_effect = ConnectionError("network down")
            mock_get_gw.return_value = mock_gateway

            with patch(_USER_PATCH) as MockUser:
                MockUser.objects.get.return_value = _mock_user(user, "+5511999990099")
                MockUser.DoesNotExist = User.DoesNotExist

                # Patch self.retry to raise MaxRetriesExceededError so the task
                # doesn't re-run inline and instead falls through to the failure path.
                # We just need to verify retry was called at least once.
                with patch.object(
                    setup_staff_whatsapp_channel,
                    "retry",
                    side_effect=MaxRetriesExceededError(),
                ) as mock_retry:
                    setup_staff_whatsapp_channel(str(user.id))

                # retry must have been called with the original exception
                mock_retry.assert_called_once()

        # Success log must NOT exist (failure path writes whatsapp_setup_failed)
        assert not AuditLog.objects.filter(
            action="whatsapp_channel_created",
            resource_type="user",
            resource_id=str(user.id),
        ).exists()

    # ── 6. Max retries exceeded → whatsapp_setup_failed AuditLog ─────────────

    def test_max_retries_writes_failed_audit_log(self):
        """
        When all retries are exhausted (persistent gateway failure),
        AuditLog `whatsapp_setup_failed` must be written with reason, error,
        AND correlation_id (decision 2A — full cascade tracing).

        We patch self.retry to immediately raise MaxRetriesExceededError,
        simulating the exhausted-retries state without running real Celery workers.
        """
        user = _make_user(email="wa.exhausted@example.com")
        correlation_id = "test-correlation-uuid-failure"

        with patch(_GW_PATCH) as mock_get_gw:
            mock_gateway = MagicMock()
            mock_gateway.send_text.side_effect = RuntimeError("gateway permanently broken")
            mock_get_gw.return_value = mock_gateway

            with patch(_USER_PATCH) as MockUser:
                MockUser.objects.get.return_value = _mock_user(user, "+5511999990077")
                MockUser.DoesNotExist = User.DoesNotExist

                with patch.object(
                    setup_staff_whatsapp_channel,
                    "retry",
                    side_effect=MaxRetriesExceededError(),
                ):
                    setup_staff_whatsapp_channel(str(user.id), correlation_id)

        # Failure audit log must exist
        assert AuditLog.objects.filter(
            action="whatsapp_setup_failed",
            resource_type="user",
            resource_id=str(user.id),
        ).exists()

        # Success audit log must NOT exist
        assert not AuditLog.objects.filter(
            action="whatsapp_channel_created",
            resource_type="user",
            resource_id=str(user.id),
        ).exists()

        failed_log = AuditLog.objects.get(
            action="whatsapp_setup_failed",
            resource_type="user",
            resource_id=str(user.id),
        )
        assert failed_log.new_data["reason"] == "max_retries_exceeded"
        assert "gateway permanently broken" in failed_log.new_data["error"]
        assert failed_log.new_data["correlation_id"] == correlation_id, (
            "correlation_id must be propagated into whatsapp_setup_failed AuditLog"
        )

    # ── 7. correlation_id None (backward-compat path) ────────────────────────

    def test_correlation_id_none_still_works(self):
        """
        The task should remain callable without a correlation_id (backward
        compatibility). When called as setup_staff_whatsapp_channel(user_id)
        the AuditLog's correlation_id field is simply None.
        """
        user = _make_user(email="wa.no_corr@example.com")

        with patch(_GW_PATCH) as mock_get_gw:
            mock_gateway = MagicMock()
            mock_gateway.send_text.return_value = None
            mock_get_gw.return_value = mock_gateway

            with patch(_USER_PATCH) as MockUser:
                MockUser.objects.get.return_value = _mock_user(user, "+5511999990055")
                MockUser.DoesNotExist = User.DoesNotExist

                setup_staff_whatsapp_channel(str(user.id))  # no correlation_id

        success_log = AuditLog.objects.get(
            action="whatsapp_channel_created",
            resource_type="user",
            resource_id=str(user.id),
        )
        # Field present, value None
        assert "correlation_id" in success_log.new_data
        assert success_log.new_data["correlation_id"] is None
