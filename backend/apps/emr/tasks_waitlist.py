"""
S-066: Celery tasks for waitlist management.

notify_next_waitlist_entry: finds the next eligible patient for a cancelled slot
    and sends a WhatsApp notification. Sets status=notified and schedules expiry.

expire_waitlist_notifications: runs every 5 minutes (Celery beat schedule).
    Finds expired 'notified' entries and cascades to next entry.

WhatsApp message format (SIM/NÃO response):
  "Uma vaga ficou disponível com [Dr. X] em [date] às [time].
   Responda *SIM* para confirmar ou *NÃO* para ser removido da fila."

Race condition protection: select_for_update() inside atomic transaction.
Idempotency: check status == 'notified' inside locked block before expiring.
"""

import logging
from datetime import timedelta

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from apps.whatsapp.gateway import get_gateway

logger = logging.getLogger(__name__)

WAITLIST_TIMEOUT_MINUTES = 30


def _format_whatsapp_message(entry, slot: dict) -> str:
    """Build the WhatsApp notification message for a waitlist slot offer."""
    from datetime import datetime

    professional = entry.professional
    doctor_name = f"Dr(a). {professional.user.full_name}"

    # Parse slot start from ISO string
    try:
        slot_start_str = slot.get("start", "")
        if slot_start_str:
            slot_dt = datetime.fromisoformat(slot_start_str)
            date_str = slot_dt.strftime("%d/%m/%Y")
            time_str = slot_dt.strftime("%H:%M")
        else:
            date_str = "data a confirmar"
            time_str = "horário a confirmar"
    except (ValueError, AttributeError):
        date_str = "data a confirmar"
        time_str = "horário a confirmar"

    return (
        f"Uma vaga ficou disponível com {doctor_name} em {date_str} às {time_str}. "
        f"Responda *SIM* para confirmar ou *NÃO* para ser removido da fila."
    )


def _get_patient_phone(entry) -> str | None:
    """Extract patient's WhatsApp phone number."""
    try:
        patient = entry.patient
        # Try whatsapp_phone first, then phone
        phone = getattr(patient, "whatsapp_phone", None) or getattr(patient, "phone", None)
        return phone
    except Exception:
        return None


@shared_task
def notify_next_waitlist_entry(professional_id: str, cancelled_slot: dict):
    """
    Find the first eligible WaitlistEntry for the professional and slot,
    send a WhatsApp notification, and schedule the expiry task.

    Eligibility criteria:
    - status = 'waiting'
    - preferred_date_from <= slot.date <= preferred_date_to
    - slot time within preferred_time_start/preferred_time_end (or None = any time)

    Ordered by priority ASC, created_at ASC.
    """
    from datetime import datetime

    from apps.emr.models import WaitlistEntry

    try:
        slot_start_str = cancelled_slot.get("start", "")
        slot_dt = datetime.fromisoformat(slot_start_str) if slot_start_str else None
        slot_date = slot_dt.date() if slot_dt else None
        slot_time = slot_dt.time() if slot_dt else None
    except (ValueError, AttributeError, Exception):
        logger.warning("Invalid cancelled_slot format: %s", cancelled_slot)
        slot_date = None
        slot_time = None

    qs = WaitlistEntry.objects.filter(
        professional_id=professional_id,
        status="waiting",
    ).order_by("priority", "created_at")

    # Filter by date range if available
    if slot_date:
        qs = qs.filter(
            preferred_date_from__lte=slot_date,
            preferred_date_to__gte=slot_date,
        )

    # Filter by time range if available (None = any time)
    if slot_time:
        qs = qs.filter(models_time_filter_Q(slot_time))

    entry = qs.first()

    if not entry:
        logger.info(
            "No eligible waitlist entry for professional %s, slot %s",
            professional_id,
            cancelled_slot,
        )
        return

    # Lock and update the entry
    try:
        with transaction.atomic():
            entry = WaitlistEntry.objects.select_for_update().get(id=entry.id, status="waiting")
            entry.status = "notified"
            entry.notified_at = timezone.now()
            entry.expires_at = timezone.now() + timedelta(minutes=WAITLIST_TIMEOUT_MINUTES)
            entry.offered_slot = cancelled_slot
            entry.save(
                update_fields=[
                    "status",
                    "notified_at",
                    "expires_at",
                    "offered_slot",
                    "expiry_task_id",
                ]
            )
    except WaitlistEntry.DoesNotExist:
        # Entry was claimed by another task instance (race condition handled)
        logger.info("WaitlistEntry %s was claimed by another task", entry.id)
        # Try the next entry
        notify_next_waitlist_entry.delay(professional_id, cancelled_slot)
        return
    except Exception as exc:
        logger.exception("Failed to lock waitlist entry %s: %s", entry.id, exc)
        return

    # Send WhatsApp notification
    phone = _get_patient_phone(entry)
    if phone:
        try:
            gateway = get_gateway()
            message = _format_whatsapp_message(entry, cancelled_slot)
            gateway.send_text(to=phone, text=message)
            logger.info(
                "Waitlist WhatsApp sent to patient %s for slot %s",
                entry.patient_id,
                cancelled_slot,
            )
        except Exception:
            logger.warning("Failed to send WhatsApp to patient %s", entry.patient_id, exc_info=True)
            # Non-fatal: entry is already notified; patient may respond via other channel
    else:
        logger.warning("No phone number for patient %s (entry %s)", entry.patient_id, entry.id)

    # Schedule expiry task
    try:
        result = expire_single_waitlist_entry.apply_async(
            args=[str(entry.id), str(professional_id), cancelled_slot],
            countdown=WAITLIST_TIMEOUT_MINUTES * 60,
        )
        # Store task ID for idempotency checks
        WaitlistEntry.objects.filter(id=entry.id).update(expiry_task_id=str(result.id))
    except Exception:
        logger.warning("Failed to schedule expiry task for entry %s", entry.id, exc_info=True)


