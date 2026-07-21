"""
Concrete patient-WhatsApp notifier — apps.whatsapp's implementation of the
apps.core port. Registered by ``WhatsappConfig.ready()`` so other domains
(e.g. apps.patient_portal invite delivery) can message a patient's opted-in
WhatsApp contact without importing apps.whatsapp directly (import-linter
domain-independence contract, P1-01).

The consent gate (``WhatsAppContact.opt_in``) and the Evolution gateway both
live here, in the channel that owns them. Delivery is fail-open: any gateway
error is logged and swallowed, and the method returns False so the caller can
fall back to another channel.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class PatientWhatsAppNotifierProvider:
    """Adapter exposing patient WhatsApp delivery to other domains."""

    def send_text_to_opted_in_patient(self, *, patient: Any, text: str) -> bool:
        from apps.whatsapp.gateway import get_gateway
        from apps.whatsapp.models import WhatsAppContact

        # Gate: only send when an opted-in contact exists (opt_in=True).
        # LGPD consent lives on the contact, never on a bare phone number.
        contact = WhatsAppContact.objects.filter(patient=patient, opt_in=True).first()
        if contact is None:
            return False

        try:
            get_gateway().send_text(contact.phone, text)
            logger.info(
                "patient_whatsapp.sent patient=%s contact=%s",
                getattr(patient, "id", "?"),
                contact.id,
            )
            return True
        except Exception as exc:  # noqa: BLE001 — fail-open, caller falls back
            logger.error(
                "patient_whatsapp.failed patient=%s err=%s",
                getattr(patient, "id", "?"),
                exc,
            )
            return False
