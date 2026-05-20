"""
Phase 3 Patient Portal backend primitive.

This module is the backend half of E-013 (Portal do Paciente). It does NOT
include:

- The patient-facing Next.js app (frontend project, separate scope).
- LGPD consent flows beyond the audit-trail of `invited_at` /
  `activated_at` / `revoked_at` timestamps — full consent UI lives in the
  portal frontend.
- WhatsApp / email invite delivery — the invite_token is materialised here
  and the actual delivery is a follow-up integration.

The split is deliberate: clinics can mint portal access for patients today
(via REST or admin), and an integrator can deliver the invite token through
any channel until the bundled frontend ships. The backend primitive is
useful on day one for partners building their own patient app.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import timedelta

from django.db import models
from django.utils import timezone

from apps.core.models import User
from apps.emr.models import Patient


def _generate_invite_token() -> str:
    """A URL-safe 32-byte token, ~43 chars."""
    return secrets.token_urlsafe(32)


class PatientPortalAccess(models.Model):
    """Binds one `core.User` account to one EMR `Patient` for portal access."""

    STATUS_INVITED = "invited"
    STATUS_ACTIVE = "active"
    STATUS_REVOKED = "revoked"

    STATUS_CHOICES = [
        (STATUS_INVITED, "Convidado"),
        (STATUS_ACTIVE, "Ativo"),
        (STATUS_REVOKED, "Revogado"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="patient_portal_access"
    )
    patient = models.OneToOneField(Patient, on_delete=models.CASCADE, related_name="portal_access")

    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_INVITED, db_index=True
    )
    invite_token = models.CharField(
        max_length=64, default=_generate_invite_token, unique=True, db_index=True
    )
    invite_expires_at = models.DateTimeField()

    invited_at = models.DateTimeField(auto_now_add=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="portal_invites_created",
    )

    class Meta:
        ordering = ["-invited_at"]
        indexes = [
            models.Index(fields=["status", "-invited_at"], name="portal_status_idx"),
        ]
        verbose_name_plural = "patient portal access"

    def __str__(self) -> str:
        return f"Portal {self.patient_id} ({self.status})"

    def save(self, *args, **kwargs):
        if not self.invite_expires_at:
            self.invite_expires_at = timezone.now() + timedelta(days=7)
        super().save(*args, **kwargs)

    # ─── State transitions ────────────────────────────────────────────────────

    def is_invite_valid(self) -> bool:
        return (
            self.status == self.STATUS_INVITED
            and self.invite_expires_at is not None
            and timezone.now() <= self.invite_expires_at
        )

    def activate(self) -> None:
        if self.status != self.STATUS_INVITED:
            raise ValueError(
                f"Portal access can only be activated from 'invited' (was '{self.status}')."
            )
        if not self.is_invite_valid():
            raise ValueError("Invite token has expired.")
        self.status = self.STATUS_ACTIVE
        self.activated_at = timezone.now()
        self.save(update_fields=["status", "activated_at"])

    def revoke(self) -> None:
        if self.status == self.STATUS_REVOKED:
            return
        self.status = self.STATUS_REVOKED
        self.revoked_at = timezone.now()
        self.save(update_fields=["status", "revoked_at"])

    def touch(self) -> None:
        """Update last_seen_at on every authenticated self-data request."""
        self.last_seen_at = timezone.now()
        self.save(update_fields=["last_seen_at"])
