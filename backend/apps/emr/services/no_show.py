"""No-show orchestrator — no-show prediction wedge PR N2.

Bridges the PURE engine (``apps.emr.services.no_show_checker``) to the DB:
resolves every upcoming appointment's patient history (in 2 bounded queries, no
N+1), scores it, and persists a ``NoShowRisk`` row; and a nightly flywheel that
grades past predictions by what actually happened. The engine DECIDES; this
service persists. Mirrors ``pharmacy.services.stockout_safety.StockoutService``.

Feature flag ``no_show_prediction`` (default OFF) → ``evaluate_window`` is a
no-op. ADVISE/operational only — nothing here blocks booking or check-in.

LEAKAGE GUARDS (locked in eng-review):
- Only FUTURE appointments are scored (`start_time >= now`); the engine is never
  fed a past appointment, so lifetime terminal history is strictly prior.
- History = terminal (``completed`` + ``no_show``) appointments only; ``cancelled``
  is excluded from BOTH numerator and denominator.
- The consecutive-no-show run is sliced to terminal appointments strictly before
  each appointment's ``start_time`` (defensive; for future appointments this is
  all of them).
- ``lead_time`` computed tz-aware, clamped ≥ 0.
"""

from __future__ import annotations

import datetime
import logging
from collections import defaultdict
from uuid import uuid4

from django.db import connection, transaction

from apps.core.models import AuditLog
from apps.core.utils import tenant_has_feature
from apps.emr.services.no_show_checker import ENGINE_VERSION, score_no_show

logger = logging.getLogger(__name__)

NO_SHOW_FEATURE_KEY = "no_show_prediction"
DEFAULT_HORIZON_DAYS = 7
_UPCOMING_STATUSES = ("scheduled", "confirmed", "waiting")
_TERMINAL_STATUSES = ("completed", "no_show")


