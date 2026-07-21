from django.apps import AppConfig


class WhatsappConfig(AppConfig):
    name = "apps.whatsapp"
    verbose_name = "WhatsApp — Patient Engagement"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        # Register this channel's notifier into the apps.core port so other
        # domains (e.g. apps.patient_portal invite delivery) can message a
        # patient over WhatsApp without importing apps.whatsapp directly
        # (P1-01 domain-independence contract).
        from apps.core.whatsapp_bridge import register_patient_whatsapp_notifier
        from apps.whatsapp.notifier import PatientWhatsAppNotifierProvider

        register_patient_whatsapp_notifier(PatientWhatsAppNotifierProvider())
