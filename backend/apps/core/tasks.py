"""
Core Celery tasks — Sprint 19 / S-081 DPA-signed cascade.

send_dpa_signed_admin_email:
  Notifies the tenant admin that the DPA was signed and AI features are live.
  Enqueued via transaction.on_commit by DPASigningService (decision 1B).
  Fail-open: persistent failure writes AuditLog `dpa_admin_email_failed` and
  logs an error; the DPA + FeatureFlag rows are NEVER rolled back.

Cascade audit chain (decision 2A):
  Both success (`dpa_admin_email_sent`) and failure (`dpa_admin_email_failed`)
  AuditLog entries carry the same correlation_id as `dpa_signed`,
  `ai_feature_flag_enabled`, etc. — so a single UUID4 ties the full cascade
  together for tracing/debugging.

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

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_dpa_signed_admin_email(
    self, user_id: str, flags_enabled: list, correlation_id: str | None = None
) -> None:
    """
    Notifies the tenant admin that DPA was signed and AI features are live.

    Args:
        user_id: UUID of the User who signed the DPA (the admin).
        flags_enabled: list of module_key strings that were enabled.
        correlation_id: UUID4 from DPASigningService.correlation_id — included
            in both success and failure AuditLog entries so the cascade audit
            chain (decision 2A) stays intact across the service → task boundary.

    Decision 1B fail-open: any failure here is contained — the AIDPAStatus and
    FeatureFlag rows from DPASigningService NEVER get rolled back.

    Retry policy: 3 attempts with 60 s backoff. On final failure: write
    AuditLog `dpa_admin_email_failed` and log error (picked up by Sentry if
    sentry-sdk is installed with logging integration).

    Skips silently (no retry) when user doesn't exist (not a transient error).
    """
    # ── 1. Resolve user ───────────────────────────────────────────────────────
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        logger.error(
            "send_dpa_signed_admin_email: user %s not found — skipping (no retry)",
            user_id,
        )
        return  # Not a transient error; don't retry.

    # ── 2. Send notification email ────────────────────────────────────────────
    try:
        from apps.core.services.email import EmailService

        EmailService.send_dpa_signed_notification(user=user, flags_enabled=flags_enabled)

        AuditLog.objects.create(
            user=None,  # System action — see module docstring for attribution decision
            action="dpa_admin_email_sent",
            resource_type="user",
            resource_id=str(user_id),
            new_data={"flags_enabled": flags_enabled, "correlation_id": correlation_id},
        )
        logger.info(
            "send_dpa_signed_admin_email: success for user %s",
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
                action="dpa_admin_email_failed",
                resource_type="user",
                resource_id=str(user_id),
                new_data={
                    "reason": "max_retries_exceeded",
                    "error": str(exc)[:200],
                    "flags_enabled": flags_enabled,
                    "correlation_id": correlation_id,
                },
            )
            logger.error(
                "send_dpa_signed_admin_email: persistent failure for user %s after retries",
                user_id,
                exc_info=True,
            )
