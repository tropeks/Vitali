"""
AI Celery tasks — S-030
run_llm_task: async LLM call wrapper for non-realtime AI features (future use).
TUSS suggest uses synchronous calls directly (haiku P50 ~300ms, acceptable for form UX).
"""
import logging

from celery import shared_task

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
