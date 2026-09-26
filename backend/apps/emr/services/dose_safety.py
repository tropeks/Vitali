"""Dose-safety orchestrator — dose-safety wedge PR B.

Bridges the PURE deterministic engine (apps.pharmacy.services.dose_checker) to
the EMR side-effects: resolving the patient context (age, latest weight), writing
the engine's verdict to an AISafetyAlert(source="engine"), and recording the
flywheel AuditLog. The engine decides; this service persists.

Locked architecture decisions (mirrors apps.hr.services / encounter_signing):
  1A — service-layer orchestrator, NOT signals.
  1B — atomic DB block; on_commit for any external call (none here today).
  2A — one AuditLog per side-effect, all sharing this run's correlation_id.

Fail posture (locked fail decision table, plan §2.6):
  OUT_OF_RANGE / WEIGHT_GATE → BLOCKING engine alert (severity=contraindication,
      status=flagged) → the gate raises 409 until acknowledged-with-reason.
  DATA_MISSING / ENGINE_ERROR → ADVISORY alert (severity=caution, status=flagged)
      — NOT a silent green, NOT a hard block. The gate still allows the action.
  SAFE → resolve any stale engine 'dose' alert to status="safe".
  NOT_APPLICABLE → nothing.

Ordem 028 — a nao_validado rule only SIGNALS, never blocks: a verdict that
would otherwise BLOCK (OUT_OF_RANGE with enforcement=block, WEIGHT_GATE,
UNIT_MISMATCH) but whose matched rule has ``rule_validated=False``
(``DoseVerdict.rule_validated``, set by the engine) is demoted here to the
SAME advisory shape as DATA_MISSING (severity=caution, status=flagged,
outside the gate), with the deterministic reason amended to say the rule is
not yet pharmacist-validated. See ``_demote_for_unvalidated_rule``.

Ordem 028 — the LLM only explains, after the fact: every genuine engine
write (create OR update, i.e. whenever ``_audit`` actually fires) for a
verdict that is neither SAFE nor NOT_APPLICABLE schedules — via
``transaction.on_commit`` — the Celery task
``apps.emr.tasks.explain_dose_verdict``, which asks the LLM to explain (never
decide) this exact verdict and writes it on its OWN row
(``source="llm"``, ``alert_type="dose_explicacao"``, FK ``explica`` to this
alert). It goes through the same consent/DPA/scrub/ceiling gate as ordem 025
and never touches this alert.

Idempotency / clobber-safety (plan §4 gap #1): every alert write is an
update_or_create keyed on (prescription_item, alert_type="dose", source="engine").
It NEVER touches the source="llm" row — the LLM explainer and the engine verdict
are independent.

Feature flag: per-tenant FeatureFlag module_key="dose_safety", default OFF. When
off, evaluate_prescription is a no-op (gates behave exactly as today).

NO clinical numbers live here. The formulary is pharmacist-supplied (D-T1) and
production tables stay empty until then.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import uuid4

from django.db import connection, transaction
from django.utils import timezone

from apps.core.models import AuditLog
from apps.core.utils import tenant_has_feature
from apps.pharmacy.services.dose_checker import DoseChecker, DoseVerdict, Verdict

if TYPE_CHECKING:
    from apps.emr.models import Prescription, PrescriptionItem

logger = logging.getLogger(__name__)

DOSE_SAFETY_FEATURE_KEY = "dose_safety"

# Per-verdict recommendation strings. These are the SINGLE SOURCE OF TRUTH for
# both the clinician-facing copy (_recommendation) and the machine-readable
# blocking-kind classification (classify_blocking_kind) — keep them in sync by
# referencing the constant, never the literal.
REC_WEIGHT_GATE = "Registre/atualize o peso do paciente e reavalie."
REC_OUT_OF_RANGE = "Reveja a dose; confirme peso/idade ou ajuste para o intervalo esperado."
REC_UNIT_MISMATCH = "Confirme a unidade prescrita; ela difere da unidade da regra de dose."

# Verdicts that BLOCK the gate (soft-stop). Everything else is advisory or silent.
_BLOCKING_VERDICTS = frozenset({Verdict.OUT_OF_RANGE, Verdict.WEIGHT_GATE, Verdict.UNIT_MISMATCH})
# Verdicts that produce a non-blocking advisory alert.
_ADVISORY_VERDICTS = frozenset({Verdict.DATA_MISSING, Verdict.ENGINE_ERROR, Verdict.NO_RULE_MATCH})


class DoseCheckService:
    """Service-layer orchestrator for the deterministic dose engine."""

    def __init__(self, *, requesting_user) -> None:
        self.requesting_user = requesting_user
        self.correlation_id = str(uuid4())

    # ── public API ────────────────────────────────────────────────────────────

    @classmethod
    def is_enabled(cls) -> bool:
        """True if the current tenant has the dose_safety feature flag enabled."""
        try:
            tenant = connection.tenant  # type: ignore[attr-defined]
            return tenant_has_feature(tenant, DOSE_SAFETY_FEATURE_KEY)
        except Exception:
            logger.warning(
                "Could not resolve dose_safety feature flag; defaulting to disabled.",
                exc_info=True,
            )
            return False

    def evaluate_prescription(self, prescription: Prescription, *, gate: str) -> None:
        """Evaluate every dose-checkable item on the prescription.

        No-op when the feature flag is off. Each item is evaluated independently
        and fails open EXCEPT a positive OUT_OF_RANGE/WEIGHT_GATE verdict, which
        writes a blocking alert. All writes for the run share one correlation_id.

        ``gate`` is "sign" or "dispense" — recorded in the flywheel so we know
        which gate raised the verdict.
        """
        if not self.is_enabled():
            return

        items = list(prescription.items.select_related("drug").all())
        if not items:
            return

        # Resolve patient context once (age in days, latest weight + when).
        patient = prescription.patient
        now = timezone.now()
        age_days = self._patient_age_days(patient, now)
        weight_kg, weight_recorded_at = self._latest_weight(patient)

        from django.conf import settings

        staleness_days = int(getattr(settings, "DOSE_SAFETY_WEIGHT_STALENESS_DAYS", 90))

        for item in items:
            self._evaluate_item(
                item=item,
                age_days=age_days,
                weight_kg=weight_kg,
                weight_recorded_at=weight_recorded_at,
                now=now,
                staleness_days=staleness_days,
                gate=gate,
            )

    @staticmethod
    def has_blocking_dose_alert(prescription: Prescription) -> bool:
        """True if any item has an outstanding BLOCKING engine dose alert.

        Blocking = alert_type="dose", source="engine", severity="contraindication",
        status="flagged" (i.e. NOT yet acknowledged). Acknowledging flips status to
        "acknowledged", so the predicate stops matching and the re-submit succeeds.

        When the dose_safety feature flag is OFF this ALWAYS returns False, so the
        gate is fully released — a stale flagged row from a previously-ON period
        can never permanently lock the gate after the flag is turned off.
        """
        if not DoseCheckService.is_enabled():
            return False

        from apps.emr.models import AISafetyAlert

        return AISafetyAlert.objects.filter(
            prescription_item__prescription=prescription,
            alert_type="dose",
            source=AISafetyAlert.Source.ENGINE,
            severity="contraindication",
            status="flagged",
        ).exists()

    @staticmethod
    def blocking_dose_alerts(prescription: Prescription):
        """Queryset of the outstanding blocking engine dose alerts (for the 409 body)."""
        from apps.emr.models import AISafetyAlert

        return AISafetyAlert.objects.filter(
            prescription_item__prescription=prescription,
            alert_type="dose",
            source=AISafetyAlert.Source.ENGINE,
            severity="contraindication",
            status="flagged",
        ).select_related("prescription_item")

    # ── per-item evaluation ─────────────────────────────────────────────────────

    def _evaluate_item(
        self,
        *,
        item: PrescriptionItem,
        age_days: int,
        weight_kg: Decimal | None,
        weight_recorded_at,
        now,
        staleness_days: int,
        gate: str,
    ) -> None:
        verdict = DoseChecker.check(
            drug=item.drug,
            dose_amount=item.dose_amount,
            dose_unit=item.dose_unit or None,
            route=item.route or None,
            frequency_per_day=item.frequency_per_day,
            patient_age_days=age_days,
            weight_kg=weight_kg,
            weight_recorded_at=weight_recorded_at,
            now=now,
            weight_staleness_days=staleness_days,
            dose_role=item.dose_role or None,
        )

        # Routing (dose-engine v2, AXIS 3; ordem 028 AXIS "validated"):
        #   WEIGHT_GATE / UNIT_MISMATCH → blocking (you cannot dose per-kg
        #     without a weight, and a unit mismatch is always dangerous —
        #     enforcement mode is irrelevant for these) — UNLESS the matched
        #     rule is not yet pharmacist-validated, in which case it demotes to
        #     the same advisory shape as DATA_MISSING (ordem 028).
        #   OUT_OF_RANGE → blocking IFF the matched rule's enforcement == "block"
        #     AND the rule is validated; an "advise" rule (opioids/sedatives with
        #     no hard pharmacological ceiling) OR a nao_validado rule is a
        #     NON-blocking caution either way.
        #   DATA_MISSING / ENGINE_ERROR / NO_RULE_MATCH → advisory (unchanged).
        #   SAFE → resolve. NOT_APPLICABLE → nothing.
        is_advise_out_of_range = (
            verdict.verdict == Verdict.OUT_OF_RANGE and verdict.enforcement == "advise"
        )
        would_block = verdict.verdict in _BLOCKING_VERDICTS and not is_advise_out_of_range

        if would_block and not verdict.rule_validated:
            self._raise_advisory_alert(
                item,
                self._demote_for_unvalidated_rule(verdict),
                gate,
                action=self._unvalidated_action(verdict),
            )
        elif would_block:
            self._raise_blocking_alert(item, verdict, gate)
        elif is_advise_out_of_range or verdict.verdict in _ADVISORY_VERDICTS:
            self._raise_advisory_alert(item, verdict, gate)
        elif verdict.verdict == Verdict.SAFE:
            self._resolve_to_safe(item, verdict, gate)
        # NOT_APPLICABLE → nothing (no alert, no badge, no false green).

    @staticmethod
    def _demote_for_unvalidated_rule(verdict: DoseVerdict) -> DoseVerdict:
        """A would-be-blocking verdict whose matched rule is nao_validado is
        never suppressed — it still signals — but it is not entitled to block
        on its own say-so (INTENT v6 §Limites: unreviewed data never enforces).
        The deterministic reason is amended (never replaced) so the audit trail
        and the alert message both keep saying WHY it stopped blocking."""
        from dataclasses import replace

        return replace(
            verdict,
            reason=(
                f"{verdict.reason} Esta regra ainda não foi validada por "
                "farmacêutico — o alerta é informativo e não bloqueia."
            ),
        )

    @staticmethod
    def _unvalidated_action(verdict: DoseVerdict) -> str:
        """AuditLog action name for a verdict demoted for lack of validation —
        distinct from the normal advisory actions so the flywheel can tell a
        genuine advisory apart from a would-have-blocked-but-unvalidated one."""
        if verdict.verdict == Verdict.WEIGHT_GATE:
            return "dose_weight_gate_nao_validada"
        if verdict.verdict == Verdict.UNIT_MISMATCH:
            return "dose_unit_mismatch_nao_validada"
        return "dose_out_of_range_nao_validada"

    def _raise_blocking_alert(
        self, item: PrescriptionItem, verdict: DoseVerdict, gate: str
    ) -> None:
        from apps.emr.models import AISafetyAlert

        with transaction.atomic():
            existing = (
                AISafetyAlert.objects.select_for_update()
                .filter(
                    prescription_item=item,
                    alert_type="dose",
                    source=AISafetyAlert.Source.ENGINE,
                )
                .first()
            )

            # Override-preservation: if the prescriber/pharmacist has ALREADY
            # acknowledged THIS exact blocking verdict (same message = same
            # clinical situation), re-evaluation at a later gate must NOT reset
            # the acknowledgement and re-block — that override stands. Only a
            # genuinely changed verdict (different reason, e.g. the dose was
            # edited) resets the ack and re-blocks. We never touch the llm row.
            if (
                existing is not None
                and existing.status == "acknowledged"
                and existing.severity == "contraindication"
                and existing.message == verdict.reason
            ):
                self._audit(
                    "dose_alert_override_preserved", item, verdict, gate, alert_id=existing.id
                )
                return

            # Idempotency (revisão P1 — mirrors the advisory path below): an
            # UNCHANGED blocking verdict (same message, still flagged,
            # still contraindication) is the SAME clinical situation on
            # re-evaluation — the dispense gate re-evaluates on every
            # attempt while the alert sits unacknowledged. Without this,
            # every retry wrote a fresh AuditLog and re-scheduled a real LLM
            # call via _schedule_explanation. Return without touching the
            # row, without auditing, without scheduling.
            if (
                existing is not None
                and existing.status == "flagged"
                and existing.severity == "contraindication"
                and existing.message == verdict.reason
            ):
                return

            alert, _created = AISafetyAlert.objects.update_or_create(
                prescription_item=item,
                alert_type="dose",
                source=AISafetyAlert.Source.ENGINE,
                defaults={
                    "severity": "contraindication",
                    "status": "flagged",
                    "message": verdict.reason,
                    # A NEW/changed blocking verdict must re-block, so we reset the
                    # ack fields. This is the engine row only, never the llm row.
                    "acknowledged_by": None,
                    "override_reason": "",
                    "acknowledged_at": None,
                    "recommendation": self._recommendation(verdict),
                },
            )
            self._audit("dose_alert_raised", item, verdict, gate, alert_id=alert.id)
            self._schedule_explanation(alert.id, verdict)

    def _raise_advisory_alert(
        self, item: PrescriptionItem, verdict: DoseVerdict, gate: str, *, action: str | None = None
    ) -> None:
        from apps.emr.models import AISafetyAlert

        if action is None:
            if verdict.verdict == Verdict.NO_RULE_MATCH:
                action = "dose_no_rule_match"
            elif verdict.verdict == Verdict.DATA_MISSING:
                action = "dose_data_missing"
            elif verdict.verdict == Verdict.OUT_OF_RANGE:
                # AXIS 3: an OUT_OF_RANGE on an enforcement="advise" rule routed here.
                # It is a visible caution, not a block — the reason already states the
                # dose exceeded the expected range.
                action = "dose_out_of_range_advisory"
            else:
                action = "dose_check_unavailable"
        with transaction.atomic():
            existing = (
                AISafetyAlert.objects.select_for_update()
                .filter(
                    prescription_item=item,
                    alert_type="dose",
                    source=AISafetyAlert.Source.ENGINE,
                )
                .first()
            )

            # Idempotency: an unchanged advisory (same message, still a caution)
            # is the SAME clinical situation on re-evaluation. Re-writing it would
            # wipe any acknowledgement and spam the audit log on every dispense
            # re-eval. Return without touching the row or auditing. A genuinely
            # changed advisory message, or a transition FROM a prior blocking
            # (contraindication) row, falls through and re-flags + audits.
            if (
                existing is not None
                and existing.message == verdict.reason
                and existing.severity == "caution"
            ):
                return

            alert, _created = AISafetyAlert.objects.update_or_create(
                prescription_item=item,
                alert_type="dose",
                source=AISafetyAlert.Source.ENGINE,
                defaults={
                    "severity": "caution",  # NON-blocking
                    "status": "flagged",
                    "message": verdict.reason,
                    "acknowledged_by": None,
                    "override_reason": "",
                    "acknowledged_at": None,
                    "recommendation": self._recommendation(verdict),
                },
            )
            self._audit(action, item, verdict, gate, alert_id=alert.id)
            self._schedule_explanation(alert.id, verdict)

    @staticmethod
    def _schedule_explanation(alert_id, verdict: DoseVerdict) -> None:
        """Ordem 028: after a genuine engine write (never SAFE/NOT_APPLICABLE —
        those never reach here), schedule the LLM explanation task post-commit.

        The task re-runs the SAME consent/DPA/ceiling gate as ordem 025 and can
        end up doing nothing (flag off, no DPA, circuit open, ceiling hit); this
        call site never blocks and never raises — it only enqueues.
        """
        context = {
            "verdict": verdict.verdict.value,
            "reason": verdict.reason,
            "expected_low": str(verdict.expected_low) if verdict.expected_low is not None else None,
            "expected_high": (
                str(verdict.expected_high) if verdict.expected_high is not None else None
            ),
            "max_per_dose": str(verdict.max_per_dose) if verdict.max_per_dose is not None else None,
            "rule_id": str(verdict.rule_id) if verdict.rule_id is not None else None,
            "status_validacao": "validado" if verdict.rule_validated else "nao_validado",
        }

        def _enqueue() -> None:
            from apps.emr.tasks import explain_dose_verdict

            explain_dose_verdict.delay(str(alert_id), context)

        transaction.on_commit(_enqueue)

    def _resolve_to_safe(self, item: PrescriptionItem, verdict: DoseVerdict, gate: str) -> None:
        """SAFE: clear any stale engine 'dose' alert (resolve to status='safe')."""
        from apps.emr.models import AISafetyAlert

        with transaction.atomic():
            existing = AISafetyAlert.objects.filter(
                prescription_item=item,
                alert_type="dose",
                source=AISafetyAlert.Source.ENGINE,
            ).first()
            if existing is not None and existing.status != "safe":
                existing.severity = "caution"
                existing.status = "safe"
                existing.message = verdict.reason
                existing.acknowledged_by = None
                existing.override_reason = ""
                existing.acknowledged_at = None
                existing.save(
                    update_fields=[
                        "severity",
                        "status",
                        "message",
                        "acknowledged_by",
                        "override_reason",
                        "acknowledged_at",
                    ]
                )
                self._audit("dose_alert_resolved", item, verdict, gate, alert_id=existing.id)

    # ── patient context ──────────────────────────────────────────────────────

    @staticmethod
    def _patient_age_days(patient, now) -> int:
        """Age in DAYS from birth_date (matches DoseRule age_min_days/age_max_days)."""
        birth = patient.birth_date
        return (now.date() - birth).days

    @staticmethod
    def _latest_weight(patient):
        """Resolve the patient's latest recorded weight via VitalSigns.

        Returns (weight_kg|None, recorded_at|None). VitalSigns is per-encounter;
        we take the most recent recording that carries a non-null weight.
        """
        from apps.emr.models import VitalSigns

        vs = (
            VitalSigns.objects.filter(
                encounter__patient=patient,
                weight_kg__isnull=False,
            )
            .order_by("-recorded_at")
            .first()
        )
        if vs is None:
            return None, None
        return vs.weight_kg, vs.recorded_at

    # ── audit (flywheel) ────────────────────────────────────────────────────────

    @staticmethod
    def _recommendation(verdict: DoseVerdict) -> str:
        if verdict.verdict == Verdict.WEIGHT_GATE:
            return REC_WEIGHT_GATE
        if verdict.verdict == Verdict.OUT_OF_RANGE:
            return REC_OUT_OF_RANGE
        if verdict.verdict == Verdict.UNIT_MISMATCH:
            return REC_UNIT_MISMATCH
        return ""

    @staticmethod
    def classify_blocking_kind(alert) -> str:
        """Map an AISafetyAlert to a machine-readable blocking kind.

        Uses the per-verdict recommendation constants as the single source of
        truth so the frontend can distinguish a non-overridable weight-gate from
        an overridable contraindication WITHOUT brittle copy-prefix matching.
        """
        recommendation = alert.recommendation
        if recommendation == REC_WEIGHT_GATE:
            return "weight_gate"
        if recommendation == REC_UNIT_MISMATCH:
            return "unit_mismatch"
        if recommendation == REC_OUT_OF_RANGE:
            return "out_of_range"
        return "dose"

    def _audit(
        self,
        action: str,
        item: PrescriptionItem,
        verdict: DoseVerdict,
        gate: str,
        *,
        alert_id,
    ) -> None:
        """One AuditLog per side-effect, carrying the labeled-example flywheel fields."""
        drug = item.drug
        new_data = {
            "correlation_id": self.correlation_id,
            "gate": gate,
            "alert_id": str(alert_id),
            "prescription_item_id": str(item.id),
            # Labeled example for the flywheel / accuracy review:
            "drug": drug.name,
            "drug_id": str(drug.id),
            "dose_amount": str(item.dose_amount) if item.dose_amount is not None else None,
            "dose_unit": item.dose_unit or None,
            "route": item.route or None,
            "frequency_per_day": item.frequency_per_day,
            "verdict": verdict.verdict.value,
            "expected_low": str(verdict.expected_low) if verdict.expected_low is not None else None,
            "expected_high": str(verdict.expected_high)
            if verdict.expected_high is not None
            else None,
            "max_per_dose": str(verdict.max_per_dose) if verdict.max_per_dose is not None else None,
            "rule_id": str(verdict.rule_id) if verdict.rule_id is not None else None,
            "reason": verdict.reason,
        }
        AuditLog.objects.create(
            user=self.requesting_user,
            action=action,
            resource_type="prescription_item",
            resource_id=str(item.id),
            new_data=new_data,
        )
