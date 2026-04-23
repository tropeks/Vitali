import logging

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class AiConfig(AppConfig):
    name = "apps.ai"
    verbose_name = "AI — LLM Gateway & TUSS Coding"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from django.conf import settings

        if getattr(settings, "FEATURE_AI_SCRIBE", False) and not getattr(
            settings, "OPENAI_API_KEY", ""
        ):
            logger.warning(
                "FEATURE_AI_SCRIBE=True but OPENAI_API_KEY is empty. "
                "The Whisper fallback path will fail at runtime. "
                "Either set OPENAI_API_KEY in .env or set FEATURE_AI_SCRIBE=False."
            )

        if getattr(settings, "FEATURE_AI_TUSS", False) and not getattr(
            settings, "ANTHROPIC_API_KEY", ""
        ):
            logger.warning(
                "FEATURE_AI_TUSS=True but ANTHROPIC_API_KEY is empty. "
                "TUSS code suggestion will fail at runtime. "
                "Either set ANTHROPIC_API_KEY in .env or set FEATURE_AI_TUSS=False."
            )
