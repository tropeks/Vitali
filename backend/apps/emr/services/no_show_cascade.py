"""
F-11 (E-013): No-show cascade.

When an Appointment transitions to ``no_show`` the clinic loses a slot it could
still fill. This service runs the three-step cascade specified by F-11:

  1. **Re-engagement** — send the patient a WhatsApp message offering to
     reschedule. Sent ONLY if the patient has an opted-in ``WhatsAppContact``
     (LGPD: no outreach without opt-in); silently skipped otherwise.
  2. **Slot reopening** — the slot frees automatically: ``no_show`` is excluded
     from every "booked" filter (``Appointment.clean`` overlap guard and
     ``AvailableSlotsView``), so no extra write is needed. Documented here so the
     behaviour is intentional, not accidental.
  3. **Waitlist consultation** — offer the freed slot to the first eligible
     patient on the professional's waitlist, reusing the existing
     ``notify_next_waitlist_entry`` cascade (the same path cancellations use).

Posture: advise/operational and **fail-open**. A failure in the re-engagement
leg is logged and swallowed — the appointment is already terminal, so the
cascade is best-effort outreach and must never roll back the ``no_show``
transition or block the waitlist consultation.
"""

import logging

from apps.whatsapp.gateway import OptOutError, get_gateway

logger = logging.getLogger(__name__)


def _build_freed_slot(appointment) -> dict:
    """ISO slot dict consumed by ``notify_next_waitlist_entry``."""
    return {
        "start": appointment.start_time.isoformat(),
        "end": appointment.end_time.isoformat(),
    }


def _reengagement_message(appointment) -> str:
    """Build the re-engagement / reschedule-offer message body."""
    professional = appointment.professional
    doctor_name = (
        professional.user.full_name if hasattr(professional, "user") else str(professional)
    )
    date_str = appointment.start_time.strftime("%d/%m/%Y às %H:%M")
    return (
        f"Olá! Sentimos sua falta na consulta com Dr(a). {doctor_name} "
        f"em {date_str}. Podemos te ajudar a reagendar? "
        f"Responda *REAGENDAR* para escolher um novo horário."
    )


def _send_reengagement(appointment) -> bool:
    """Send the re-engagement WhatsApp message if the patient opted in.

    Returns ``True`` when a message was dispatched. Fail-open: any lookup or
    gateway error is logged and swallowed (returns ``False``).
    """
    from apps.whatsapp.models import WhatsAppContact

    contact = WhatsAppContact.objects.filter(patient=appointment.patient, opt_in=True).first()
    if contact is None:
        logger.info(
            "no_show_cascade: patient %s has no opted-in WhatsApp contact — skipping outreach",
            appointment.patient_id,
        )
        return False

    try:
        gateway = get_gateway()
        # send_if_opted_in re-checks opt_in (defends against a flip between the
        # query above and the send) and raises OptOutError if it changed.
        gateway.send_if_opted_in(contact, _reengagement_message(appointment))
    except OptOutError:
        logger.info(
            "no_show_cascade: contact %s opted out before send — skipping outreach",
            contact.id,
        )
        return False
    except Exception:
        logger.warning(
            "no_show_cascade: failed to send re-engagement for appointment %s",
            appointment.id,
            exc_info=True,
        )
        return False

    logger.info(
        "no_show_cascade: re-engagement sent to patient %s (appointment %s)",
        appointment.patient_id,
        appointment.id,
    )
    return True


def run_no_show_cascade(appointment) -> dict:
    """Execute the F-11 cascade for an appointment that just became ``no_show``.

    Callers MUST only invoke this on the transition into ``no_show`` (idempotency
    is the caller's responsibility — both trigger sites fire exactly once per
    transition). Returns a small result dict for logging/tests.
    """
    from apps.emr.tasks_waitlist import notify_next_waitlist_entry

    if appointment.status != "no_show":
        logger.warning(
            "run_no_show_cascade: appointment %s has status=%s (expected no_show) — skipping",
            appointment.id,
            appointment.status,
        )
        return {"reengaged": False, "waitlist_triggered": False}

    reengaged = _send_reengagement(appointment)

    # The slot is already free (no_show is excluded from booked filters). Offer it
    # to the first eligible waitlist entry for this professional.
    slot = _build_freed_slot(appointment)
    notify_next_waitlist_entry.delay(str(appointment.professional_id), slot)

    logger.info(
        "no_show_cascade: completed for appointment %s (reengaged=%s)",
        appointment.id,
        reengaged,
    )
    return {"reengaged": reengaged, "waitlist_triggered": True}
