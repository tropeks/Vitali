"""
EMR Celery tasks.

check_prescription_safety (S-063):
  AI prescription safety checking. Wired via post_save signal in
  EmrConfig.ready() through apps/emr/signals.py.  The signal uses
  transaction.on_commit() so the task fires only after the DB transaction
  commits — prevents race conditions where the task reads data before the
  write is visible.

send_appointment_confirmation_whatsapp (S-090 / F-02):
  Send WhatsApp appointment confirmation. Fail-open: persistent failure
  writes AuditLog 'appointment_whatsapp_failed' but never rolls back DB rows.
  Mirrors apps.hr.tasks.setup_staff_whatsapp_channel (Sprint 18 pattern).
  Enqueued via transaction.on_commit by AppointmentCreationService (decision 1B).
  Gated by WhatsAppContact.opt_in — task also re-checks opt-in at runtime
  (guard against revocation between queue and execution).
"""

import logging

from celery import shared_task
from celery.exceptions import MaxRetriesExceededError
from django.core.cache import cache
from django.db import transaction

from apps.core.models import AuditLog

logger = logging.getLogger(__name__)

SAFETY_STATUS_CACHE_TTL = 3600  # 1 hour
SAFETY_STATUS_KEY_TEMPLATE = "ai:safety_status:{item_id}"


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def check_prescription_safety(self, item_id: str):
    """
    Run PrescriptionSafetyChecker for a PrescriptionItem.

    Creates or updates AISafetyAlert records for each flagged alert.
    Updates the item's safety status badge in cache.
    Uses select_for_update() to prevent race conditions on retry.

    Idempotent: unique_together on (prescription_item, alert_type) prevents
    duplicate alerts if the task retries.
    """
    from apps.emr.models import AISafetyAlert, PrescriptionItem
    from apps.emr.services.prescription_safety import PrescriptionSafetyChecker

    status_key = SAFETY_STATUS_KEY_TEMPLATE.format(item_id=item_id)

    try:
        # select_for_update prevents concurrent task instances from racing
        with transaction.atomic():
            try:
                item = (
                    PrescriptionItem.objects.select_for_update()
                    .select_related("prescription__patient", "drug")
                    .get(id=item_id)
                )
            except PrescriptionItem.DoesNotExist:
                logger.warning("PrescriptionItem %s not found, skipping safety check", item_id)
                return

            prescription = item.prescription
            checker = PrescriptionSafetyChecker()
            result = checker.check(item, prescription)

            if result.degraded:
                # Don't create alerts for degraded (LLM error) results
                cache.set(
                    status_key,
                    {"status": "error", "alerts": [], "degraded": True},
                    SAFETY_STATUS_CACHE_TTL,
                )
                return

            # Create or update AISafetyAlert records for each flagged alert
            created_alerts = []
            for alert in result.alerts:
                safety_alert, _ = AISafetyAlert.objects.update_or_create(
                    prescription_item=item,
                    alert_type=alert.alert_type,
                    defaults={
                        "severity": alert.severity,
                        "message": alert.message,
                        "recommendation": alert.recommendation,
                        "status": "flagged",
                    },
                )
                created_alerts.append(
                    {
                        "id": str(safety_alert.id),
                        "alert_type": safety_alert.alert_type,
                        "severity": safety_alert.severity,
                        "message": safety_alert.message,
                        "recommendation": safety_alert.recommendation,
                    }
                )

            # Update cache with final status
            final_status = "safe" if result.is_safe else "flagged"
            cache.set(
                status_key,
                {"status": final_status, "alerts": created_alerts, "degraded": False},
                SAFETY_STATUS_CACHE_TTL,
            )

            logger.info(
                "Safety check complete for item %s: %s (%d alerts)",
                item_id,
                final_status,
                len(created_alerts),
            )

    except Exception as exc:
        logger.exception("Safety check task failed for item %s: %s", item_id, exc)
        # Set error status in cache before retry
        cache.set(
            status_key,
            {"status": "error", "alerts": [], "degraded": True},
            SAFETY_STATUS_CACHE_TTL,
        )
        raise self.retry(exc=exc) from exc


# ── S-090 / F-02: Appointment WhatsApp confirmation ──────────────────────────


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_appointment_confirmation_whatsapp(
    self, appointment_id: str, correlation_id: str | None = None
) -> None:
    """
    Send WhatsApp appointment confirmation. Fail-open: persistent failure
    writes AuditLog 'appointment_whatsapp_failed' but never affects DB rows.

    Decision 1B fail-open. Mirrors apps.hr.tasks.setup_staff_whatsapp_channel.

    Args:
        appointment_id: UUID of the Appointment to confirm.
        correlation_id: UUID4 from AppointmentCreationService.correlation_id —
            included in both success and failure AuditLog entries so the cascade
            audit chain (decision 2A) stays intact across the service → task
            boundary.

    Gating: re-checks WhatsAppContact.opt_in at task run time to handle
    revocations between queue time and execution time. Silent no-op if
    contact no longer opted in.
    """
    from apps.emr.models import Appointment
    from apps.whatsapp.gateway import get_gateway
    from apps.whatsapp.models import WhatsAppContact

    # ── 1. Resolve appointment ────────────────────────────────────────────────
    try:
        appt = Appointment.objects.select_related("patient", "professional__user").get(
            id=appointment_id
        )
    except Appointment.DoesNotExist:
        logger.error(
            "send_appointment_confirmation_whatsapp: appointment %s not found — skipping",
            appointment_id,
        )
        return  # Not a transient error; don't retry.

    # ── 2. Guard: re-check opt-in at task runtime ─────────────────────────────
    contact = WhatsAppContact.objects.filter(patient=appt.patient, opt_in=True).first()
    if not contact:
        logger.info(
            "send_appointment_confirmation_whatsapp: no opted-in contact for patient %s — skipping",
            appt.patient_id,
        )
        return

    # ── 3. Send WhatsApp confirmation ─────────────────────────────────────────
    try:
        gateway = get_gateway()
        prof_name = (
            appt.professional.user.full_name
            if appt.professional and appt.professional.user
            else "—"
        )
        text = (
            f"Olá {appt.patient.full_name}! Sua consulta com {prof_name} foi agendada para "
            f"{appt.start_time.strftime('%d/%m/%Y às %H:%M')}."
        )
        gateway.send_text(contact.phone, text)

        AuditLog.objects.create(
            user=None,  # System action — Celery task has no requesting-user context
            action="appointment_whatsapp_sent",
            resource_type="appointment",
            resource_id=str(appointment_id),
            new_data={"phone": contact.phone, "correlation_id": correlation_id},
        )
        logger.info(
            "send_appointment_confirmation_whatsapp: success for appointment %s",
            appointment_id,
        )

    except Exception as exc:
        # Transient error — retry. When retries are exhausted, self.retry()
        # raises MaxRetriesExceededError; we catch that to write the failure log.
        try:
            raise self.retry(exc=exc) from exc
        except MaxRetriesExceededError:
            AuditLog.objects.create(
                user=None,
                action="appointment_whatsapp_failed",
                resource_type="appointment",
                resource_id=str(appointment_id),
                new_data={
                    "reason": "max_retries_exceeded",
                    "error": str(exc)[:200],
                    "correlation_id": correlation_id,
                },
            )
            logger.error(
                "send_appointment_confirmation_whatsapp: persistent failure for appointment %s",
                appointment_id,
                exc_info=True,
            )
