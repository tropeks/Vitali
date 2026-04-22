"""
S-055: Asaas PIX payment gateway service.

Handles PIX charge creation, cancellation, and status checks via the Asaas API.
Asaas is a Brazilian payment gateway with PIX-first API.

LGPD compliance:
- We never send raw CPF to Asaas. Instead we use Asaas Customer objects.
- get_or_create_customer() links Patient.id → Asaas customer_id.
- The mapping is stored in PIXCharge.asaas_customer_id.

Error handling:
- All HTTP calls have a 5s timeout.
- Non-2xx responses raise AsaasAPIError with structured message.
- Callers receive {"error": "payment_gateway_unavailable", "detail": "...", "action": "..."}

Environment variables:
  ASAAS_API_KEY: required — Asaas API key (starts with $aact_ for sandbox, $act_ for prod)
  ASAAS_WEBHOOK_TOKEN: required — shared token for webhook validation
  ASAAS_ENVIRONMENT: optional — "sandbox" (default) or "production"
  PIX_CHARGE_EXPIRY_MINUTES: optional — charge TTL in minutes (default 30)
"""

import logging
from decimal import Decimal

import requests
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

logger = logging.getLogger(__name__)

_SANDBOX_URL = "https://sandbox.asaas.com/api/v3"
_PRODUCTION_URL = "https://api.asaas.com/v3"
_TIMEOUT = 5  # seconds


class AsaasAPIError(Exception):
    """Raised when Asaas returns a non-2xx response or a network error."""

    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message)
        self.status_code = status_code

    def to_response_dict(self) -> dict:
        return {
            "error": "payment_gateway_unavailable",
            "detail": str(self),
            "action": "Tente novamente em 60s ou entre em contato com o suporte.",
        }


class AsaasService:
    """Client for the Asaas payment API. Instantiate per-request (stateless)."""

    def __init__(self):
        api_key = getattr(settings, "ASAAS_API_KEY", None)
        if not api_key:
            raise ImproperlyConfigured(
                "ASAAS_API_KEY is not set. See docs/DEVELOPMENT.md#local-pix-setup for setup instructions."
            )
        env = getattr(settings, "ASAAS_ENVIRONMENT", "sandbox")
        self._base_url = _SANDBOX_URL if env == "sandbox" else _PRODUCTION_URL
        self._headers = {
            "access_token": api_key,
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, **kwargs) -> dict:
        """Make an API request, raise AsaasAPIError on failure."""
        url = f"{self._base_url}/{path.lstrip('/')}"
        try:
            resp = requests.request(method, url, headers=self._headers, timeout=_TIMEOUT, **kwargs)
        except requests.Timeout as exc:
            logger.error("asaas.timeout method=%s path=%s", method, path)
            raise AsaasAPIError(f"Asaas não respondeu em {_TIMEOUT}s. Tente novamente.") from exc
        except requests.RequestException as exc:
            logger.error("asaas.network_error method=%s path=%s err=%s", method, path, exc)
            raise AsaasAPIError(f"Erro de rede ao conectar com Asaas: {exc}") from exc

        if not resp.ok:
            logger.error(
                "asaas.api_error method=%s path=%s status=%s body=%s",
                method,
                path,
                resp.status_code,
                resp.text[:200],
            )
            raise AsaasAPIError(
                f"Asaas retornou {resp.status_code}. Tente novamente.",
                status_code=resp.status_code,
            )
        return resp.json()

    def get_or_create_customer(self, patient) -> str:
        """
        Returns the Asaas customer_id for a patient.
        Creates a new Asaas customer if one doesn't exist.
        LGPD: sends only name and email — no CPF transmitted.
        """
        # Check if we already have a customer ID stored on a previous PIX charge
        from apps.billing.models import PIXCharge

        existing = (
            PIXCharge.objects.filter(
                appointment__patient=patient,
                asaas_customer_id__gt="",
            )
            .values_list("asaas_customer_id", flat=True)
            .first()
        )
        if existing:
            return existing

        # Create new Asaas customer — name + email only (LGPD)
        payload = {
            "name": patient.full_name,
            "email": patient.email or f"patient-{patient.id}@vitali.internal",
            "externalReference": str(patient.id),
            "notificationDisabled": True,
        }
        data = self._request("POST", "/customers", json=payload)
        return data["id"]

    def create_pix_charge(self, appointment, amount: Decimal) -> dict:
        """
        Create a PIX charge for an appointment.
        Returns dict with: asaas_charge_id, pix_copy_paste, pix_qr_code_base64, expires_at.
        """
        from datetime import timedelta

        from django.utils import timezone

        expiry_minutes = getattr(settings, "PIX_CHARGE_EXPIRY_MINUTES", 30)
        expires_at = timezone.now() + timedelta(minutes=expiry_minutes)

        customer_id = self.get_or_create_customer(appointment.patient)

        # Create the charge
        charge_payload = {
            "customer": customer_id,
            "billingType": "PIX",
            "value": float(amount),
            "dueDate": expires_at.strftime("%Y-%m-%d"),
            "description": (
                f"Consulta — {appointment.patient.full_name} "
                f"em {appointment.start_time.strftime('%d/%m/%Y %H:%M')}"
            ),
            "externalReference": str(appointment.id),
        }
        charge_data = self._request("POST", "/payments", json=charge_payload)
        charge_id = charge_data["id"]

        # Get PIX QR code
        pix_data = self._request("GET", f"/payments/{charge_id}/pixQrCode")

        return {
            "asaas_charge_id": charge_id,
            "asaas_customer_id": customer_id,
            "pix_copy_paste": pix_data.get("payload", ""),
            "pix_qr_code_base64": pix_data.get("encodedImage", ""),
            "expires_at": expires_at,
        }

    def cancel_charge(self, charge_id: str) -> bool:
        """Cancel a pending PIX charge. Returns True on success."""
        try:
            self._request("DELETE", f"/payments/{charge_id}")
            return True
        except AsaasAPIError:
            return False

    def get_charge_status(self, charge_id: str) -> str:
        """Returns the Asaas payment status string."""
        data = self._request("GET", f"/payments/{charge_id}")
        return data.get("status", "UNKNOWN")
