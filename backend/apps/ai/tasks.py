"""
AI Celery tasks — S-030, S-034, S-038, S-069
run_llm_task: async LLM call wrapper for non-realtime AI features (future use).
TUSS suggest uses synchronous calls directly (haiku P50 ~300ms, acceptable for form UX).
cleanup_orphaned_glosa_predictions: removes GlosaPrediction rows not linked to a guide after 7 days.
check_tuss_staleness: daily check that TUSSSyncLog has a recent successful sync (S-038).
generate_soap_task: async SOAP generation from transcription (S-069).
"""

import logging

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=2, default_retry_delay=10)
def run_llm_task(self, prompt_template_id: int, context_json: dict) -> str | None:
    """
    Async LLM call wrapper for non-realtime use cases.
    Returns AIUsageLog.id (str) on success, None on failure.
    """
    from .gateway import ClaudeGateway, LLMGatewayError
    from .models import AIPromptTemplate, AIUsageLog

    try:
        template = AIPromptTemplate.objects.get(id=prompt_template_id, is_active=True)
    except AIPromptTemplate.DoesNotExist:
        logger.error("AIPromptTemplate %s not found", prompt_template_id)
        return None

    user_prompt = template.user_prompt_template.format(**context_json)

    gateway = ClaudeGateway()
    try:
        text, tokens_in, tokens_out = gateway.complete(
            system=template.system_prompt,
            user=user_prompt,
        )
        log = AIUsageLog.objects.create(
            prompt_template=template,
            event_type="llm_call",
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )
        return str(log.id)
    except LLMGatewayError as exc:
        logger.warning("run_llm_task failed: %s", exc)
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            return None


@shared_task(bind=True, max_retries=1, default_retry_delay=5)
def generate_soap_task(self, session_id: str) -> None:
    """
    S-069: Async SOAP generation from a transcription.
    Updates AIScribeSession.status to 'completed' or 'failed'.
    """
    from django.utils import timezone

    from .models import AIScribeSession
    from .services_scribe import generate_soap

    try:
        session = AIScribeSession.objects.get(pk=session_id)
    except AIScribeSession.DoesNotExist:
        logger.error("generate_soap_task: session %s not found", session_id)
        return

    try:
        soap = generate_soap(session.raw_transcription)
        # generate_soap is fail-open — check if all fields are empty (degraded result)
        if not any(soap.values()):
            session.status = AIScribeSession.Status.FAILED
            session.error_message = "AI service returned empty SOAP. Check ANTHROPIC_API_KEY."
        else:
            session.status = AIScribeSession.Status.COMPLETED
            session.soap_json = soap
        session.completed_at = timezone.now()
        session.save(update_fields=["status", "soap_json", "error_message", "completed_at"])
    except Exception as exc:
        logger.error("generate_soap_task: unexpected error — %s", exc, exc_info=True)
        try:
            session.status = AIScribeSession.Status.FAILED
            session.error_message = str(exc)[:500]
            session.completed_at = timezone.now()
            session.save(update_fields=["status", "error_message", "completed_at"])
        except Exception:
            pass
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            pass


@shared_task
def purge_old_scribe_sessions() -> dict:
    """
    S-071: Delete non-completed AIScribeSession rows older than
    SCRIBE_SESSION_RETENTION_DAYS days across all tenant schemas.

    Scheduled via Celery beat (daily at 03:00 UTC).
    """
    from datetime import timedelta

    from django.conf import settings
    from django_tenants.utils import get_tenant_model, tenant_context

    from .models import AIScribeSession

    retention_days = getattr(settings, "SCRIBE_SESSION_RETENTION_DAYS", 90)
    cutoff = timezone.now() - timedelta(days=retention_days)
    TenantModel = get_tenant_model()
    total_deleted = 0

    for tenant in TenantModel.objects.exclude(schema_name="public"):
        with tenant_context(tenant):
            deleted, _ = (
                AIScribeSession.objects.filter(
                    created_at__lt=cutoff,
                )
                .exclude(
                    status=AIScribeSession.Status.COMPLETED,
                )
                .delete()
            )
            total_deleted += deleted
            if deleted:
                logger.info(
                    "purge_old_scribe_sessions: deleted %d rows for tenant=%s",
                    deleted,
                    tenant.schema_name,
                )

    return {"deleted": total_deleted}


@shared_task
def cleanup_orphaned_glosa_predictions() -> dict:
    """
    Delete GlosaPrediction rows that were never linked to a guide (guide__isnull=True)
    and are older than 7 days. These are predictions the faturista abandoned before
    submitting the guide form.

    Scheduled via Celery beat (daily). Runs once per tenant schema because Celery beat
    tasks execute in the public schema by default — to purge all tenant schemas this
    task must be dispatched per-tenant or use django_tenants tenant_context.
    """
    from datetime import timedelta

    from django_tenants.utils import get_tenant_model, tenant_context

    from .models import GlosaPrediction

    cutoff = timezone.now() - timedelta(days=7)
    TenantModel = get_tenant_model()
    total_deleted = 0

    for tenant in TenantModel.objects.exclude(schema_name="public"):
        with tenant_context(tenant):
            deleted, _ = GlosaPrediction.objects.filter(
                guide__isnull=True,
                created_at__lt=cutoff,
            ).delete()
            total_deleted += deleted
            if deleted:
                logger.info(
                    "cleanup_orphaned_glosa_predictions: deleted %d rows for tenant=%s",
                    deleted,
                    tenant.schema_name,
                )

    return {"deleted": total_deleted}


@shared_task
def check_tuss_staleness() -> dict:
    """
    Daily check that TUSS data is fresh (S-038).
    Reads TUSSSyncLog from the public schema (using='default').
    Thresholds:
      - < 14 days old: no log
      - 14–29 days old: logs INFO (ageing)
      - ≥ 30 days old OR no successful sync: logs WARNING (stale)
    Fail-safe: any DB exception logs error and returns gracefully.
    Scheduled by data migration (apps.ai 0004).
    """

    try:
        from apps.core.models import TUSSSyncLog

        last = (
            TUSSSyncLog.objects.using("default")
            .filter(status="success")
            .order_by("-ran_at")
            .first()
        )

        if last is None:
            logger.warning(
                "apps.ai.tasks TUSS data is stale: no successful sync found. "
                "Run: python manage.py import_tuss"
            )
            return {"status": "stale", "last_sync": None, "age_days": None}

        age_days = max(0, (timezone.now() - last.ran_at).days)

        if age_days >= 30:
            logger.warning(
                "apps.ai.tasks TUSS data is stale: last_sync=%s, age_days=%d. "
                "Run: python manage.py import_tuss",
                last.ran_at.date(),
                age_days,
            )
            return {"status": "stale", "last_sync": str(last.ran_at.date()), "age_days": age_days}
        elif age_days >= 14:
            logger.info(
                "apps.ai.tasks TUSS data is ageing: age_days=%d",
                age_days,
            )
            return {"status": "ageing", "last_sync": str(last.ran_at.date()), "age_days": age_days}
        else:
            return {"status": "fresh", "last_sync": str(last.ran_at.date()), "age_days": age_days}

    except Exception as exc:
        logger.error("check_tuss_staleness: DB error — %s", exc)
        return {"status": "error", "error": str(exc)}
