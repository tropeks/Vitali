"""Patient registration cascade service — Sprint 19 / S-080 / F-04.

Locked architecture decisions (from /plan-eng-review v2 + /autoplan):
  1A — Service-layer orchestrator, NOT Django signals.
  2A — AuditLog correlation_id in new_data JSON for full cascade tracing.
  D2 — LGPD posture B: WhatsAppContact created with opt_in=False;
       NO outbound message in v1. Welcome handshake deferred to S-035
       (FSM-based explicit opt-in).

Race-safety decision (eng review A5):
  select_for_update + IntegrityError catch on WhatsAppContact creation.

Usage:
    service = PatientRegistrationService(requesting_user=request.user)
    service.register(patient)  # patient already saved by serializer.save()
"""

import logging
from uuid import uuid4

from django.db import IntegrityError, transaction

from apps.core.models import AuditLog
from apps.emr.models import Patient
from apps.whatsapp.models import WhatsAppContact

logger = logging.getLogger(__name__)


class PatientRegistrationService:
    """
    Orchestrates post-save Patient cascade:
      1. AuditLog entry for the patient creation (with correlation_id).
      2. Atomic WhatsAppContact get-or-create (race-safe).
      3. AuditLog entry for the WhatsApp contact mapping.

    Sprint 19 scope: structural only — no Celery task, no welcome message,
    no MedicalHistory pre-creation.
    """

    def __init__(self, requesting_user) -> None:
        self.requesting_user = requesting_user
        self.correlation_id = str(uuid4())

    def register(self, patient: Patient) -> Patient:
        """
        Main entry point. Patient is already saved by the serializer.
        Runs inside a new atomic block so both audit entries and the
        WhatsAppContact row either all commit or all roll back together.

        Args:
            patient: the already-saved Patient instance.

        Returns:
            The same Patient instance, unchanged.
        """
        with transaction.atomic():
            self._audit(
                "patient_created",
                "patient",
                patient.id,
                new_data={
                    "mrn": patient.medical_record_number,
                    "full_name": patient.full_name,
                },
            )
            contact = self._get_or_create_contact(patient)
            if contact is not None:
                self._audit(
                    "whatsapp_contact_mapped",
                    "whatsapp_contact",
                    contact.id,
                    new_data={"phone": contact.phone, "opt_in": contact.opt_in},
                )
        return patient

    # ── Private helpers ──────────────────────────────────────────────────────

    def _get_or_create_contact(self, patient: Patient):
        """
        Atomically get-or-create a WhatsAppContact for the patient's number.

        Priority: patient.whatsapp > patient.phone (whatsapp column is the
        dedicated WA channel; phone is the generic contact fallback).

        Returns None when no usable phone is present — no contact is created.

        Race-safety (eng review A5):
          - select_for_update acquires a row lock when the contact already exists.
          - IntegrityError catch handles the TOCTOU window where another concurrent
            transaction inserts the same phone between our filter and our create.
        """
        phone = (patient.whatsapp or patient.phone or "").strip()
        if not phone:
            return None

        with transaction.atomic():
            existing = WhatsAppContact.objects.select_for_update().filter(phone=phone).first()
            if existing is not None:
                # Re-link contact to this patient on re-registration.
                if existing.patient_id != patient.id:
                    existing.patient = patient
                    existing.save(update_fields=["patient"])
                return existing

            try:
                return WhatsAppContact.objects.create(
                    phone=phone,
                    patient=patient,
                    opt_in=False,
                )
            except IntegrityError:
                # Another transaction beat us to the insert — fetch and re-link.
                existing = WhatsAppContact.objects.get(phone=phone)
                if existing.patient_id != patient.id:
                    existing.patient = patient
                    existing.save(update_fields=["patient"])
                return existing

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
