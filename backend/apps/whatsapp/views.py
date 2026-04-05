"""
WhatsApp views — S-032, S-033, S-034, S-035

WebhookView:      POST /api/v1/whatsapp/webhook/
  - HMAC-SHA256 validated, always returns 200 (Evolution API retries on non-2xx)
  - Dispatches to ConversationFSM
  - Per-contact rate limiting (20 msg/min via Django cache)

HealthView:       GET /api/v1/whatsapp/health/
  - Returns Evolution API connection state

WhatsAppContactViewSet: /api/v1/whatsapp/contacts/
MessageLogViewSet:      /api/v1/whatsapp/message-logs/
"""
import json
import logging

from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from rest_framework import filters, status, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import ModuleRequiredPermission

from .fsm import ConversationFSM
from .gateway import get_gateway, verify_webhook_signature
from .models import ConversationSession, MessageLog, WhatsAppContact
from .serializers import MessageLogSerializer, WhatsAppContactSerializer

logger = logging.getLogger(__name__)

_WHATSAPP_MODULE = ModuleRequiredPermission("whatsapp")
_RATE_LIMIT_WINDOW = 60   # seconds
_RATE_LIMIT_MAX = 20      # messages per window per contact


def _check_rate_limit(phone: str) -> bool:
    """Returns True if message is within rate limit, False if exceeded."""
    cache_key = f"wa_rate:{phone}"
    count = cache.get(cache_key, 0)
    if count >= _RATE_LIMIT_MAX:
        return False
    cache.set(cache_key, count + 1, timeout=_RATE_LIMIT_WINDOW)
    return True


def _log_message(contact, direction: str, content: str, message_type: str = "text", appointment=None):
    """Create a MessageLog entry with CPF masked."""
    import re
    preview = content[:200]
    # Mask CPF pattern NNN.NNN.NNN-NN or 11 digits
    preview = re.sub(r"\d{3}\.?\d{3}\.?\d{3}-?\d{2}", lambda m: "***-***-**" + m.group()[-1], preview)
    try:
        MessageLog.objects.create(
            contact=contact,
            direction=direction,
            content_preview=preview,
            message_type=message_type,
            appointment=appointment,
        )
    except Exception as exc:
        logger.warning("Failed to write MessageLog: %s", exc)


class WebhookView(APIView):
    """
    POST /api/v1/whatsapp/webhook/

    Exempt from JWT auth and module gating — Evolution API posts here directly.
    Security: HMAC-SHA256 signature validation.
    Always returns HTTP 200 — Evolution API retries on any non-2xx.
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        try:
            raw_body = request.body
            signature = request.headers.get("X-Hub-Signature-256", "")
            if not verify_webhook_signature(raw_body, signature):
                logger.warning("Webhook signature mismatch — dropping payload")
                return Response({"status": "ok"}, status=200)

            payload = json.loads(raw_body)
            self._dispatch(payload)
        except Exception as exc:
            logger.critical("Webhook dispatch failed: %s", exc, exc_info=True)

        return Response({"status": "ok"}, status=200)

    def _dispatch(self, payload: dict):
        event = payload.get("event", "")
        if event == "messages.upsert":
            self._handle_message(payload)
        elif event == "connection.update":
            logger.info("WhatsApp connection update: %s", payload.get("data", {}).get("state"))

    def _handle_message(self, payload: dict):
        data = payload.get("data", {})
        messages = data.get("messages", [])
        for msg in messages:
            # Skip outbound (fromMe) messages
            if msg.get("key", {}).get("fromMe"):
                continue
            phone = msg.get("key", {}).get("remoteJid", "").split("@")[0]
            if not phone:
                continue
            if not _check_rate_limit(phone):
                logger.warning("Rate limit exceeded for %s — dropping message", phone)
                continue

            message_type = "text"
            text = ""
            if "conversation" in msg.get("message", {}):
                text = msg["message"]["conversation"]
            elif "buttonsResponseMessage" in msg.get("message", {}):
                text = msg["message"]["buttonsResponseMessage"].get("selectedButtonId", "")
                message_type = "button_reply"
            elif "listResponseMessage" in msg.get("message", {}):
                text = msg["message"]["listResponseMessage"].get("singleSelectReply", {}).get("selectedRowId", "")
                message_type = "list_reply"

            if not text:
                continue

            self._process_message(phone, text, message_type)

    def _process_message(self, phone: str, text: str, message_type: str):
        from datetime import timedelta

        with transaction.atomic():
            contact, _ = WhatsAppContact.objects.get_or_create(phone=phone)
            # Lock session row to prevent concurrent double-tap corruption
            session, _ = ConversationSession.get_or_create_for_contact(contact)
            session = ConversationSession.objects.select_for_update().get(pk=session.pk)

            _log_message(contact, "inbound", text, message_type)

            gateway = get_gateway()
            fsm = ConversationFSM(session, gateway)
            outbound_messages = fsm.process(text, message_type)

        # Send outbound messages outside the transaction (network I/O)
        for msg_text in outbound_messages:
            try:
                if contact.opt_in:
                    gateway.send_text(phone, msg_text)
                elif session.state in ("PENDING_OPTIN", "IDLE"):
                    # Opt-in prompt goes out before formal opt-in
                    gateway.send_text(phone, msg_text)
                _log_message(contact, "outbound", msg_text)
            except Exception as exc:
                logger.error("Failed to send outbound message to %s: %s", phone, exc)


class HealthView(APIView):
    """GET /api/v1/whatsapp/health/ — returns Evolution API connection state."""
    permission_classes = [IsAuthenticated, _WHATSAPP_MODULE]

    def get(self, request):
        try:
            result = get_gateway().health_check()
            return Response({"status": "ok", "evolution_api": result})
        except Exception as exc:
            return Response(
                {"status": "error", "detail": str(exc)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )


class SetupWebhookView(APIView):
    """
    POST /api/v1/whatsapp/setup-webhook/
    Called by the frontend QR page after QR scan — registers the tenant-specific
    webhook URL with Evolution API programmatically.
    """
    permission_classes = [IsAuthenticated, _WHATSAPP_MODULE]

    def post(self, request):
        webhook_url = request.data.get("webhook_url")
        if not webhook_url:
            # Auto-build from request host
            host = request.get_host()
            webhook_url = f"https://{host}/api/v1/whatsapp/webhook/"
        try:
            gateway = get_gateway()
            gateway.register_webhook(webhook_url)
            return Response({"status": "ok", "webhook_url": webhook_url})
        except Exception as exc:
            logger.exception("Webhook registration failed")
            return Response({"detail": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class MessageLogPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 100


class WhatsAppContactViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = WhatsAppContactSerializer
    permission_classes = [IsAuthenticated, _WHATSAPP_MODULE]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["phone", "patient__full_name"]
    ordering = ["-created_at"]

    def get_queryset(self):
        return WhatsAppContact.objects.select_related("patient")


class MessageLogViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = MessageLogSerializer
    permission_classes = [IsAuthenticated, _WHATSAPP_MODULE]
    pagination_class = MessageLogPagination
    filter_backends = [filters.OrderingFilter]
    ordering = ["-created_at"]

    def get_queryset(self):
        qs = MessageLog.objects.select_related("contact", "contact__patient", "appointment")
        contact_id = self.request.query_params.get("contact")
        if contact_id:
            qs = qs.filter(contact_id=contact_id)
        phone = self.request.query_params.get("phone")
        if phone:
            qs = qs.filter(contact__phone=phone)
        return qs
