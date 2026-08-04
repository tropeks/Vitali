from django.apps import AppConfig


class BillingConfig(AppConfig):
    name = "apps.billing"
    verbose_name = "Billing — Faturamento TISS/TUSS"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        # Registra o receiver que acumula as diárias na alta (B5). O import é
        # que executa o @receiver, e precisa acontecer aqui, depois de os models
        # estarem carregados. Mesmo padrão do apps.emr.
        from apps.billing.services import inpatient_signals  # noqa: F401
