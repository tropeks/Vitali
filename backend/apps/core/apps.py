from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "apps.core"
    verbose_name = "Core — Multi-tenancy & Auth"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        import apps.core.signals  # noqa: F401
