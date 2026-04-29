"""
WhatsApp Celery tasks — S-034

- send_appointment_reminders: every 15 min, sends 24h and 2h reminders
- mark_no_shows: every hour, flags missed appointments
- send_satisfaction_surveys: every hour, sends post-visit survey 2h after completion
- cleanup_expired_sessions: every 15 min, deletes expired ConversationSession rows

All tasks: select_for_update(skip_locked=True) on ScheduledReminder to prevent
concurrent workers from double-sending.
"""

import logging
from datetime import timedelta

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from .gateway import OptOutError, get_gateway

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_appointment_reminders(self):
    """
    Query ScheduledReminder rows with status='pending' whose appointment starts
    within the reminder window. Send and mark as 'sent'.

    Runs every 15 min (registered in migration 0002).
    select_for_update(skip_locked=True) prevents double-send on concurrent workers.
    """
    from .models import ScheduledReminder

    now = timezone.now()
    window_24h_start = now + timedelta(hours=23, minutes=45)
    window_24h_end = now + timedelta(hours=24, minutes=15)
    window_2h_start = now + timedelta(hours=1, minutes=45)
    window_2h_end = now + timedelta(hours=2, minutes=15)

    gateway = get_gateway()

    # Ensure ScheduledReminder rows exist for upcoming appointments with opt-in contacts
    _ensure_reminders_exist(now)

    # Fetch and lock pending reminders inside a transaction (select_for_update requires it)
    with transaction.atomic():
        reminders_24h = list(
            ScheduledReminder.objects.filter(
                status="pending",
                reminder_type="24h",
                appointment__start_time__gte=window_24h_start,
                appointment__start_time__lte=window_24h_end,
            )
            .select_for_update(skip_locked=True)
            .select_related(
                "appointment__patient",
                "appointment__professional__user",
            )
        )

        reminders_2h = list(
            ScheduledReminder.objects.filter(
                status="pending",
                reminder_type="2h",
                appointment__start_time__gte=window_2h_start,
                appointment__start_time__lte=window_2h_end,
            )
            .select_for_update(skip_locked=True)
            .select_related(
                "appointment__patient",
                "appointment__professional__user",
            )
        )

        for reminder in reminders_24h + reminders_2h:
            _send_reminder(gateway, reminder)


def _ensure_reminders_exist(now):
    """Create ScheduledReminder rows for appointments in the next 25 hours that don't have them yet."""
    from apps.emr.models import Appointment

    from .models import ScheduledReminder, WhatsAppContact

    upcoming = Appointment.objects.filter(
        status__in=["scheduled", "confirmed"],
        start_time__gte=now,
        start_time__lte=now + timedelta(hours=25),
    ).select_related("patient")

    for appt in upcoming:
        # Check if patient has opted-in WhatsApp contact
        try:
            WhatsAppContact.objects.get(
                patient=appt.patient,
                opt_in=True,
            )
        except WhatsAppContact.DoesNotExist:
            continue

        for reminder_type in ("24h", "2h"):
            ScheduledReminder.objects.get_or_create(
                appointment=appt,
                reminder_type=reminder_type,
                defaults={"status": "pending"},
            )


