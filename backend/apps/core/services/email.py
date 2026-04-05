"""
S-056: Transactional email service.

Sends appointment confirmation and 24h reminder emails via Django's email backend.
In development: prints to console (EMAIL_BACKEND = console).
In production: configure EMAIL_BACKEND + SMTP settings.

Usage:
    EmailService.send_appointment_confirmation(appointment)
    EmailService.send_appointment_reminder(appointment)
"""
import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone

logger = logging.getLogger(__name__)


class EmailService:
    """Stateless transactional email helpers."""

    DEFAULT_FROM = getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@vitali.app")

    @classmethod
    def send_appointment_confirmation(cls, appointment) -> bool:
        """
        Send confirmation email after PIX payment is received.
        Returns True on success, False on failure (never raises).
        """
        return cls._send(
            appointment=appointment,
            subject="Consulta confirmada — Vitali",
            template="email/appointment_confirmation.html",
        )

    @classmethod
    def send_appointment_reminder(cls, appointment) -> bool:
        """
        Send 24h reminder email.
        Returns True on success, False on failure (never raises).
        """
        return cls._send(
            appointment=appointment,
            subject="Lembrete: sua consulta é amanhã — Vitali",
            template="email/appointment_reminder.html",
        )

    @classmethod
    def _send(cls, appointment, subject: str, template: str) -> bool:
        patient = appointment.patient
        recipient = getattr(patient, "email", None)
        if not recipient:
            logger.warning(
                "email.skipped appointment=%s reason=no_patient_email", appointment.id
            )
            return False

        context = {
            "patient_name": patient.full_name,
            "appointment": appointment,
            "start_time_local": timezone.localtime(appointment.start_time),
            "clinic_name": getattr(settings, "CLINIC_DISPLAY_NAME", "Clínica Vitali"),
            "support_email": getattr(settings, "SUPPORT_EMAIL", "suporte@vitali.app"),
        }

        try:
            html_body = render_to_string(template, context)
            text_body = cls._strip_html(html_body)

            msg = EmailMultiAlternatives(
                subject=subject,
                body=text_body,
                from_email=cls.DEFAULT_FROM,
                to=[recipient],
            )
            msg.attach_alternative(html_body, "text/html")
            msg.send()

            logger.info(
                "email.sent template=%s appointment=%s to=%s",
                template, appointment.id, recipient,
            )
            return True

        except Exception as exc:
            logger.error(
                "email.failed template=%s appointment=%s err=%s",
                template, appointment.id, exc,
            )
            return False

    @staticmethod
    def _strip_html(html: str) -> str:
        """Very basic HTML → plain text fallback."""
        import re
        text = re.sub(r"<[^>]+>", "", html)
        return re.sub(r"\n{3,}", "\n\n", text).strip()
