"""
S-055/S-056: Celery tasks for PIX billing.

- send_appointment_confirmation_email: fires after appointment_paid signal
- expire_pix_charges: periodic task to cancel expired pending charges
- send_appointment_reminders: periodic task for 24h reminder emails
"""
import logging

from celery import shared_task
from django.dispatch import receiver
from django.utils import timezone

from .pix_signals import appointment_paid

logger = logging.getLogger(__name__)


@receiver(appointment_paid)
def on_appointment_paid(sender, appointment, **kwargs):
    """
    Connect appointment_paid signal → Celery task.
    Never send email inline here — this runs inside the webhook DB transaction.
    """
    send_appointment_confirmation_email.delay(str(appointment.id))


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_appointment_confirmation_email(self, appointment_id: str):
    """Send PIX confirmation email. Retried up to 3× on failure."""
    from apps.emr.models import Appointment
    from apps.core.services.email import EmailService

    try:
        appointment = Appointment.objects.select_related("patient", "professional").get(
            id=appointment_id
        )
    except Appointment.DoesNotExist:
        logger.error("send_confirmation.appointment_not_found id=%s", appointment_id)
        return

    EmailService.send_appointment_confirmation(appointment)


@shared_task
def expire_pix_charges():
    """
    S-055: Cancel pending PIX charges that have passed their expiry time.
    Runs every 5 minutes via Celery beat. Updates DB status; does NOT call
    Asaas cancel API (Asaas auto-expires; this is a local status sync).
    """
    from apps.billing.models import PIXCharge

    now = timezone.now()
    expired_qs = PIXCharge.objects.filter(status=PIXCharge.Status.PENDING, expires_at__lt=now)
    count = expired_qs.update(status=PIXCharge.Status.EXPIRED)
    if count:
        logger.info("expire_pix_charges.expired count=%d", count)


@shared_task
def send_appointment_reminders():
    """
    S-056: Send 24h reminder emails for appointments starting tomorrow.
    Runs daily at 08:00 via Celery beat (set in vitali/celery.py).
    Only sends for confirmed appointments (status='confirmed').
    """
    from apps.emr.models import Appointment
    from apps.core.services.email import EmailService

    tomorrow_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0) + timezone.timedelta(days=1)
    tomorrow_end = tomorrow_start + timezone.timedelta(days=1)

    appointments = Appointment.objects.filter(
        start_time__gte=tomorrow_start,
        start_time__lt=tomorrow_end,
        status="confirmed",
    ).select_related("patient", "professional")

    sent = 0
    for appt in appointments:
        if EmailService.send_appointment_reminder(appt):
            sent += 1

    logger.info("send_appointment_reminders.done sent=%d total=%d", sent, appointments.count())
