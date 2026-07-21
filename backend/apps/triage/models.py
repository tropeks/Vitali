"""
Phase 3 Triagem Inteligente — session state primitive.

A `TriageSession` walks a patient through a fixed question bank (see
`apps.triage.services.question_bank`) and ends with an urgency
classification (`routine` / `urgent` / `emergency`). When `emergency`
fires the session is auto-escalated and clinical staff must be paged
(CFM Res. 2.314/2022 §6 — non-presential triage must escalate to a
licensed professional when a red flag fires; this layer just records
the decision so the WhatsApp / portal frontend can dispatch the page).

The WhatsApp signalling layer (gateway already in `apps.whatsapp`) wraps
this primitive: each inbound message becomes an `answer()` call, the
session walks forward, and the WhatsApp send-message hook turns the next
`current_question` into an outbound message. Wiring that up is a
deploy-time integration; the FSM contract here is the swap-in point.
"""

import uuid

from django.db import models
from django.utils import timezone

from apps.core.models import User
from apps.emr.models import Patient

from .services.evaluator import (
    URGENCY_EMERGENCY,
    URGENCY_ROUTINE,
    URGENCY_URGENT,
    evaluate,
)
from .services.question_bank import RED_FLAG_QUESTIONS, question_by_key, question_keys


class TriageSession(models.Model):
    """One triage interaction with a patient."""

    STATUS_STARTED = "started"
    STATUS_ANSWERING = "answering"
    STATUS_EVALUATED = "evaluated"
    STATUS_ESCALATED = "escalated"
    STATUS_COMPLETED = "completed"
    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = [
        (STATUS_STARTED, "Iniciada"),
        (STATUS_ANSWERING, "Respondendo"),
        (STATUS_EVALUATED, "Avaliada"),
        (STATUS_ESCALATED, "Escalonada"),
        (STATUS_COMPLETED, "Concluída"),
        (STATUS_CANCELLED, "Cancelada"),
    ]

    URGENCY_CHOICES = [
        (URGENCY_ROUTINE, "Rotina"),
        (URGENCY_URGENT, "Urgente"),
        (URGENCY_EMERGENCY, "Emergência"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey(
        Patient,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="triage_sessions",
        help_text="Optional — anonymous WhatsApp triage may not have a patient match yet.",
    )
    contact_phone = models.CharField(max_length=20, blank=True, db_index=True)
    chief_complaint = models.TextField(blank=True)
    answers = models.JSONField(default=dict, blank=True)

    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_STARTED, db_index=True
    )
    urgency = models.CharField(max_length=20, choices=URGENCY_CHOICES, blank=True, db_index=True)
    rationale = models.TextField(blank=True)
    matched_keywords = models.JSONField(default=list, blank=True)
    red_flags_positive = models.PositiveSmallIntegerField(default=0)

    started_at = models.DateTimeField(auto_now_add=True)
    evaluated_at = models.DateTimeField(null=True, blank=True)
    escalated_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="triage_sessions_created",
    )

    class Meta:
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["status", "-started_at"], name="triage_status_idx"),
            models.Index(fields=["urgency", "-started_at"], name="triage_urgency_idx"),
        ]

    def __str__(self) -> str:
        return f"Triage {self.id} ({self.status}/{self.urgency or '?'})"

    # ─── State helpers ────────────────────────────────────────────────────────

    @property
    def next_question_key(self) -> str | None:
        for key in question_keys():
            if key not in (self.answers or {}):
                return key
        return None

    def current_question(self):
        key = self.next_question_key
        return question_by_key(key) if key else None

    def all_answered(self) -> bool:
        return self.next_question_key is None and bool(self.chief_complaint)

    # ─── Transitions ──────────────────────────────────────────────────────────

    def record_chief_complaint(self, text: str) -> None:
        if self.status in (
            self.STATUS_COMPLETED,
            self.STATUS_CANCELLED,
            self.STATUS_ESCALATED,
        ):
            raise ValueError(f"Cannot edit a triage in '{self.status}' state.")
        self.chief_complaint = (text or "").strip()
        if self.status == self.STATUS_STARTED:
            self.status = self.STATUS_ANSWERING
        self.save(update_fields=["chief_complaint", "status"])

    def answer(self, key: str, value: str) -> None:
        if self.status in (
            self.STATUS_COMPLETED,
            self.STATUS_CANCELLED,
            self.STATUS_ESCALATED,
            self.STATUS_EVALUATED,
        ):
            raise ValueError(f"Cannot answer a triage in '{self.status}' state.")
        if question_by_key(key) is None:
            raise ValueError(f"Unknown question key '{key}'.")
        current = self.answers or {}
        current[key] = (value or "").strip().lower()
        self.answers = current
        if self.status == self.STATUS_STARTED:
            self.status = self.STATUS_ANSWERING
        self.save(update_fields=["answers", "status"])

    def evaluate_now(self) -> None:
        if self.status in (
            self.STATUS_EVALUATED,
            self.STATUS_ESCALATED,
            self.STATUS_COMPLETED,
            self.STATUS_CANCELLED,
        ):
            raise ValueError(f"Cannot re-evaluate a triage in '{self.status}' state.")
        if not self.all_answered():
            raise ValueError("Cannot evaluate: chief complaint or answers missing.")
        decision = evaluate(self.chief_complaint, self.answers or {})
        self.urgency = decision.urgency
        self.rationale = decision.rationale
        self.matched_keywords = decision.matched_keywords
        self.red_flags_positive = decision.red_flags_positive
        self.evaluated_at = timezone.now()
        self.status = self.STATUS_EVALUATED
        if decision.urgency == URGENCY_EMERGENCY:
            self.status = self.STATUS_ESCALATED
            self.escalated_at = self.evaluated_at
        self.save(
            update_fields=[
                "urgency",
                "rationale",
                "matched_keywords",
                "red_flags_positive",
                "evaluated_at",
                "escalated_at",
                "status",
            ]
        )

    def complete(self) -> None:
        if self.status not in (self.STATUS_EVALUATED, self.STATUS_ESCALATED):
            raise ValueError(f"Cannot complete a triage in '{self.status}' state.")
        self.closed_at = timezone.now()
        self.status = self.STATUS_COMPLETED
        self.save(update_fields=["closed_at", "status"])

    def cancel(self) -> None:
        if self.status == self.STATUS_COMPLETED:
            raise ValueError("Cannot cancel a completed triage.")
        self.closed_at = timezone.now()
        self.status = self.STATUS_CANCELLED
        self.save(update_fields=["closed_at", "status"])

    def abandon(self, reason: str = "") -> bool:
        """Close an abandoned (incomplete) triage, evaluating partial evidence first.

        Unlike ``evaluate_now`` this does NOT require every question to be
        answered: the evaluator treats missing answers as "no evidence", so a
        chief complaint containing an emergency keyword (e.g. "dor no peito")
        still classifies as ``emergency`` even if the patient went silent
        (CFM Res. 2.314/2022 §6 — a known red flag must escalate regardless
        of how the conversation ended).

        Returns True when the partial evidence classifies as emergency — the
        session is then ESCALATED (not CANCELLED) so callers can page staff.
        Terminal sessions (evaluated/escalated/completed/cancelled) are left
        untouched and return False so callers never double-page.
        """
        if self.status not in (self.STATUS_STARTED, self.STATUS_ANSWERING):
            return False
        now = timezone.now()
        decision = evaluate(self.chief_complaint, self.answers or {})
        prefix = f"[abandoned{f': {reason}' if reason else ''}] "
        self.urgency = decision.urgency
        self.rationale = prefix + decision.rationale
        self.matched_keywords = decision.matched_keywords
        self.red_flags_positive = decision.red_flags_positive
        self.evaluated_at = now
        self.closed_at = now
        if decision.urgency == URGENCY_EMERGENCY:
            self.status = self.STATUS_ESCALATED
            self.escalated_at = now
        else:
            self.status = self.STATUS_CANCELLED
        self.save(
            update_fields=[
                "urgency",
                "rationale",
                "matched_keywords",
                "red_flags_positive",
                "evaluated_at",
                "escalated_at",
                "closed_at",
                "status",
            ]
        )
        return decision.urgency == URGENCY_EMERGENCY


# Keep direct imports stable for callers that prefer the constants here.
__all__ = ["TriageSession", "RED_FLAG_QUESTIONS"]
