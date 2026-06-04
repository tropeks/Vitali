from django.apps import AppConfig


class PharmacyConfig(AppConfig):
    name = "apps.pharmacy"
    verbose_name = "Pharmacy — Farmácia & Estoque"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        # Controlled-diversion wedge (C2): register the Dispensation post_save
        # receiver. Imported here (not at module level) so models are loaded.
        from . import signals  # noqa: F401
