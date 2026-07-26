"""AppConfig for the HR (Recursos Humanos) app — Sprint 18 / E-013."""

from django.apps import AppConfig


class HRConfig(AppConfig):
    name = "apps.hr"
    verbose_name = "Recursos Humanos"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        # Register F-15 employee-termination signals (issue #128).
        # M2-S2: wire the duty roster into emr appointment availability (read-side;
        # hr→emr only). emr exposes the hook registry and never imports hr.
        from apps.emr.services.scheduling import register_availability_hook

        from . import signals  # noqa: F401
        from .roster_integration import roster_availability_hook

        register_availability_hook(roster_availability_hook)
