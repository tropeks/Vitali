"""Patient registration cascade service — Sprint 19 / S-080 / F-04 (E-013).

Locked architecture decisions (from /plan-eng-review v2 + /autoplan):
  1A — Service-layer orchestrator, NOT Django signals.
  2A — AuditLog correlation_id in new_data JSON for full cascade tracing.

Race-safety decision (eng review A5):
  select_for_update + IntegrityError catch on WhatsAppContact creation.

F-04 (E-013) — full cascade on Patient creation:
  1. Gate the WhatsApp cascade behind the tenant's ``whatsapp`` module flag.
  2. When the module is active and a brand-new WhatsAppContact is created for a
     not-yet-decided number, enqueue the welcome + opt-in invitation
     (async via Celery / transaction.on_commit so the API stays well under 30s).
     The invitation dispatch is additionally gated behind the default-OFF
     ``whatsapp_cold_optin`` tenant flag — see _cold_optin_enabled for why.

  NOTE (pre-merge review, PR #145): the cascade previously pre-created an empty
  MedicalHistory(condition="", type="") placeholder. That was removed —
  MedicalHistory is a *list of clinical entries* (chronic/acute/surgical/family)
  with no per-item PATCH/DELETE in the API, so the placeholder polluted every
  new patient's chart with a permanent blank row. Real entries are created on
  demand via POST /medical-history/.

  The post-opt-in welcome handshake (after the patient replies) lives in the FSM
  opt-in transition (S-110: WhatsAppContact.do_opt_in → send_post_opt_in_welcome).

Usage:
    service = PatientRegistrationService(requesting_user=request.user)
    service.register(patient)  # patient already saved by serializer.save()
"""

import logging
from uuid import uuid4

from django.db import IntegrityError, connection, transaction

from apps.core.models import AuditLog
from apps.core.utils import tenant_has_feature
from apps.emr.models import Patient
from apps.whatsapp.models import WhatsAppContact

logger = logging.getLogger(__name__)

WHATSAPP_MODULE_KEY = "whatsapp"
COLD_OPTIN_FLAG_KEY = "whatsapp_cold_optin"


class PatientRegistrationService:
    """
    Orchestrates the post-save Patient cascade (F-04 / E-013):
      1. AuditLog entry for the patient creation (with correlation_id).
      2. If the tenant's ``whatsapp`` module is active:
         a. Atomic WhatsAppContact get-or-create (race-safe).
         b. AuditLog entry for the WhatsApp contact mapping.
         c. For a brand-new, not-yet-decided contact — and only when the
            default-OFF ``whatsapp_cold_optin`` tenant flag is enabled —
            enqueue the welcome + opt-in invitation (async, fail-open).
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
            # F-04: the WhatsApp cascade is gated on the tenant module.
            if not self._whatsapp_module_active():
                return patient

            contact, created = self._get_or_create_contact(patient)
            if contact is not None:
                self._audit(
                    "whatsapp_contact_mapped",
                    "whatsapp_contact",
                    contact.id,
                    new_data={"phone": contact.phone, "opt_in": contact.opt_in},
                )
                # Send the welcome + opt-in invitation only for a brand-new
                # contact whose consent has not yet been decided, and only when
                # the tenant has explicitly enabled cold outbound opt-in.
                if (
                    created
                    and not contact.opt_in
                    and contact.opt_out_at is None
                    and self._cold_optin_enabled()
                ):
                    self._enqueue_opt_in_invitation(contact)
        return patient

    # ── Private helpers ──────────────────────────────────────────────────────

    def _whatsapp_module_active(self) -> bool:
        """Return whether the current tenant has the ``whatsapp`` module enabled.

        Fail-closed: any error resolving the tenant/flag (e.g. no tenant on the
        connection in a non-request context) disables the WhatsApp cascade.
        """
        try:
            tenant = connection.tenant  # type: ignore[attr-defined]
            return tenant_has_feature(tenant, WHATSAPP_MODULE_KEY)
        except Exception:
            logger.warning(
                "Could not resolve whatsapp module flag; skipping WhatsApp cascade.",
                exc_info=True,
            )
            return False

    def _cold_optin_enabled(self) -> bool:
        """Return whether the tenant explicitly enabled cold outbound opt-in.

        The opt-in invitation is a *business-initiated, freeform* WhatsApp
        message to a number that has never interacted with the channel. On
        Baileys/Evolution-style gateways that pattern is a well-known trigger
        for the provider banning the sender number — which would take down the
        tenant's entire WhatsApp channel. The dispatch is therefore gated
        behind the dedicated ``whatsapp_cold_optin`` FeatureFlag, which is
        default-OFF (no row → disabled): the cascade lands inert and an
        operator enables the flag explicitly once an approved template /
        messaging window strategy is in place.

        Fail-closed, mirroring _whatsapp_module_active: any error resolving
        the tenant/flag disables the invitation dispatch.
        """
        try:
            tenant = connection.tenant  # type: ignore[attr-defined]
            return tenant_has_feature(tenant, COLD_OPTIN_FLAG_KEY)
        except Exception:
            logger.warning(
                "Could not resolve whatsapp_cold_optin flag; skipping opt-in invitation dispatch.",
                exc_info=True,
            )
            return False

    def _enqueue_opt_in_invitation(self, contact) -> None:
        """Enqueue the welcome + opt-in invitation after the transaction commits.

        Deferred via transaction.on_commit so the Celery worker only fires once
        the contact row is durable, and so the synchronous API request returns
        immediately (acceptance criterion: opt-in dispatched in < 30s).
        """
        from apps.whatsapp.tasks import send_opt_in_invitation

        contact_id = str(contact.id)
        correlation_id = self.correlation_id
        self._audit(
            "opt_in_invitation_enqueued",
            "whatsapp_contact",
            contact.id,
            new_data={"phone": contact.phone},
        )
        transaction.on_commit(lambda: send_opt_in_invitation.delay(contact_id, correlation_id))

    def _get_or_create_contact(self, patient: Patient):
        """
        Atomically get-or-create a WhatsAppContact for the patient's number.

        Priority: patient.whatsapp > patient.phone (whatsapp column is the
        dedicated WA channel; phone is the generic contact fallback).

        Returns a ``(contact, created)`` tuple, or ``(None, False)`` when no
        usable phone is present — no contact is created.

        Race-safety (eng review A5):
          - select_for_update acquires a row lock when the contact already exists.
          - IntegrityError catch handles the TOCTOU window where another concurrent
            transaction inserts the same phone between our filter and our create.
        """
        phone = (patient.whatsapp or patient.phone or "").strip()
        if not phone:
            return None, False

        with transaction.atomic():
            existing = WhatsAppContact.objects.select_for_update().filter(phone=phone).first()
            if existing is not None:
                # Re-link contact to this patient on re-registration.
                if existing.patient_id != patient.id:
                    existing.patient = patient
                    existing.save(update_fields=["patient"])
                return existing, False

            try:
                contact = WhatsAppContact.objects.create(
                    phone=phone,
                    patient=patient,
                    opt_in=False,
                )
                return contact, True
            except IntegrityError:
                # Another transaction beat us to the insert — fetch and re-link.
                existing = WhatsAppContact.objects.get(phone=phone)
                if existing.patient_id != patient.id:
                    existing.patient = patient
                    existing.save(update_fields=["patient"])
                return existing, False

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
