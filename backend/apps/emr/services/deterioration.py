"""Deterioration-safety orchestrator — clinical-deterioration wedge (PR D2).

Bridges the PURE NEWS2 engine (``apps.emr.services.news2``) to the EMR
side-effects: reading a ``VitalSigns`` row + the patient's SpO2-scale flag,
computing the NEWS2 score, and — when it crosses the risk band — persisting a
``DeteriorationAlert(source="engine")`` and a flywheel ``AuditLog``. The engine
DECIDES; this service persists.

Mirrors ``apps.emr.services.dose_safety`` / ``pharmacy.services.stockout_safety``:
  * service-layer orchestrator; one AuditLog per side-effect with the
    labeled-example fields (score, band, breakdown) for the future flywheel (D4);
  * feature flag ``deterioration_safety`` (default OFF) — when off, ``evaluate``
    is a no-op and NO alert is ever written;
  * fail-safe: any error → logged and swallowed; **vitals recording is never
    blocked or rolled back** (this runs on_commit, after the save is durable).

POSTURE — ADVISE / ESCALATION, NEVER BLOCK. There is no gate on vitals recording.
The wedge raises an early-warning alert for the clinical dashboard (D3); the
deterministic NEWS2 score is authoritative, an LLM would only explain/prioritise.

Alerting threshold (LOCKED): an alert is raised when the band is **low_medium,
medium or high** — i.e. NOT plain ``low``. low_medium is the RCP "red score" (a
single parameter scoring 3), a recognised trigger for urgent ward review, so it
is included even though the plan shorthand said "≥ medium". Severity: ``high`` →
``escalation`` (emergency response), otherwise ``advise``.

De-dup (LOCKED): at most one OPEN alert per encounter (DB partial unique). A new
reading ESCALATES the open alert only if the score ROSE (no downgrade/spam); a
new alert is created only when there is no open one (i.e. the previous was
acknowledged/resolved). Concurrent evaluations for one encounter are serialised
by locking the parent Encounter row.
"""

from __future__ import annotations

import logging
from uuid import uuid4

from django.db import connection, transaction

from apps.core.models import AuditLog
from apps.core.utils import tenant_has_feature
from apps.emr.models import DeteriorationAlert, Encounter, VitalSigns
from apps.emr.services.news2 import (
    BAND_HIGH,
    BAND_LOW,
    NEWS2Result,
    compute_news2,
)

logger = logging.getLogger(__name__)

DETERIORATION_SAFETY_FEATURE_KEY = "deterioration_safety"

# Human-readable parameter labels for the alert message (pt-BR).
_PARAM_LABELS = {
    "respiratory_rate": "FR",
    "spo2": "SpO2",
    "supplemental_oxygen": "O2 suplementar",
    "systolic_bp": "PAS",
    "heart_rate": "FC",
    "temperature": "Temp",
    "consciousness": "Consciência",
}


