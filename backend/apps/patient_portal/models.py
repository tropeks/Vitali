"""
Phase 3 Patient Portal backend primitive.

This module is the backend half of E-013 (Portal do Paciente). It does NOT
include:

- The patient-facing Next.js app (frontend project, separate scope).
- LGPD consent flows beyond the audit-trail of `invited_at` /
  `activated_at` / `revoked_at` timestamps — full consent UI lives in the
  portal frontend.
- WhatsApp / email invite delivery — the invite token is minted here and
  delivered by ``apps.patient_portal.services.invite_delivery``.

The split is deliberate: clinics can mint portal access for patients today
(via REST or admin), and an integrator can deliver the invite token through
any channel until the bundled frontend ships. The backend primitive is
useful on day one for partners building their own patient app.
"""

from __future__ import annotations

import hashlib
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


def hash_invite_token(token: str) -> str:
    """What the database keeps instead of the token (order 033).

    SHA-256 is enough: the token is 256 random bits, so there is no dictionary
    to attack, and the lookup stays an index hit. Migration 0004 hashes the
    tokens of existing rows with this same function (``sha256_hex`` there).
    """
    return hashlib.sha256(token.encode()).hexdigest()


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
    # Only the hash is stored for new invites (order 033): a dump or backup of
    # this table must not hand out every open invite. The plaintext exists on
    # the instance that minted it (``invite_token`` below), for delivery and the
    # 201, and never comes back from the database.
    #
    # Phase 1 of the two-phase rule (docs/TENANT_MIGRATIONS.md): the hash is
    # nullable and the pre-033 plaintext column stays, nullable, as
    # ``invite_token_legado``, so the previous release still runs against this
    # schema. Order 034 (phase 2) makes the hash NOT NULL and drops the column.
    #
    # NULL, not "", on both (DJ001 silenced on purpose): they are unique, and
    # only NULLs do not collide — two empty strings would.
    invite_token_hash = models.CharField(  # noqa: DJ001
        max_length=64, unique=True, null=True, editable=False
    )
    invite_token_legado = models.CharField(  # noqa: DJ001
        max_length=64, db_column="invite_token", unique=True, null=True, editable=False
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

    #: Plaintext invite token: set only on the instance that minted it, never
    #: persisted. ``None`` on any instance loaded from the database.
    invite_token: str | None = None

    def save(self, *args, **kwargs):
        if self._state.adding and not self.invite_token_hash:
            self.invite_token = _generate_invite_token()
            self.invite_token_hash = hash_invite_token(self.invite_token)
        if not self.invite_expires_at:
            self.invite_expires_at = timezone.now() + timedelta(days=7)
        super().save(*args, **kwargs)

    @classmethod
    def find_by_invite_token(cls, token: str) -> PatientPortalAccess:
        """The access whose invite *token* this is — by hash.

        Fallback (phase 1 only, removed by order 034): a row written by the
        previous release has the plaintext and no hash. It is matched by value
        only when its hash is NULL, and gets its hash on the way out.
        """
        digest = hash_invite_token(token)
        try:
            return cls.objects.get(invite_token_hash=digest)
        except cls.DoesNotExist:
            access = cls.objects.get(invite_token_hash__isnull=True, invite_token_legado=token)
            access.invite_token_hash = digest
            access.save(update_fields=["invite_token_hash"])
            return access

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
        # A spent invite needs no token: the pre-033 plaintext goes with it.
        self.invite_token_legado = None
        self.save(update_fields=["status", "activated_at", "invite_token_legado"])

    def revoke(self) -> None:
        if self.status == self.STATUS_REVOKED:
            return
        self.status = self.STATUS_REVOKED
        self.revoked_at = timezone.now()
        self.invite_token_legado = None
        self.save(update_fields=["status", "revoked_at", "invite_token_legado"])

    def touch(self) -> None:
        """Update last_seen_at on every authenticated self-data request."""
        self.last_seen_at = timezone.now()
        self.save(update_fields=["last_seen_at"])


class PatientRepresentative(models.Model):
    """Delegated portal relationship (guardian, parent or caregiver)."""

    RELATION_CHOICES = [
        ("guardian", "Responsável"),
        ("parent", "Parente"),
        ("caregiver", "Cuidador"),
        ("other", "Outro"),
    ]
    patient = models.ForeignKey(
        Patient, on_delete=models.CASCADE, related_name="portal_representatives"
    )
    representative = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="portal_patient_relationships"
    )
    relationship = models.CharField(max_length=20, choices=RELATION_CHOICES, default="guardian")
    active = models.BooleanField(default=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    granted_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["patient", "representative"], name="portal_rep_unique")
        ]

    def is_valid(self):
        return self.active and (self.expires_at is None or timezone.now() < self.expires_at)

    def __str__(self):
        return f"{self.representative} → {self.patient}"


class PortalConsent(models.Model):
    """Versioned, auditable consent granted by a patient or representative."""

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="portal_consents")
    granted_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name="portal_consents_granted"
    )
    purpose = models.CharField(max_length=80)
    policy_version = models.CharField(max_length=30)
    granted_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["patient", "purpose"], name="portal_consent_patient_idx")]

    def is_valid(self):
        return self.revoked_at is None and (
            self.expires_at is None or timezone.now() < self.expires_at
        )

    def __str__(self):
        return f"{self.patient} — {self.purpose}"


from .transactional_models import *  # noqa: E402,F401,F403
