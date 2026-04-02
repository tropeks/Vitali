"""
AI Celery tasks — S-030, S-034, S-038
run_llm_task: async LLM call wrapper for non-realtime AI features (future use).
TUSS suggest uses synchronous calls directly (haiku P50 ~300ms, acceptable for form UX).
cleanup_orphaned_glosa_predictions: removes GlosaPrediction rows not linked to a guide after 7 days.
check_tuss_staleness: daily check that TUSSSyncLog has a recent successful sync (S-038).
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
    import json
    from .models import AIPromptTemplate
    from .gateway import ClaudeGateway, LLMGatewayError
    from .models import AIUsageLog

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
            event_type='llm_call',
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
    from datetime import timedelta

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

        age_days = (timezone.now() - last.ran_at).days

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
