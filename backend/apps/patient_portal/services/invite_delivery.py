"""
Patient Portal invite delivery (issue #117).

`PatientPortalAccess.invite_token` is minted by the model, but on its own the
activation link never reaches the patient. This module wires the token to two
delivery channels:

1. **WhatsApp** (primary) — via `WhatsAppGateway.send_text()`. Gated on an
   *opted-in* `WhatsAppContact` for the patient (LGPD consent lives on the
   contact's `opt_in` flag, never on the bare phone number).
2. **Email** (fallback) — via `EmailService.send_portal_invitation()`. Only
   attempted when WhatsApp was not delivered and the patient has an address.

Delivery is **fail-open**: minting an invite must never break because a
channel is down. Every failure is logged and swallowed; the caller decides
nothing on the return value beyond observability/telemetry.
"""

from __future__ import annotations

import logging

from django.conf import settings

logger = logging.getLogger(__name__)


def build_activation_url(access) -> str:
    """Frontend activation link the patient consumes to go invited → active."""
    base = getattr(settings, "FRONTEND_URL", "http://localhost:3000").rstrip("/")
    return f"{base}/portal/activate?token={access.invite_token}"


def build_whatsapp_message(patient_name: str, link: str) -> str:
    """WhatsApp invite template with the formatted activation link."""
    greeting = f"Olá {patient_name}!" if patient_name else "Olá!"
    return (
        f"{greeting} 🏥\n\n"
        f"Seu acesso ao *Portal do Paciente* da Vitali está pronto. "
        f"No portal você acompanha consultas, prescrições e resultados.\n\n"
        f"Ative seu acesso pelo link abaixo (expira em 7 dias):\n{link}"
    )


def deliver_portal_invite(access) -> list[str]:
    """
    Deliver the portal activation link for *access*.

    Returns the list of channels that accepted the message (e.g. ``["whatsapp"]``
    or ``["email"]``; ``[]`` when no channel was available). Never raises.
    """
    patient = access.patient
    link = build_activation_url(access)
    delivered: list[str] = []

    if _try_whatsapp(patient, link):
        delivered.append("whatsapp")
    elif _try_email(patient, link):
        # Email is a *fallback*: only used when WhatsApp was not delivered.
        delivered.append("email")

    if not delivered:
        logger.warning(
            "portal_invite.undelivered access=%s patient=%s reason=no_channel",
            access.id,
            patient.id,
        )
    return delivered


def _try_whatsapp(patient, link: str) -> bool:
    """Send via WhatsApp iff the patient has an opted-in contact."""
    from apps.whatsapp.gateway import get_gateway
    from apps.whatsapp.models import WhatsAppContact

    # Gate: WhatsApp only when an opted-in contact exists (opt_in=True).
    contact = WhatsAppContact.objects.filter(patient=patient, opt_in=True).first()
    if not contact:
        return False

    try:
        text = build_whatsapp_message(getattr(patient, "full_name", "") or "", link)
        get_gateway().send_text(contact.phone, text)
        logger.info(
            "portal_invite.sent channel=whatsapp patient=%s contact=%s",
            patient.id,
            contact.id,
        )
        return True
    except Exception as exc:  # noqa: BLE001 — fail-open, fall through to email
        logger.error(
            "portal_invite.failed channel=whatsapp patient=%s err=%s",
            patient.id,
            exc,
        )
        return False


def _try_email(patient, link: str) -> bool:
    """Send the email fallback iff the patient has an address."""
    from apps.core.services.email import EmailService

    # Gate: email only when an address is present (checked inside the service,
    # which returns False and logs when absent).
    return EmailService.send_portal_invitation(patient, link)
