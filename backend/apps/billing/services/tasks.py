"""
S-055/S-056: Celery tasks for PIX billing.

- send_appointment_confirmation_email: fires after appointment_paid signal
- expire_pix_charges: periodic task to cancel expired pending charges
- send_appointment_reminders: periodic task for 24h reminder emails
"""

import logging
from datetime import timedelta

from celery import shared_task
from django.dispatch import receiver
from django.utils import timezone

from apps.core.tenancy import for_each_tenant_schema

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
    from apps.core.services.email import EmailService
    from apps.emr.models import Appointment

    try:
        appointment = Appointment.objects.select_related("patient", "professional").get(
            id=appointment_id
        )
    except Appointment.DoesNotExist:
        logger.error("send_confirmation.appointment_not_found id=%s", appointment_id)
        return

    EmailService.send_appointment_confirmation(appointment)


@shared_task
def expire_pix_charges() -> int:
    """
    S-055: Cancel pending PIX charges that have passed their expiry time.
    Runs every 5 minutes via Celery beat. Updates DB status; does NOT call
    Asaas cancel API (Asaas auto-expires; this is a local status sync).
    """
    counts = for_each_tenant_schema(
        _expire_pix_charges_for_schema,
        logger=logger,
        operation="expire_pix_charges",
    )
    return sum(count or 0 for count in counts)


def _expire_pix_charges_for_schema(schema_name: str) -> int:
    from apps.billing.models import PIXCharge

    now = timezone.now()
    expired_qs = PIXCharge.objects.filter(status=PIXCharge.Status.PENDING, expires_at__lt=now)
    count = expired_qs.update(status=PIXCharge.Status.EXPIRED)
    if count:
        logger.info("expire_pix_charges.expired schema=%s count=%d", schema_name, count)
    return count


@shared_task
def send_appointment_reminders() -> dict[str, int]:
    """
    S-056: Send 24h reminder emails for appointments starting tomorrow.
    Runs daily at 08:00 via Celery beat (set in vitali/celery.py).
    Only sends for confirmed appointments (status='confirmed').
    """
    results = for_each_tenant_schema(
        _send_appointment_reminders_for_schema,
        logger=logger,
        operation="send_appointment_reminders",
    )
    sent = sum(result.get("sent", 0) for result in results if result)
    total = sum(result.get("total", 0) for result in results if result)
    logger.info("send_appointment_reminders.done sent=%d total=%d", sent, total)
    return {"sent": sent, "total": total}


def _send_appointment_reminders_for_schema(schema_name: str) -> dict[str, int]:
    from apps.core.services.email import EmailService
    from apps.emr.models import Appointment

    tomorrow_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(
        days=1
    )
    tomorrow_end = tomorrow_start + timedelta(days=1)

    appointments = Appointment.objects.filter(
        start_time__gte=tomorrow_start,
        start_time__lt=tomorrow_end,
        status="confirmed",
    ).select_related("patient", "professional")

    sent = 0
    for appt in appointments:
        if EmailService.send_appointment_reminder(appt):
            sent += 1

    total = appointments.count()
    logger.info(
        "send_appointment_reminders.schema_done schema=%s sent=%d total=%d",
        schema_name,
        sent,
        total,
    )
    return {"sent": sent, "total": total}


@shared_task(name="billing.accrue_active_admissions")
def accrue_active_admissions() -> dict[str, int]:
    """B5 — Acumula as diárias de todas as internações ATIVAS, em todo tenant.

    A rede de segurança do acúmulo. O hook da alta
    (``billing.services.inpatient_signals``) pega a estada no último instante em
    que ela é faturável, mas depender só dele deixa a receita de uma internação
    longa pendurada num único evento: se aquela transação falhar, perde-se a
    estada inteira. Rodando diariamente, no pior caso perde-se um dia.

    Internação com alta NÃO entra: ou o hook já cuidou dela, ou o leito já foi
    liberado e não há mais tipo de leito para resolver o TUSS da diária.
    """
    results = for_each_tenant_schema(
        _accrue_daily_charges_for_schema,
        logger=logger,
        operation="accrue_active_admissions",
    )
    charges = sum(r.get("charges", 0) for r in results if r)
    admissions = sum(r.get("admissions", 0) for r in results if r)
    logger.info("accrue_active_admissions.done admissions=%d charges=%d", admissions, charges)
    return {"admissions": admissions, "charges": charges}


def _accrue_daily_charges_for_schema(schema_name: str) -> dict[str, int]:
    from apps.billing.services.inpatient_billing import accrue_daily_charges
    from apps.emr.models import Admission

    active = Admission.objects.filter(
        status=Admission.Status.ADMITTED, current_bed__isnull=False
    ).select_related("current_bed")

    admissions = 0
    charges = 0
    for admission in active.iterator():
        admissions += 1
        try:
            charges += len(accrue_daily_charges(admission))
        except Exception:
            # Uma internação problemática não pode abortar a varredura das
            # outras — seria trocar uma diária perdida por todas elas.
            logger.exception(
                "accrue_active_admissions: falha na internação %s (schema=%s)",
                admission.pk,
                schema_name,
            )

    if charges:
        logger.info(
            "accrue_active_admissions.schema schema=%s admissions=%d charges=%d",
            schema_name,
            admissions,
            charges,
        )
    return {"admissions": admissions, "charges": charges}
