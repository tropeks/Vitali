from django.apps import AppConfig


class TriageConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.triage"
    verbose_name = "Triagem Inteligente"

    def ready(self):
        # Register this domain's provider into the apps.core port so
        # conversation channels (apps.whatsapp) can drive the TriageSession
        # FSM without importing apps.triage directly (P1-01 contract).
        from apps.core.triage_bridge import register_triage_provider
        from apps.triage.provider import TriageSessionProvider

        register_triage_provider(TriageSessionProvider())
