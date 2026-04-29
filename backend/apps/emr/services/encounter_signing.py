"""Encounter signing cascade service — Sprint 21 / S-100 / F-03.

Locked architecture decisions (from /autoplan + /plan-eng-review):
  1A — Service-layer orchestrator, NOT Django signals.
  1B — atomic DB block + transaction.on_commit fail-open for WhatsApp.
  2A — AuditLog correlation_id in new_data JSON for full cascade tracing.

LGPD posture (Sprint 19 D2 carries forward):
  WhatsApp follow-up gated by WhatsAppContact.opt_in.
  Patients without an opted-in contact get a silent no-op (no message,
  no failure). The Encounter row still gets signed.

DROPPED from spec: auto-TISSGuide creation at sign time.
  There is no EncounterProcedure model in the codebase. TISSGuides today
  are composed manually by billing staff. Creating an empty stub adds
  confusion. Real auto-TISS needs EncounterProcedure (Sprint 23+ candidate).

Usage:
    service = EncounterSigningService(requesting_user=request.user)
    encounter = service.sign(encounter)  # raises ValueError if not open
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import uuid4

from django.db import transaction
from django.utils import timezone

from apps.core.models import AuditLog
from apps.emr.tasks import send_post_visit_followup_whatsapp
from apps.whatsapp.models import WhatsAppContact

if TYPE_CHECKING:
    from apps.emr.models import Encounter

logger = logging.getLogger(__name__)

FOLLOWUP_DELAY_SECONDS = 86400  # 24h


class EncounterSigningService:
    """
    Service-layer orchestrator for F-03 Encounter-signed cascade.

    Locked decisions:
      1A — service-layer (NOT signals)
      1B — atomic DB block + transaction.on_commit fail-open for follow-up
      2A — AuditLog correlation_id propagated to the Celery task

    LGPD posture (Sprint 19 D2 carries): follow-up WhatsApp gated by
    WhatsAppContact.opt_in. Patients without an opted-in contact get a
    silent skip (no message, no failure). Encounter signing still proceeds.
    """

    def __init__(self, requesting_user) -> None:
        self.requesting_user = requesting_user
        self.correlation_id = str(uuid4())

    def sign(self, encounter: Encounter) -> Encounter:
        """
        Sign the encounter + cascade. Caller has already verified status==open.
        Raises ValueError if already signed (defensive — view should pre-check).

        Args:
            encounter: the open Encounter instance to sign.

        Returns:
            The same Encounter instance with status='signed', signed_at, signed_by set.
        """
        if encounter.status != "open":
            raise ValueError("Apenas consultas abertas podem ser assinadas.")

        with transaction.atomic():
            encounter.status = "signed"
            encounter.signed_at = timezone.now()
            encounter.signed_by = self.requesting_user
            encounter.save(update_fields=["status", "signed_at", "signed_by", "updated_at"])

            self._audit(
                "encounter_signed",
                "encounter",
                encounter.id,
                new_data={
                    "patient_id": str(encounter.patient_id),
                    "professional_id": str(encounter.professional_id),
                    "signed_at": encounter.signed_at.isoformat(),
                },
            )

            # Schedule 24h follow-up if patient has an opted-in contact
            contact = WhatsAppContact.objects.filter(patient=encounter.patient, opt_in=True).first()
            if contact:
                encounter_id = str(encounter.id)
                correlation_id = self.correlation_id
                transaction.on_commit(
                    lambda: send_post_visit_followup_whatsapp.apply_async(
                        args=[encounter_id, correlation_id],
                        countdown=FOLLOWUP_DELAY_SECONDS,
                    )
                )
                self._audit(
                    "followup_scheduled",
                    "encounter",
                    encounter.id,
                    new_data={"countdown_seconds": FOLLOWUP_DELAY_SECONDS},
                )
            else:
                self._audit(
                    "followup_skipped",
                    "encounter",
                    encounter.id,
                    new_data={"reason": "no_opted_in_contact"},
                )

        return encounter

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
