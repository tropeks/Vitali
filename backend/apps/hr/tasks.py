"""
HR Celery tasks — Sprint 18 / E-013 Workflow Intelligence v0.

setup_staff_whatsapp_channel:
  Sets up the WhatsApp staff channel for a newly-onboarded user.
  Enqueued via transaction.on_commit by EmployeeOnboardingService (decision 1B).
  Fail-open: persistent failure writes AuditLog `whatsapp_setup_failed` and
  logs to Sentry; the User/Employee/Professional rows are NEVER rolled back.

Cascade audit chain (decision 2A):
  Both success (`whatsapp_channel_created`) and failure (`whatsapp_setup_failed`)
  AuditLog entries carry the same correlation_id as `employee_created`,
  `user_created`, etc. — so a single UUID4 ties the full cascade together for
  tracing/debugging.

Attribution decision:
  AuditLog.user is intentionally None for this task. Celery tasks run outside
  any HTTP request and have no requesting-user context. The correlation_id
  links the task's audit back to the service-layer audits (which DO have
  requesting_user attribution), preserving the full audit trail.
"""

import logging

from celery import shared_task
from celery.exceptions import MaxRetriesExceededError

from apps.core.models import AuditLog, User
from apps.whatsapp.gateway import get_gateway

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def setup_staff_whatsapp_channel(self, user_id: str, correlation_id: str | None = None) -> None:
    """
    Set up WhatsApp staff channel for the given user_id.

    Args:
        user_id: UUID of the User to set up.
        correlation_id: UUID4 from EmployeeOnboardingService.correlation_id —
            included in both success and failure AuditLog entries so the cascade
            audit chain (decision 2A) stays intact across the service → task
            boundary. Defaults to None for backward compatibility / system-
            triggered enqueues that don't originate from the cascade.

    Decision 1B fail-open: any failure here is contained — the User/Employee/
    Professional rows from EmployeeOnboardingService NEVER get rolled back.

    Retry policy: 3 attempts with 60 s backoff. On final failure: write
    AuditLog `whatsapp_setup_failed` and log error via logger.error (picked up
    by Sentry if sentry-sdk is installed with logging integration).

    Skips silently (no retry) when:
      - User doesn't exist (not a transient error)
      - User has no phone number (nothing to set up)
    """
    # ── 1. Resolve user ───────────────────────────────────────────────────────
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        logger.error(
            "setup_staff_whatsapp_channel: user %s not found — skipping (no retry)",
            user_id,
        )
        return  # Not a transient error; don't retry.

    # ── 2. Guard: skip if no phone ────────────────────────────────────────────
    # User.phone is NOT a DB column in Sprint 18 — it's a transient attribute
    # attached by EmployeeOnboardingService._create_user(). After the commit the
    # attribute is gone, so getattr will always return None here. We guard
    # defensively so that if a future migration adds the column the task just
    # works without a code change.
    phone = getattr(user, "phone", None)
    if not phone or not str(phone).strip():
        logger.info(
            "setup_staff_whatsapp_channel: user %s has no phone — skipping",
            user_id,
        )
        return

    # ── 3. Send WhatsApp welcome message ──────────────────────────────────────
    try:
        gateway = get_gateway()
        welcome_text = (
            f"Olá {user.full_name}! Sua conta no Vitali foi configurada. "
            f"Use este canal para comunicação interna da clínica."
        )
        gateway.send_text(phone, welcome_text)

        AuditLog.objects.create(
            user=None,  # System action — see module docstring for attribution decision
            action="whatsapp_channel_created",
            resource_type="user",
            resource_id=str(user_id),
            new_data={"phone": phone, "correlation_id": correlation_id},
        )
        logger.info(
            "setup_staff_whatsapp_channel: success for user %s",
            user_id,
        )

    except Exception as exc:
        # Transient error — retry. When retries are exhausted, self.retry()
        # raises MaxRetriesExceededError; we catch that to write the failure log.
        try:
            raise self.retry(exc=exc) from exc
        except MaxRetriesExceededError:
            AuditLog.objects.create(
                user=None,
                action="whatsapp_setup_failed",
                resource_type="user",
                resource_id=str(user_id),
                new_data={
                    "reason": "max_retries_exceeded",
                    "error": str(exc)[:200],
                    "correlation_id": correlation_id,
                },
            )
            logger.error(
                "setup_staff_whatsapp_channel: persistent failure for user %s after retries",
                user_id,
                exc_info=True,
            )
