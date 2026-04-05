"""
WhatsApp Gateway — abstract interface + Evolution API implementation.

WhatsAppGateway defines the contract. EvolutionAPIGateway talks to the
self-hosted Evolution API container via REST.

Key rules:
- All requests have timeout=10s — no hanging webhook threads.
- send_if_opted_in() checks opt_in before sending. Raises OptOutError if opted out.
- All methods log request+response at DEBUG level (not INFO — message content is PII).
- Never raise on Evolution API errors in the send path — log + swallow so webhook
  processing continues. Webhook must always return 200.
"""
import hashlib
import hmac
import logging
from abc import ABC, abstractmethod

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class OptOutError(Exception):
    """Raised when a send is attempted for a contact who has opted out."""


class EvolutionAPIError(Exception):
    """Raised when Evolution API returns a non-2xx response (health checks only)."""


class WhatsAppGateway(ABC):
    @abstractmethod
    def send_text(self, to: str, text: str) -> None: ...

    @abstractmethod
    def send_button_menu(self, to: str, body: str, buttons: list[dict]) -> None: ...

    @abstractmethod
    def send_template(self, to: str, template_name: str, params: list[str]) -> None: ...

    @abstractmethod
    def health_check(self) -> dict: ...

    def send_if_opted_in(self, contact, text: str) -> None:
        """Send a text message only if contact.opt_in is True."""
        if not contact.opt_in:
            raise OptOutError(f"Contact {contact.phone} has not opted in.")
        self.send_text(contact.phone, text)

    def send_buttons_if_opted_in(self, contact, body: str, buttons: list[dict]) -> None:
        if not contact.opt_in:
            raise OptOutError(f"Contact {contact.phone} has not opted in.")
        self.send_button_menu(contact.phone, body, buttons)


class EvolutionAPIGateway(WhatsAppGateway):
    def __init__(self):
        self._base_url = getattr(settings, "WHATSAPP_EVOLUTION_URL", "http://evolution-api:8080").rstrip("/")
        self._api_key = getattr(settings, "WHATSAPP_EVOLUTION_API_KEY", "")
        self._instance = getattr(settings, "WHATSAPP_INSTANCE_NAME", "vitali")
        self._headers = {
            "apikey": self._api_key,
            "Content-Type": "application/json",
        }

    def _post(self, path: str, payload: dict) -> dict:
        url = f"{self._base_url}{path}"
        logger.debug("Evolution API POST %s payload=%r", path, payload)
        try:
            resp = requests.post(url, json=payload, headers=self._headers, timeout=10)
            logger.debug("Evolution API response status=%d body=%r", resp.status_code, resp.text[:200])
            resp.raise_for_status()
            return resp.json()
        except requests.Timeout:
            logger.error("Evolution API timeout on %s", path)
            return {}
        except requests.RequestException as exc:
            logger.error("Evolution API error on %s: %s", path, exc)
            return {}

    def send_text(self, to: str, text: str) -> None:
        self._post(
            f"/message/sendText/{self._instance}",
            {"number": to, "text": text},
        )

    def send_button_menu(self, to: str, body: str, buttons: list[dict]) -> None:
        """
        buttons = [{"displayText": "Label", "id": "btn_id"}, ...]
        Max 3 buttons per Evolution API spec.
        """
        self._post(
            f"/message/sendButtons/{self._instance}",
            {
                "number": to,
                "title": "",
                "description": body,
                "buttons": buttons,
            },
        )

    def send_template(self, to: str, template_name: str, params: list[str]) -> None:
        self._post(
            f"/message/sendTemplate/{self._instance}",
            {"number": to, "template": {"name": template_name, "components": [
                {"type": "body", "parameters": [{"type": "text", "text": p} for p in params]}
            ]}},
        )

    def health_check(self) -> dict:
        url = f"{self._base_url}/instance/connectionState/{self._instance}"
        try:
            resp = requests.get(url, headers=self._headers, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            raise EvolutionAPIError(str(exc)) from exc

    def register_webhook(self, webhook_url: str) -> None:
        """Called during QR setup to register the tenant-specific webhook URL."""
        self._post(
            f"/webhook/set/{self._instance}",
            {
                "url": webhook_url,
                "webhook_by_events": False,
                "webhook_base64": False,
                "events": ["MESSAGES_UPSERT", "CONNECTION_UPDATE"],
            },
        )


def verify_webhook_signature(payload_bytes: bytes, signature_header: str) -> bool:
    """
    Verify Evolution API HMAC-SHA256 webhook signature.
    Expected header format: "sha256=<hex_digest>"
    """
    secret = getattr(settings, "WHATSAPP_WEBHOOK_SECRET", "")
    if not secret:
        logger.warning("WHATSAPP_WEBHOOK_SECRET not set — rejecting webhook (fail-closed)")
        return False
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()
    provided = signature_header[len("sha256="):]
    return hmac.compare_digest(expected, provided)


def get_gateway() -> WhatsAppGateway:
    """Return the configured gateway instance. Centralised to allow test mocking."""
    return EvolutionAPIGateway()
