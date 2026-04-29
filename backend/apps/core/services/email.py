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
    def send_user_invitation(cls, user, link: str) -> None:
        """
        Send an invite-to-set-password email to *user*.
        Called by _create_invitation_for_user in apps.core.views (T6).
        Never raises — logs errors instead.
        """
        recipient = getattr(user, "email", None)
        if not recipient:
            logger.warning("email.skipped user=%s reason=no_email", getattr(user, "id", "?"))
            return

        subject = "Bem-vindo à Vitali — configure sua conta"
        template = "email/user_invitation.html"
        context = {
            "user": user,
            "link": link,
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

            logger.info("email.sent template=%s user=%s to=%s", template, user.id, recipient)
        except Exception as exc:
            logger.error("email.failed template=%s user=%s err=%s", template, user.id, exc)

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
            logger.warning("email.skipped appointment=%s reason=no_patient_email", appointment.id)
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
                template,
                appointment.id,
                recipient,
            )
            return True

        except Exception as exc:
            logger.error(
                "email.failed template=%s appointment=%s err=%s",
                template,
                appointment.id,
                exc,
            )
            return False

    @classmethod
    def send_dpa_signed_notification(cls, user, flags_enabled: list) -> None:
        """
        Notify the tenant admin that the DPA was signed and AI features are live.
        Called by apps.core.tasks.send_dpa_signed_admin_email (S-081).
        Never raises — logs errors instead (fail-open, decision 1B).

        Args:
            user: the User who signed the DPA (the admin receiving the email).
            flags_enabled: list of module_key strings that were enabled.
        """
        recipient = getattr(user, "email", None)
        if not recipient:
            logger.warning(
                "email.skipped user=%s reason=no_email template=dpa_signed",
                getattr(user, "id", "?"),
            )
            return

        subject = "Vitali — DPA assinado, recursos de IA habilitados"
        flags_list_html = "".join(f"<li><code>{key}</code></li>" for key in flags_enabled)
        html_body = (
            f"<p>Olá {user.full_name},</p>"
            f"<p>O Acordo de Processamento de Dados (DPA) foi assinado com sucesso. "
            f"Os seguintes recursos de IA foram habilitados para o seu tenant:</p>"
            f"<ul>{flags_list_html}</ul>"
            f"<p>Caso tenha dúvidas, entre em contato com o suporte: "
            f"{getattr(settings, 'SUPPORT_EMAIL', 'suporte@vitali.app')}</p>"
            f"<p>Equipe Vitali</p>"
        )
        text_body = cls._strip_html(html_body)

        try:
            msg = EmailMultiAlternatives(
                subject=subject,
                body=text_body,
                from_email=cls.DEFAULT_FROM,
                to=[recipient],
            )
            msg.attach_alternative(html_body, "text/html")
            msg.send()

            logger.info(
                "email.sent template=dpa_signed user=%s to=%s",
                getattr(user, "id", "?"),
                recipient,
            )
        except Exception as exc:
            logger.error(
                "email.failed template=dpa_signed user=%s err=%s",
                getattr(user, "id", "?"),
                exc,
            )
            raise  # Re-raise so the Celery task's retry/failure logic fires

    @staticmethod
    def _strip_html(html: str) -> str:
        """Very basic HTML → plain text fallback."""
        import re

        text = re.sub(r"<[^>]+>", "", html)
        return re.sub(r"\n{3,}", "\n\n", text).strip()
