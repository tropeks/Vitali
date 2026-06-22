"""AppConfig for the HR (Recursos Humanos) app — Sprint 18 / E-013."""

from django.apps import AppConfig


class HRConfig(AppConfig):
    name = "apps.hr"
    verbose_name = "Recursos Humanos"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        # Register F-15 employee-termination signals (issue #128).
        from . import signals  # noqa: F401
