from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "apps.core"
    verbose_name = "Core — Multi-tenancy & Auth"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        import apps.core.signals  # noqa: F401
        import apps.billing.services.tasks  # noqa: F401 — connects appointment_paid signal
