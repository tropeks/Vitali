"""
Sprint M1-S5 — Portal transacional.

Backend state for the three self-service transactional flows the portal now
exposes to an authenticated patient:

* **PortalScheduleRequest** (S5-T1) — an auditable, portal-origin record of a
  self-service scheduling action (book / reschedule / cancel). The clinical
  source of truth stays ``emr.Appointment``; this row is the portal's own
  history of *who requested what through the portal*, gated by a
  ``PortalConsent``.
* **PortalPixPayment** (S5-T2) — bridges an open receivable to the
  ``billing.PIXCharge`` a patient initiated from the portal. ``receivable_ref``
  is stored as an opaque string (not a hard FK) on purpose: Sprint S4 is
  untethering ``AccountsReceivable`` from the TISS guide, so the portal records
  the receivable by reference and lets the parent reconcile the concrete type.
* **PortalPreConsultForm** (S5-T3) — assigns a published
  ``emr.ClinicalFormTemplate`` to an upcoming appointment so the patient can
  fill it in *before* the consult. The filled answers live in an
  ``emr.ClinicalFormResponse`` (encrypted at rest); this row tracks the
  assignment + submission status.

All three flows are LGPD-consent-checked (reusing ``PortalConsent``) and audited
via ``core.AuditLog`` in the views.
"""

from __future__ import annotations

import uuid

from django.db import models


class PortalScheduleRequest(models.Model):
    """Portal-origin audit trail of a self-service scheduling action."""

    ACTION_BOOK = "book"
    ACTION_RESCHEDULE = "reschedule"
    ACTION_CANCEL = "cancel"
    ACTION_CHOICES = [
        (ACTION_BOOK, "Agendar"),
        (ACTION_RESCHEDULE, "Remarcar"),
        (ACTION_CANCEL, "Cancelar"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey(
        "emr.Patient", on_delete=models.CASCADE, related_name="portal_schedule_requests"
    )
    appointment = models.ForeignKey(
        "emr.Appointment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="portal_schedule_requests",
    )
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    consent = models.ForeignKey(
        "patient_portal.PortalConsent",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="schedule_requests",
    )
    requested_by = models.ForeignKey(
        "core.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="portal_schedule_requests",
    )
    detail = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["patient", "-created_at"], name="portal_sched_patient_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.get_action_display()} — {self.patient_id}"


class PortalPixPayment(models.Model):
    """Bridge between an open receivable and the PIX charge raised in the portal."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey(
        "emr.Patient", on_delete=models.CASCADE, related_name="portal_pix_payments"
    )
    # Opaque reference to the receivable (see module docstring — S4 reconciliation).
    receivable_ref = models.CharField(max_length=64, db_index=True)
    pix_charge = models.ForeignKey(
        "billing.PIXCharge",
        on_delete=models.CASCADE,
        related_name="portal_pix_payments",
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    consent = models.ForeignKey(
        "patient_portal.PortalConsent",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pix_payments",
    )
    initiated_by = models.ForeignKey(
        "core.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="portal_pix_payments",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["patient", "-created_at"], name="portal_pix_patient_idx"),
        ]

    def __str__(self) -> str:
        return f"PortalPIX {self.receivable_ref} — R$ {self.amount}"


class PortalPreConsultForm(models.Model):
    """A pre-consult clinical form assigned to an upcoming appointment."""

    STATUS_ASSIGNED = "assigned"
    STATUS_SUBMITTED = "submitted"
    STATUS_CHOICES = [
        (STATUS_ASSIGNED, "Atribuído"),
        (STATUS_SUBMITTED, "Enviado"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    appointment = models.ForeignKey(
        "emr.Appointment",
        on_delete=models.CASCADE,
        related_name="portal_pre_consult_forms",
    )
    template = models.ForeignKey(
        "emr.ClinicalFormTemplate",
        on_delete=models.PROTECT,
        related_name="portal_pre_consult_forms",
    )
    response = models.ForeignKey(
        "emr.ClinicalFormResponse",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="portal_pre_consult_forms",
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_ASSIGNED, db_index=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["appointment", "template"], name="portal_preconsult_unique"
            ),
        ]

    def __str__(self) -> str:
        return f"Pré-consulta {self.template_id} — {self.appointment_id} ({self.status})"


__all__ = [
    "PortalScheduleRequest",
    "PortalPixPayment",
    "PortalPreConsultForm",
]
