from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    HealthView,
    MessageLogViewSet,
    SetupWebhookView,
    WebhookView,
    WhatsAppContactViewSet,
)

router = DefaultRouter()
router.register(r"whatsapp/contacts", WhatsAppContactViewSet, basename="whatsapp-contact")
router.register(r"whatsapp/message-logs", MessageLogViewSet, basename="whatsapp-messagelog")

urlpatterns = [
    path("whatsapp/webhook/", WebhookView.as_view(), name="whatsapp-webhook"),
    path("whatsapp/health/", HealthView.as_view(), name="whatsapp-health"),
    path("whatsapp/setup-webhook/", SetupWebhookView.as_view(), name="whatsapp-setup-webhook"),
    path("", include(router.urls)),
]
