"""Appointment creation cascade service — Sprint 20 / S-090 / F-02.

Locked architecture decisions (from /autoplan + /plan-eng-review):
  1A — Service-layer orchestrator, NOT Django signals.
  1B — atomic DB block + transaction.on_commit fail-open for WhatsApp.
  2A — AuditLog correlation_id in new_data JSON for full cascade tracing.

LGPD posture (Sprint 19 D2 carries forward):
  WhatsApp confirmation gated by WhatsAppContact.opt_in.
  Patients without an opted-in contact get a silent no-op (no message,
  no failure). The Appointment row + slot still persist.

REMOVED from spec: Draft TISSGuide creation at appointment time.
  TISSGuide model has encounter FK with on_delete=PROTECT plus required
  insured_card_number + competency fields — cannot exist pre-encounter.
  TISS work moves to F-03 (Sprint 21).

Usage:
    service = AppointmentCreationService(requesting_user=request.user)
    service.create(appointment)  # appointment already saved by serializer.save()
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import uuid4

from django.db import transaction

from apps.core.models import AuditLog
from apps.emr.tasks import send_appointment_confirmation_whatsapp
from apps.whatsapp.models import WhatsAppContact

if TYPE_CHECKING:
    from apps.emr.models import Appointment

logger = logging.getLogger(__name__)


class AppointmentCreationService:
    """
    Service-layer orchestrator for F-02 Appointment-created cascade.

    Locked decisions:
      1A — service-layer (NOT signals)
      1B — atomic DB block + transaction.on_commit fail-open for WhatsApp
      2A — AuditLog correlation_id propagated to the Celery task

    LGPD posture (Sprint 19 D2 carries): WhatsApp confirmation gated by
    WhatsAppContact.opt_in. Patients without an opted-in contact get a silent
    no-op (no message, no failure). The Appointment row + slot still persist.
    """

    def __init__(self, requesting_user) -> None:
        self.requesting_user = requesting_user
        self.correlation_id = str(uuid4())

    def create(self, appointment) -> Appointment:
        """
        Wraps the appointment creation in the cascade. Caller has already
        saved the Appointment via serializer.save() — we audit + on_commit.

        Args:
            appointment: the already-saved Appointment instance.

        Returns:
            The same Appointment instance, unchanged.
        """
        with transaction.atomic():
            # Audit the appointment itself first
            self._audit(
                "appointment_created",
                "appointment",
                appointment.id,
                new_data={
                    "patient_id": str(appointment.patient_id),
                    "professional_id": str(appointment.professional_id),
                    "start_time": appointment.start_time.isoformat(),
                    "status": appointment.status,
                },
            )

            # Check opt-in gate; only queue task if there's an opted-in contact
            contact = WhatsAppContact.objects.filter(
                patient=appointment.patient, opt_in=True
            ).first()
            if contact:
                appointment_id = str(appointment.id)
                correlation_id = self.correlation_id
                transaction.on_commit(
                    lambda: send_appointment_confirmation_whatsapp.delay(
                        appointment_id, correlation_id
                    )
                )
                self._audit("appointment_whatsapp_queued", "appointment", appointment.id)
            else:
                self._audit(
                    "appointment_whatsapp_skipped",
                    "appointment",
                    appointment.id,
                    new_data={"reason": "no_opted_in_contact"},
                )

        return appointment

    def _audit(
        self,
        action: str,
        resource_type: str,
        resource_id: object,
        new_data: dict | None = None,
    ) -> None:
        """Write an AuditLog entry tagged with this service invocation's correlation_id."""
        data = dict(new_data) if new_data else {}
        data["correlation_id"] = self.correlation_id
        AuditLog.objects.create(
            user=self.requesting_user,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id),
            new_data=data,
        )