class NoShowService:
    def __init__(self, *, requesting_user=None) -> None:
        self.requesting_user = requesting_user
        self.correlation_id = str(uuid4())

    @classmethod
    def is_enabled(cls) -> bool:
        try:
            tenant = connection.tenant  # type: ignore[attr-defined]
            return tenant_has_feature(tenant, NO_SHOW_FEATURE_KEY)
        except Exception:
            logger.warning(
                "Could not resolve no_show_prediction feature flag; defaulting to disabled.",
                exc_info=True,
            )
            return False

    # ── evaluation (proactive nightly job over the upcoming window) ───────────

    def evaluate_window(
        self, *, now: datetime.datetime, horizon_days: int = DEFAULT_HORIZON_DAYS
    ) -> dict[str, int]:
        """Score every upcoming appointment in [now, now+horizon] and persist.

        No-op (returns zero counts) when the flag is off. Three bounded queries,
        no per-appointment DB hits.
        """
        counts = {"scored": 0, "inert": 0}
        if not self.is_enabled():
            return counts

        from apps.emr.models import Appointment

        window_end = now + datetime.timedelta(days=horizon_days)
        upcoming = list(
            Appointment.objects.filter(
                status__in=_UPCOMING_STATUSES,
                start_time__gte=now,
                start_time__lte=window_end,
            ).select_related("patient", "professional")
        )
        if not upcoming:
            return counts

        patient_ids = {a.patient_id for a in upcoming}

        # Query 2: ALL terminal rows for these patients, newest-first, in ONE query.
        # We compute the lifetime counts AND the consecutive-no-show run from this
        # single ordered result in Python — no per-appointment query, and no
        # ``.values().annotate()`` aggregate (which trips a django-stubs/mypy bug).
        ordered = (
            Appointment.objects.filter(patient_id__in=patient_ids, status__in=_TERMINAL_STATUSES)
            .order_by("patient_id", "-start_time")
            .values_list("patient_id", "start_time", "status")
        )
        terminal_by_patient: dict = defaultdict(list)
        for pid, start_time, status in ordered:
            terminal_by_patient[pid].append((start_time, status))

        for appt in upcoming:
            history = terminal_by_patient.get(appt.patient_id, [])
            # History is strictly prior for future appointments; slice defensively.
            prior = [(st, s) for st, s in history if st < appt.start_time]
            terminal = len(prior)
            no_shows = sum(1 for _, s in prior if s == "no_show")
            consecutive = self._consecutive_no_shows(prior, appt.start_time)
            lead_days = max(0, (appt.start_time - appt.created_at).days)
            verdict = score_no_show(
                no_shows=no_shows,
                terminal=terminal,
                consecutive_no_shows=consecutive,
                whatsapp_reminder_sent=appt.whatsapp_reminder_sent,
                whatsapp_confirmed=appt.whatsapp_confirmed,
                lead_time_days=lead_days,
                source=appt.source,
                appointment_type=appt.type,
            )
            if verdict is None:
                counts["inert"] += 1
                continue
            self._persist(appt, verdict)
            counts["scored"] += 1

        return counts

    @staticmethod
    def _consecutive_no_shows(terminal_desc: list, before: datetime.datetime) -> int:
        """Trailing run of no_show among terminal appts strictly before ``before``.

        ``terminal_desc`` is (start_time, status) newest-first. Counts leading
        no_shows until the first completed.
        """
        run = 0
        for start_time, status in terminal_desc:
            if start_time >= before:  # leakage guard (defensive for future appts)
                continue
            if status == "no_show":
                run += 1
            else:
                break
        return run

    def _persist(self, appt, verdict) -> None:
        from apps.emr.models import NoShowRisk

        with transaction.atomic():
            existing = NoShowRisk.objects.select_for_update().filter(appointment=appt).first()
            # Override-preservation: an acknowledged risk whose band is UNCHANGED
            # stands — don't reopen/spam on the nightly re-evaluation.
            if (
                existing is not None
                and existing.status == NoShowRisk.Status.ACKNOWLEDGED
                and existing.band == verdict.band
            ):
                return
            NoShowRisk.objects.update_or_create(
                appointment=appt,
                defaults={
                    "score": verdict.score,
                    "band": verdict.band,
                    "breakdown": verdict.breakdown,
                    "suggested_action": verdict.suggested_action,
                    "status": NoShowRisk.Status.OPEN,
                    "outcome": NoShowRisk.Outcome.PENDING,
                    "engine_version": verdict.engine_version,
                    "acknowledged_by": None,
                    "acknowledged_at": None,
                    "note": "",
                    "graded_at": None,
                },
            )

    # ── flywheel grading (after start_time passes) ────────────────────────────

    def grade_predictions(self, *, now: datetime.datetime) -> dict[str, int]:
        """Grade past-due predictions whose appointment reached a terminal status.

        medium+high = predicted-positive, low = predicted-negative. Appointments
        that ended ``cancelled`` are excluded entirely (stay pending). Idempotent:
        only ``outcome=pending`` rows are candidates. Flag-independent (only grades
        existing rows). Returns counts per outcome.
        """
        from apps.emr.models import NoShowRisk

        Outcome = NoShowRisk.Outcome
        counts = {o.value: 0 for o in Outcome if o != Outcome.PENDING}

        candidates = (
            NoShowRisk.objects.filter(
                outcome=Outcome.PENDING,
                appointment__start_time__lt=now,
                appointment__status__in=_TERMINAL_STATUSES,
            )
            .select_related("appointment")
            .order_by("created_at")
        )
        for risk in candidates:
            actual_no_show = risk.appointment.status == "no_show"
            predicted_positive = risk.band in (NoShowRisk.Band.MEDIUM, NoShowRisk.Band.HIGH)
            if actual_no_show:
                outcome = Outcome.TRUE_POSITIVE if predicted_positive else Outcome.FALSE_NEGATIVE
            else:  # completed
                outcome = Outcome.FALSE_POSITIVE if predicted_positive else Outcome.TRUE_NEGATIVE

            with transaction.atomic():
                risk.outcome = outcome
                risk.graded_at = now
                risk.save(update_fields=["outcome", "graded_at"])
                self._audit_graded(risk, outcome)
            counts[outcome.value] += 1

        return counts

    def _audit_graded(self, risk, outcome) -> None:
        AuditLog.objects.create(
            user=self.requesting_user,
            action="no_show_prediction_graded",
            resource_type="no_show_risk",
            resource_id=str(risk.id),
            new_data={
                "correlation_id": self.correlation_id,
                "appointment_id": str(risk.appointment_id),
                "band": risk.band,
                "score": str(risk.score),
                "actual_status": risk.appointment.status,
                "outcome": outcome.value if hasattr(outcome, "value") else outcome,
                "engine_version": ENGINE_VERSION,
            },
        )