class DeteriorationService:
    """Persist a NEWS2 verdict as a DeteriorationAlert (advise/escalation)."""

    def __init__(self, *, requesting_user=None) -> None:
        self.requesting_user = requesting_user
        self.correlation_id = str(uuid4())

    @classmethod
    def is_enabled(cls) -> bool:
        """True if the current tenant has the deterioration_safety flag enabled."""
        try:
            tenant = connection.tenant  # type: ignore[attr-defined]
            return tenant_has_feature(tenant, DETERIORATION_SAFETY_FEATURE_KEY)
        except Exception:
            logger.warning(
                "Could not resolve deterioration_safety feature flag; defaulting to disabled.",
                exc_info=True,
            )
            return False

    def evaluate(self, vital_signs: VitalSigns) -> DeteriorationAlert | None:
        """Score one VitalSigns reading and raise/escalate an alert if warranted.

        No-op when the flag is OFF or the reading is incomplete (engine inert).
        Fail-safe: any error is logged and swallowed so vitals recording — which
        already committed before this runs on_commit — is never disturbed.
        """
        if not self.is_enabled():
            return None
        try:
            return self._evaluate(vital_signs)
        except Exception:
            logger.exception(
                "DeteriorationService.evaluate failed for VitalSigns %s; failing safe.",
                getattr(vital_signs, "pk", None),
            )
            return None

    def _evaluate(self, vs: VitalSigns) -> DeteriorationAlert | None:
        patient = vs.encounter.patient
        result = compute_news2(
            respiratory_rate=vs.respiratory_rate,
            spo2=vs.oxygen_saturation,
            on_supplemental_oxygen=vs.on_supplemental_oxygen,
            systolic_bp=vs.blood_pressure_systolic,
            heart_rate=vs.heart_rate,
            temperature=vs.temperature_celsius,
            consciousness=vs.consciousness,
            use_spo2_scale_2=patient.use_spo2_scale_2,
        )
        # Incomplete vitals (any of the 7 NEWS2 params missing) → inert. We do NOT
        # impute "normal" and we do NOT touch existing alerts.
        if result is None:
            return None
        # Below the alerting threshold → no alert, no false-green badge.
        if result.band == BAND_LOW:
            return None

        severity = (
            DeteriorationAlert.Severity.ESCALATION
            if result.band == BAND_HIGH
            else DeteriorationAlert.Severity.ADVISE
        )
        return self._raise_or_escalate(vs, result, severity)

    def _raise_or_escalate(
        self, vs: VitalSigns, result: NEWS2Result, severity: str
    ) -> DeteriorationAlert:
        encounter = vs.encounter
        with transaction.atomic():
            # Serialise all deterioration evaluations for this encounter so two
            # concurrent readings can't both create an OPEN alert (the partial
            # unique index would otherwise reject the second with IntegrityError).
            Encounter.objects.select_for_update().get(pk=encounter.pk)

            open_alert = (
                DeteriorationAlert.objects.filter(
                    encounter=encounter,
                    status=DeteriorationAlert.Status.OPEN,
                )
                .order_by("-created_at")
                .first()
            )

            message = self._message(result)

            if open_alert is not None:
                # Only escalate if the score ROSE — never downgrade or re-notify
                # an already-open alert for an equal/lower score.
                if result.score <= open_alert.score:
                    return open_alert
                open_alert.score = result.score
                open_alert.band = result.band
                open_alert.breakdown = result.breakdown
                open_alert.any_param_three = result.any_param_three
                open_alert.spo2_scale = result.spo2_scale
                open_alert.severity = severity
                open_alert.engine_version = result.engine_version
                open_alert.vital_signs = vs
                open_alert.message = message
                open_alert.save(
                    update_fields=[
                        "score",
                        "band",
                        "breakdown",
                        "any_param_three",
                        "spo2_scale",
                        "severity",
                        "engine_version",
                        "vital_signs",
                        "message",
                        "updated_at",
                    ]
                )
                alert = open_alert
                action = "deterioration_alert_escalated"
            else:
                alert = DeteriorationAlert.objects.create(
                    encounter=encounter,
                    vital_signs=vs,
                    score=result.score,
                    band=result.band,
                    breakdown=result.breakdown,
                    any_param_three=result.any_param_three,
                    spo2_scale=result.spo2_scale,
                    severity=severity,
                    source=DeteriorationAlert.Source.ENGINE,
                    status=DeteriorationAlert.Status.OPEN,
                    engine_version=result.engine_version,
                    message=message,
                )
                action = "deterioration_alert_raised"

            self._audit(action, vs, result, severity, alert_id=alert.id)

        # Route escalation notifications AFTER the atomic block commits so that
        # any routing failure cannot roll back the alert or its audit row.
        if action in ("deterioration_alert_raised", "deterioration_alert_escalated"):
            from apps.emr.services.escalation import EscalationRouter

            EscalationRouter().route(alert, requesting_user=self.requesting_user)

        return alert

    @staticmethod
    def _message(result: NEWS2Result) -> str:
        """pt-BR summary naming the score, band and the contributing parameters."""
        contributors = [
            f"{_PARAM_LABELS.get(param, param)} +{pts}"
            for param, pts in result.breakdown.items()
            if pts > 0
        ]
        detail = "; ".join(contributors) if contributors else "sem parâmetro pontuado"
        return f"NEWS2 {result.score} ({result.clinical_response}) — {detail}."

    def _audit(
        self,
        action: str,
        vs: VitalSigns,
        result: NEWS2Result,
        severity: str,
        *,
        alert_id,
    ) -> None:
        """One AuditLog per side-effect, carrying the labeled-example flywheel fields."""
        new_data = {
            "correlation_id": self.correlation_id,
            "alert_id": str(alert_id),
            "encounter_id": str(vs.encounter_id),
            "vital_signs_id": str(vs.pk),
            # Labeled example for the future flywheel (D4: vs ICU-transfer / RRT).
            "score": result.score,
            "band": result.band,
            "any_param_three": result.any_param_three,
            "spo2_scale": result.spo2_scale,
            "severity": severity,
            "breakdown": result.breakdown,
            "engine_version": result.engine_version,
        }
        AuditLog.objects.create(
            user=self.requesting_user,
            action=action,
            resource_type="deterioration_alert",
            resource_id=str(alert_id),
            new_data=new_data,
        )
