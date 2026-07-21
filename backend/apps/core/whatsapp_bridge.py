"""
Patient-WhatsApp notifier port — the apps.core seam between domains that need
to message a patient over WhatsApp (e.g. apps.patient_portal invite delivery)
and the apps.whatsapp channel that owns contacts, consent (opt_in) and the
Evolution gateway.

Domain apps must not import each other directly (import-linter
domain-independence contract, P1-01). This module is the dependency-inversion
seam that lets a consumer send a WhatsApp message to a patient without a static
``apps.patient_portal -> apps.whatsapp`` import (mirrors apps.core.triage_bridge):

- apps.core defines the port (this module) and imports NO domain app.
- apps.whatsapp registers its concrete provider here in ``WhatsappConfig.ready()``.
- consumers resolve the provider at call time via
  ``get_patient_whatsapp_notifier()`` and drive it purely by duck typing.

If the whatsapp app is not installed (or has not registered), consumers get
``None`` and must degrade gracefully (e.g. fall back to email).
"""

from __future__ import annotations

from typing import Any, Protocol


class PatientWhatsAppNotifier(Protocol):
    """The single operation other domains need from the WhatsApp channel."""

    def send_text_to_opted_in_patient(self, *, patient: Any, text: str) -> bool:
        """Send ``text`` to the patient's opted-in WhatsApp contact.

        The opt_in (LGPD consent) gate and the gateway live in the whatsapp
        domain — callers pass only the patient and the message body.

        Returns True iff an opted-in contact existed and the gateway accepted
        the message; False otherwise (no contact, not opted in, or send failed).
        Never raises.
        """
        ...


_notifier: PatientWhatsAppNotifier | None = None


def register_patient_whatsapp_notifier(notifier: PatientWhatsAppNotifier) -> None:
    """Register the active notifier (called by WhatsappConfig.ready())."""
    global _notifier
    _notifier = notifier


def get_patient_whatsapp_notifier() -> PatientWhatsAppNotifier | None:
    """Return the registered notifier, or None if WhatsApp is unavailable."""
    return _notifier