def _send_reminder(gateway, reminder):
    from .models import WhatsAppContact

    appt = reminder.appointment
    try:
        contact = WhatsAppContact.objects.get(patient=appt.patient, opt_in=True)
    except WhatsAppContact.DoesNotExist:
        reminder.status = "skipped"
        reminder.save(update_fields=["status"])
        return

    label = "24 horas" if reminder.reminder_type == "24h" else "2 horas"
    pro_name = (
        appt.professional.user.full_name
        if hasattr(appt.professional, "user")
        else str(appt.professional)
    )
    text = (
        f"🔔 Lembrete de consulta!\n\n"
        f"Sua consulta com {pro_name} é em {label}.\n"
        f"📅 {appt.start_time.strftime('%d/%m/%Y às %H:%M')}\n\n"
        f"Responda:\n✅ *confirmar*\n📅 *remarcar*\n❌ *cancelar*"
    )
    try:
        gateway.send_if_opted_in(contact, text)
        reminder.status = "sent"
        reminder.sent_at = timezone.now()
        reminder.save(update_fields=["status", "sent_at"])
        appt.whatsapp_reminder_sent = True
        appt.save(update_fields=["whatsapp_reminder_sent", "updated_at"])
    except OptOutError:
        reminder.status = "skipped"
        reminder.save(update_fields=["status"])
    except Exception as exc:
        logger.error("Failed to send reminder %s: %s", reminder.pk, exc)
        reminder.status = "failed"
        reminder.save(update_fields=["status"])


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def mark_no_shows(self):
    """
    Mark appointments as no_show if:
    - reminder was sent (whatsapp_reminder_sent=True)
    - appointment time has passed
    - appointment was not confirmed via WhatsApp
    - status is still 'scheduled'

    Runs every hour.
    """
    from apps.emr.models import Appointment

    cutoff = timezone.now() - timedelta(minutes=30)
    updated = Appointment.objects.filter(
        status="scheduled",
        whatsapp_reminder_sent=True,
        whatsapp_confirmed=False,
        end_time__lt=cutoff,
    ).update(status="no_show")

    if updated:
        logger.info("Marked %d appointments as no_show", updated)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_satisfaction_surveys(self):
    """
    Send post-visit satisfaction survey 2h after appointment status = 'completed'.
    Only once per appointment (ScheduledReminder unique_together guard).

    Runs every hour.
    """
    from apps.emr.models import Appointment

    from .models import ScheduledReminder, WhatsAppContact

    gateway = get_gateway()
    cutoff_start = timezone.now() - timedelta(hours=3)
    cutoff_end = timezone.now() - timedelta(hours=2)

    completed = Appointment.objects.filter(
        status="completed",
        end_time__gte=cutoff_start,
        end_time__lte=cutoff_end,
    ).select_related("patient", "professional__user")

    for appt in completed:
        reminder, created = ScheduledReminder.objects.get_or_create(
            appointment=appt,
            reminder_type="satisfaction",
            defaults={"status": "pending"},
        )
        if not created and reminder.status != "pending":
            continue

        # Lock to prevent concurrent send — select_for_update requires transaction.atomic()
        with transaction.atomic():
            try:
                locked = ScheduledReminder.objects.select_for_update(skip_locked=True).get(
                    pk=reminder.pk, status="pending"
                )
            except ScheduledReminder.DoesNotExist:
                continue

            try:
                contact = WhatsAppContact.objects.get(patient=appt.patient, opt_in=True)
            except WhatsAppContact.DoesNotExist:
                locked.status = "skipped"
                locked.save(update_fields=["status"])
                continue

            pro_name = (
                appt.professional.user.full_name
                if hasattr(appt.professional, "user")
                else str(appt.professional)
            )
            text = (
                f"Olá! 😊 Como foi sua consulta com {pro_name}?\n\n"
                f"1️⃣ 😊 Muito bom\n"
                f"2️⃣ 😐 Ok\n"
                f"3️⃣ 😕 Poderia ser melhor"
            )
            try:
                gateway.send_if_opted_in(contact, text)
                locked.status = "sent"
                locked.sent_at = timezone.now()
                locked.save(update_fields=["status", "sent_at"])
            except OptOutError:
                locked.status = "skipped"
                locked.save(update_fields=["status"])
            except Exception as exc:
                logger.error("Failed to send satisfaction survey for appt %s: %s", appt.pk, exc)
                locked.status = "failed"
                locked.save(update_fields=["status"])


@shared_task
def cleanup_expired_sessions():
    """Delete ConversationSession rows past their expires_at. Runs every 15 min."""
    from .models import ConversationSession

    count, _ = ConversationSession.objects.filter(expires_at__lt=timezone.now()).delete()
    if count:
        logger.info("Cleaned up %d expired WhatsApp conversation sessions", count)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_post_opt_in_welcome(self, contact_id: str, correlation_id: str | None = None) -> None:
    """
    Send post-opt-in welcome message. Fail-open (decision 1B).
    """
    from celery.exceptions import MaxRetriesExceededError

    from apps.core.models import AuditLog
    from apps.whatsapp.gateway import get_gateway
    from apps.whatsapp.models import WhatsAppContact

    try:
        contact = WhatsAppContact.objects.select_related("patient").get(id=contact_id)
    except WhatsAppContact.DoesNotExist:
        logger.error("send_post_opt_in_welcome: contact %s not found", contact_id)
        return

    if not contact.opt_in:
        # Defensive: opted back out between enqueue and run. No message.
        return

    patient_name = contact.patient.full_name if contact.patient else "—"
    try:
        gateway = get_gateway()
        text = (
            f"Olá {patient_name}! Obrigado por confirmar. Você passará a receber "
            f"confirmações de consultas e lembretes pela Vitali. Para sair a qualquer "
            f"momento, responda 'sair'."
        )
        gateway.send_text(contact.phone, text)
        AuditLog.objects.create(
            user=None,
            action="opt_in_welcome_sent",
            resource_type="whatsapp_contact",
            resource_id=str(contact_id),
            new_data={"phone": contact.phone, "correlation_id": correlation_id},
        )
    except Exception as exc:
        try:
            raise self.retry(exc=exc) from exc
        except MaxRetriesExceededError:
            AuditLog.objects.create(
                user=None,
                action="opt_in_welcome_failed",
                resource_type="whatsapp_contact",
                resource_id=str(contact_id),
                new_data={
                    "reason": "max_retries_exceeded",
                    "error": str(exc)[:200],
                    "correlation_id": correlation_id,
                },
            )
            logger.error(
                "send_post_opt_in_welcome: persistent failure for contact %s",
                contact_id,
                exc_info=True,
            )
