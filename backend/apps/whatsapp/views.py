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
from rest_framework import filters, status, viewsets
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
_RATE_LIMIT_WINDOW = 60  # seconds
_RATE_LIMIT_MAX = 20  # messages per window per contact


def _check_rate_limit(phone: str) -> bool:
    """Returns True if message is within rate limit, False if exceeded.

    Uses atomic cache.incr() to avoid TOCTOU race on concurrent requests.
    """
    cache_key = f"wa_rate:{phone}"
    try:
        count = cache.incr(cache_key)
    except ValueError:
        # Key did not exist — initialize then increment atomically
        cache.set(cache_key, 1, timeout=_RATE_LIMIT_WINDOW)
        count = 1
    return count <= _RATE_LIMIT_MAX


def _handle_waitlist_reply(phone: str, text: str) -> bool:
    """
    S-066: Intercept SIM/NÃO replies from patients with a pending waitlist notification.

    Returns True if the message was consumed by the waitlist handler (caller should
    not route to ConversationFSM). Returns False if the message is unrelated to a
    waitlist notification.

    SIM → book the offered slot, set entry.status = 'booked'
    NÃO → remove from waitlist (status = 'cancelled'), cascade to next entry
    """
    normalized = text.strip().upper()
    if normalized not in ("SIM", "NÃO", "NAO", "N"):
        return False

    try:
        from apps.emr.models import Patient, WaitlistEntry
        from apps.emr.tasks_waitlist import notify_next_waitlist_entry

        # Find the patient by phone number
        patient = Patient.objects.filter(phone=phone).first()
        if not patient:
            return False

        # Find their notified entry (there should be at most one at a time)
        with transaction.atomic():
            entry = (
                WaitlistEntry.objects.select_for_update()
                .filter(patient=patient, status="notified")
                .first()
            )
            if not entry:
                return False

            gateway = get_gateway()

            if normalized == "SIM":
                # Book the offered slot
                entry.status = "booked"
                entry.save(update_fields=["status"])
                try:
                    gateway.send_text(
                        phone,
                        "Ótimo! Sua consulta foi confirmada. Em breve você receberá a confirmação.",
                    )
                except Exception as exc:
                    logger.error("Failed to send waitlist confirmation to %s: %s", phone, exc)
                logger.info("WaitlistEntry %s booked by patient (SIM reply)", entry.id)
            else:
                # NÃO / NAO / N — cancel entry and cascade
                professional_id = str(entry.professional_id)
                offered_slot = entry.offered_slot or {}
                entry.status = "cancelled"
                entry.save(update_fields=["status"])
                try:
                    gateway.send_text(
                        phone,
                        "Tudo bem! Você foi removido(a) da fila de espera.",
                    )
                except Exception as exc:
                    logger.error("Failed to send waitlist opt-out to %s: %s", phone, exc)
                logger.info("WaitlistEntry %s cancelled by patient (NÃO reply)", entry.id)
                # Cascade to next entry outside the transaction
                transaction.on_commit(
                    lambda: notify_next_waitlist_entry.delay(professional_id, offered_slot)
                )

        return True

    except Exception as exc:
        logger.error("_handle_waitlist_reply error for %s: %s", phone, exc)
        return False


def _log_message(
    contact, direction: str, content: str, message_type: str = "text", appointment=None
):
    """Create a MessageLog entry with CPF masked."""
    import re

    preview = content[:200]
    # Mask CPF pattern NNN.NNN.NNN-NN or 11 digits — fully masked, no digit leaked
    preview = re.sub(r"\d{3}\.?\d{3}\.?\d{3}-?\d{2}", "***.***.***-**", preview)
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
                text = (
                    msg["message"]["listResponseMessage"]
                    .get("singleSelectReply", {})
                    .get("selectedRowId", "")
                )
                message_type = "list_reply"

            if not text:
                continue

            self._process_message(phone, text, message_type)

    def _process_message(self, phone: str, text: str, message_type: str):
        # S-066: Check for pending waitlist notification before routing to scheduling FSM.
        # SIM/NÃO responses must be disambiguated: if the patient has a 'notified'
        # WaitlistEntry, route to waitlist handler first.
        if _handle_waitlist_reply(phone, text):
            return

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
        # Always derive the webhook URL from the server's own host — never trust
        # a client-supplied URL (SSRF risk: arbitrary URL could redirect Evolution API
        # to internal network endpoints).
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
    pagination_class = MessageLogPagination
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
