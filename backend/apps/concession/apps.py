from django.apps import AppConfig


class ConcessionConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.concession"
    verbose_name = "Comodato & Suprimentos de Diagnóstico (tier: diagnostic_concession)"

    def ready(self):
        # C5-P2: register the imaging→consumption bridge (post_save on
        # imaging.DicomStudy). Imported here so models are loaded. Kept
        # concession-side so the imaging app stays independent.
        from . import imaging_bridge  # noqa: F401