def models_time_filter_Q(slot_time):
    """
    Build a Q filter for time range matching.
    Allows entries with NULL time fields (any time).
    """
    from django.db.models import Q

    return Q(preferred_time_start__isnull=True) | (
        Q(preferred_time_start__lte=slot_time)
        & (Q(preferred_time_end__isnull=True) | Q(preferred_time_end__gte=slot_time))
    )


@shared_task
def expire_single_waitlist_entry(entry_id: str, professional_id: str, slot: dict):
    """
    Expire a single notified waitlist entry and cascade to next.
    Called by notify_next_waitlist_entry after WAITLIST_TIMEOUT_MINUTES.
    Uses select_for_update() + idempotency check.
    """
    from apps.emr.models import WaitlistEntry

    try:
        with transaction.atomic():
            try:
                entry = WaitlistEntry.objects.select_for_update().get(id=entry_id)
            except WaitlistEntry.DoesNotExist:
                logger.info("WaitlistEntry %s not found during expiry", entry_id)
                return

            # Idempotency: only expire if still in 'notified' state
            if entry.status != "notified":
                logger.info(
                    "WaitlistEntry %s is in status=%s, skipping expiry",
                    entry_id,
                    entry.status,
                )
                return

            entry.status = "expired"
            entry.save(update_fields=["status"])
            logger.info("WaitlistEntry %s expired", entry_id)
    except Exception:
        logger.exception("Failed to expire waitlist entry %s", entry_id)
        return

    # Cascade: notify the next entry for the same slot
    notify_next_waitlist_entry.delay(professional_id, slot)


@shared_task
def expire_waitlist_notifications():
    """
    Periodic task (every 5 minutes via Celery beat).
    Find all WaitlistEntry where status='notified' and expires_at < now().
    Expire each one and cascade to next entry for the same slot.

    Uses select_for_update() to prevent double-expiry.
    Idempotency: checks status == 'notified' inside the locked block.
    """
    from apps.emr.models import WaitlistEntry

    now = timezone.now()
    expired_entries = (
        WaitlistEntry.objects.filter(
            status="notified",
            expires_at__lt=now,
        )
        .select_related("professional")
        .order_by("expires_at")
    )

    count = 0
    for entry in expired_entries:
        try:
            with transaction.atomic():
                locked_entry = WaitlistEntry.objects.select_for_update().get(id=entry.id)

                # Idempotency: re-check status inside locked block
                if locked_entry.status != "notified":
                    continue

                offered_slot = locked_entry.offered_slot or {}
                professional_id = str(locked_entry.professional_id)

                locked_entry.status = "expired"
                locked_entry.save(update_fields=["status"])
                count += 1

            # Cascade outside atomic to avoid nested transaction issues
            notify_next_waitlist_entry.delay(professional_id, offered_slot)

        except WaitlistEntry.DoesNotExist:
            continue
        except Exception:
            logger.exception("Error expiring waitlist entry %s", entry.id)

    logger.info("expire_waitlist_notifications: expired %d entries", count)
    return count
