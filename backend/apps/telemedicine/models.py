"""
Phase 3 Telemedicine session tracking primitive.

This module is the *session lifecycle* layer of the telemedicine epic. It
does NOT include:

- WebRTC infrastructure (Janus / Jitsi / a TURN/STUN server)
- Video recording storage / encryption-at-rest pipeline
- Per-tenant SFU multiplexing

Those are deploy-time concerns. The tracking primitive shipped here is
sufficient to:

1. Schedule a telemed session against an `Appointment` (or stand-alone).
2. Move it through `scheduled → in_progress → completed | cancelled` via
   explicit transition endpoints (so the audit trail is unambiguous, CFM
   Res. 2.314/2022 §3 requires logging the start/end of every telemedicine
   session).
3. Carry a `room_uid` that the eventual WebRTC layer can route by.
4. Optionally record a post-session `recording_url` once a recording flow
   is wired up — currently a free-text field; we'll add encryption-at-rest
   handling when storage is provisioned.
"""

import uuid

from django.db import models
from django.utils import timezone

from apps.core.models import User
from apps.emr.models import Appointment, Patient, Professional


class TelemedicineSession(models.Model):
    """One telemedicine session — corresponds to one Appointment when present."""

    STATUS_SCHEDULED = "scheduled"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_COMPLETED = "completed"
    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = [
        (STATUS_SCHEDULED, "Agendada"),
        (STATUS_IN_PROGRESS, "Em atendimento"),
        (STATUS_COMPLETED, "Concluída"),
        (STATUS_CANCELLED, "Cancelada"),
    ]

    # Valid transitions: scheduled → in_progress | cancelled;
    # in_progress → completed | cancelled. Terminal states are sinks.
    ALLOWED_TRANSITIONS = {
        STATUS_SCHEDULED: {STATUS_IN_PROGRESS, STATUS_CANCELLED},
        STATUS_IN_PROGRESS: {STATUS_COMPLETED, STATUS_CANCELLED},
        STATUS_COMPLETED: set(),
        STATUS_CANCELLED: set(),
    }

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    appointment = models.OneToOneField(
        Appointment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="telemedicine_session",
    )
    patient = models.ForeignKey(
        Patient, on_delete=models.PROTECT, related_name="telemedicine_sessions"
    )
    professional = models.ForeignKey(
        Professional, on_delete=models.PROTECT, related_name="telemedicine_sessions"
    )

    # The `room_uid` is what the WebRTC signalling layer routes by — clients
    # connect to e.g. `/telemed/room/<room_uid>`. We mint a fresh uuid on
    # creation so the room identifier never collides across tenants.
    room_uid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_SCHEDULED, db_index=True
    )

    scheduled_for = models.DateTimeField()
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    duration_seconds = models.PositiveIntegerField(null=True, blank=True)

    # Free-text URL — when a recording pipeline is wired up, this points at
    # the encrypted artifact. Today it's mostly used by integrators that
    # ship recordings to S3 / GCS manually.
    recording_url = models.URLField(blank=True, max_length=500)
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="telemedicine_sessions_created",
    )

    class Meta:
        ordering = ["-scheduled_for"]
        indexes = [
            models.Index(fields=["patient", "-scheduled_for"], name="tele_pat_sched_idx"),
            models.Index(fields=["professional", "-scheduled_for"], name="tele_prof_sched_idx"),
            models.Index(fields=["status", "-scheduled_for"], name="tele_status_idx"),
        ]

    def __str__(self) -> str:
        return f"Telemed {self.id} — {self.patient_id} ({self.status})"

    @property
    def is_terminal(self) -> bool:
        return self.status in (self.STATUS_COMPLETED, self.STATUS_CANCELLED)

    def can_transition_to(self, target: str) -> bool:
        return target in self.ALLOWED_TRANSITIONS.get(self.status, set())

    def start(self) -> None:
        """Move scheduled → in_progress; sets `started_at`."""
        if not self.can_transition_to(self.STATUS_IN_PROGRESS):
            raise ValueError(f"Cannot start session in status '{self.status}'.")
        self.status = self.STATUS_IN_PROGRESS
        self.started_at = timezone.now()
        self.save(update_fields=["status", "started_at"])

    def complete(self) -> None:
        """Move in_progress → completed; computes `duration_seconds`."""
        if not self.can_transition_to(self.STATUS_COMPLETED):
            raise ValueError(f"Cannot complete session in status '{self.status}'.")
        now = timezone.now()
        self.ended_at = now
        if self.started_at is not None:
            self.duration_seconds = int((now - self.started_at).total_seconds())
        self.status = self.STATUS_COMPLETED
        self.save(update_fields=["status", "ended_at", "duration_seconds"])

    def cancel(self) -> None:
        """Cancel from scheduled or in_progress."""
        if not self.can_transition_to(self.STATUS_CANCELLED):
            raise ValueError(f"Cannot cancel session in status '{self.status}'.")
        now = timezone.now()
        if self.started_at is not None and self.ended_at is None:
            self.ended_at = now
            self.duration_seconds = int((now - self.started_at).total_seconds())
        self.status = self.STATUS_CANCELLED
        self.save(update_fields=["status", "ended_at", "duration_seconds"])
