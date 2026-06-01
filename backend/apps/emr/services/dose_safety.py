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

# Verdicts that BLOCK the gate (soft-stop). Everything else is advisory or silent.
_BLOCKING_VERDICTS = frozenset({Verdict.OUT_OF_RANGE, Verdict.WEIGHT_GATE})
# Verdicts that produce a non-blocking advisory alert.
_ADVISORY_VERDICTS = frozenset({Verdict.DATA_MISSING, Verdict.ENGINE_ERROR})


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
        """
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
        )

        if verdict.verdict in _BLOCKING_VERDICTS:
            self._raise_blocking_alert(item, verdict, gate)
        elif verdict.verdict in _ADVISORY_VERDICTS:
            self._raise_advisory_alert(item, verdict, gate)
        elif verdict.verdict == Verdict.SAFE:
            self._resolve_to_safe(item, verdict, gate)
        # NOT_APPLICABLE → nothing (no alert, no badge, no false green).

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

    def _raise_advisory_alert(
        self, item: PrescriptionItem, verdict: DoseVerdict, gate: str
    ) -> None:
        from apps.emr.models import AISafetyAlert

        action = (
            "dose_data_missing"
            if verdict.verdict == Verdict.DATA_MISSING
            else "dose_check_unavailable"
        )
        with transaction.atomic():
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
            return "Registre/atualize o peso do paciente e reavalie."
        if verdict.verdict == Verdict.OUT_OF_RANGE:
            return "Reveja a dose; confirme peso/idade ou ajuste para o intervalo esperado."
        return ""

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
