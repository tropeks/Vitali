"""
AppConfig for the EMR (Electronic Medical Record) app.

Signal wiring is done in ready() to ensure models are fully loaded
before signal receivers are registered. Importing signals at module
level (outside ready()) can cause AppRegistryNotReady errors.
"""

from django.apps import AppConfig


class EmrConfig(AppConfig):
    name = "apps.emr"
    verbose_name = "EMR — Prontuário Eletrônico"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        # Wire prescription safety signal (S-063).
        # This import registers the @receiver decorators in signals.py.
        # Must be done here, after all models are loaded.
        from . import signals  # noqa: F401
