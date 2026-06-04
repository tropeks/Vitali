"""Allergy-safety orchestrator — allergy/interaction wedge PR A1.

Bridges the PURE allergy engine (``apps.pharmacy.services.allergy_checker``) to
the prescription side-effects: resolving the patient's ACTIVE allergies, running
the checker per prescription item, writing an engine-sourced ``AISafetyAlert``
(``alert_type="allergy"``) when a drug conflicts with a recorded allergy, and the
flywheel ``AuditLog``. The engine DECIDES; this service persists.

Mirrors ``apps.emr.services.dose_safety.DoseCheckService``:
  * feature flag ``allergy_safety`` (default OFF) — when off, evaluate is a no-op;
  * the engine row is ``source="engine"`` so it never clobbers (nor is clobbered
    by) the LLM explainer's ``source="llm"`` row for the same item/alert_type;
  * override-preservation: an already-acknowledged identical block is not reset on
    re-evaluation; only a genuinely changed verdict re-blocks;
  * the shared sign/dispense gate (see ``prescription_safety_gate``) blocks on the
    engine contraindication this writes.

POSTURE — a confirmed ACTIVE allergy match BLOCKS (soft-stop 409, override with
reason), regardless of the recorded severity (recorded severity is unreliable).
Cross-reactivity / interactions (wedge A2/A3) are advise and curated, not here.
"""

from __future__ import annotations

import logging
from uuid import uuid4

from django.db import connection, transaction

from apps.core.models import AuditLog
from apps.core.utils import tenant_has_feature
from apps.pharmacy.services.allergy_checker import (
    ENGINE_VERSION,
    INTERACTION_CONTRAINDICATED,
    VERDICT_ALLERGY_CONFLICT,
    VERDICT_CROSS_REACTIVITY,
    VERDICT_SAFE,
    AllergyChecker,
    AllergyInput,
    CrossReactivityClass,
    DrugInPrescription,
    DrugInteractionRule,
    build_drug_tokens,
    find_interactions,
)

logger = logging.getLogger(__name__)

ALLERGY_SAFETY_FEATURE_KEY = "allergy_safety"

_RECOMMENDATION = (
    "Confirme a alergia do paciente. Se a prescrição for clinicamente necessária "
    "mesmo assim, reconheça o alerta com justificativa antes de prosseguir."
)
_CROSS_RECOMMENDATION = (
    "Possível reatividade cruzada. Avalie clinicamente; este é um aviso, não um bloqueio."
)


class AllergySafetyService:
    def __init__(self, *, requesting_user) -> None:
        self.requesting_user = requesting_user
        self.correlation_id = str(uuid4())

    @classmethod
    def is_enabled(cls) -> bool:
        """True if the current tenant has the allergy_safety feature flag enabled."""
        try:
            tenant = connection.tenant  # type: ignore[attr-defined]
            return tenant_has_feature(tenant, ALLERGY_SAFETY_FEATURE_KEY)
        except Exception:
            logger.warning(
                "Could not resolve allergy_safety feature flag; defaulting to disabled.",
                exc_info=True,
            )
            return False

    def evaluate_prescription(self, prescription, *, gate: str) -> None:
        """Evaluate every item on the prescription against the patient's allergies.

        No-op when the feature flag is off. ``gate`` is "sign" or "dispense",
        recorded in the flywheel. All writes for the run share one correlation_id.
        """
        if not self.is_enabled():
            return

        items = list(prescription.items.select_related("drug").all())
        if not items:
            return

        # Resolve the patient's ACTIVE allergies once (not per item).
        allergies = [
            AllergyInput(substance=a.substance, severity=a.severity)
            for a in prescription.patient.allergies.filter(status="active")
        ]
        if allergies:
            # Resolve the curated cross-reactivity classes once (wedge A2). Empty
            # when the establishment has not curated any → no cross-reactivity.
            classes = self._cross_reactivity_classes()
            for item in items:
                self._evaluate_item(item, allergies, classes, gate)
        else:
            # No active allergies — still resolve any stale engine allergy alerts
            # (e.g. an allergy was deactivated) so the gate releases.
            for item in items:
                self._resolve_to_safe(item, gate)

        # Drug-drug interactions (wedge A3) — independent of allergies; runs over
        # every prescription so a pair of interacting drugs is caught even with no
        # recorded allergy.
        self._evaluate_interactions(items, gate)

    @staticmethod
    def _cross_reactivity_classes() -> list[CrossReactivityClass]:
        from apps.pharmacy.models import AllergenClass

        return [
            CrossReactivityClass(name=c.name, members=list(c.members or []))
            for c in AllergenClass.objects.filter(active=True)
        ]

    def _evaluate_item(self, item, allergies, classes, gate: str) -> None:
        drug = item.drug
        if drug is None:
            return
        verdict = AllergyChecker.check(
            drug_name=drug.name,
            drug_generic_name=drug.generic_name or None,
            drug_active_ingredients=drug.active_ingredients or [],
            allergies=allergies,
            cross_reactivity_classes=classes,
        )
        if verdict.verdict == VERDICT_ALLERGY_CONFLICT:
            self._raise_blocking_alert(item, verdict, gate)
        elif verdict.verdict == VERDICT_CROSS_REACTIVITY:
            self._raise_advisory_alert(item, verdict, gate)
        elif verdict.verdict == VERDICT_SAFE:
            self._resolve_to_safe(item, gate)
        # NOT_APPLICABLE (unidentifiable drug) → no alert, no false green.

    def _raise_blocking_alert(self, item, verdict, gate: str) -> None:
        from apps.emr.models import AISafetyAlert

        with transaction.atomic():
            existing = (
                AISafetyAlert.objects.select_for_update()
                .filter(
                    prescription_item=item,
                    alert_type="allergy",
                    source=AISafetyAlert.Source.ENGINE,
                )
                .first()
            )
            # Override-preservation: an already-acknowledged identical block stands
            # on re-evaluation at a later gate. Only a changed verdict re-blocks.
            if (
                existing is not None
                and existing.status == "acknowledged"
                and existing.severity == "contraindication"
                and existing.message == verdict.reason
            ):
                self._audit("allergy_alert_override_preserved", item, verdict, gate, existing.id)
                return

            alert, _created = AISafetyAlert.objects.update_or_create(
                prescription_item=item,
                alert_type="allergy",
                source=AISafetyAlert.Source.ENGINE,
                defaults={
                    "severity": "contraindication",
                    "status": "flagged",
                    "message": verdict.reason,
                    "acknowledged_by": None,
                    "override_reason": "",
                    "acknowledged_at": None,
                    "recommendation": _RECOMMENDATION,
                },
            )
            self._audit("allergy_alert_raised", item, verdict, gate, alert.id)

    def _raise_advisory_alert(self, item, verdict, gate: str) -> None:
        """Cross-reactivity (wedge A2): a CAUTION alert — advise, never blocks."""
        from apps.emr.models import AISafetyAlert

        with transaction.atomic():
            existing = (
                AISafetyAlert.objects.select_for_update()
                .filter(
                    prescription_item=item,
                    alert_type="allergy",
                    source=AISafetyAlert.Source.ENGINE,
                )
                .first()
            )
            # Idempotency: an unchanged caution is the same clinical situation on
            # re-evaluation — don't reset an acknowledgement or spam the audit log.
            # A changed message, or a transition FROM a prior contraindication
            # (direct match cleared, now only cross-reactivity), falls through.
            if (
                existing is not None
                and existing.severity == "caution"
                and existing.message == verdict.reason
            ):
                return

            alert, _created = AISafetyAlert.objects.update_or_create(
                prescription_item=item,
                alert_type="allergy",
                source=AISafetyAlert.Source.ENGINE,
                defaults={
                    "severity": "caution",  # NON-blocking (advise)
                    "status": "flagged",
                    "message": verdict.reason,
                    "acknowledged_by": None,
                    "override_reason": "",
                    "acknowledged_at": None,
                    "recommendation": _CROSS_RECOMMENDATION,
                },
            )
            self._audit("allergy_cross_reactivity_advised", item, verdict, gate, alert.id)

    def _resolve_to_safe(self, item, gate: str) -> None:
        """No conflict: clear any stale engine 'allergy' alert (resolve to safe)."""
        from apps.emr.models import AISafetyAlert

        with transaction.atomic():
            existing = AISafetyAlert.objects.filter(
                prescription_item=item,
                alert_type="allergy",
                source=AISafetyAlert.Source.ENGINE,
            ).first()
            if existing is not None and existing.status != "safe":
                existing.severity = "caution"
                existing.status = "safe"
                existing.message = "Sem conflito de alergia registrado."
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
                self._audit("allergy_alert_resolved", item, None, gate, existing.id)

    # ── drug-drug interactions (wedge A3) ─────────────────────────────────────

    def _evaluate_interactions(self, items, gate: str) -> None:
        """Pairwise interaction scan across the prescription (single query)."""
        from apps.pharmacy.models import DrugInteraction

        drugs = [
            DrugInPrescription(
                key=str(item.id),
                label=item.drug.name,
                tokens=build_drug_tokens(
                    item.drug.name,
                    item.drug.generic_name or None,
                    item.drug.active_ingredients or [],
                ),
            )
            for item in items
            if item.drug is not None
        ]
        items_by_key = {str(item.id): item for item in items if item.drug is not None}

        # Single query: the curated interaction table is small; load active rows once.
        rules = [
            DrugInteractionRule(
                ingredient_a=r.ingredient_a,
                ingredient_b=r.ingredient_b,
                severity=r.severity,
                description=r.description,
            )
            for r in DrugInteraction.objects.filter(active=True)
        ]
        findings = find_interactions(drugs, rules) if rules else {}

        for key, item in items_by_key.items():
            item_findings = findings.get(key)
            if item_findings:
                self._raise_interaction_alert(item, item_findings, gate)
            else:
                self._resolve_interaction(item, gate)

    def _raise_interaction_alert(self, item, item_findings, gate: str) -> None:
        from apps.emr.models import AISafetyAlert

        # Any contraindicated interaction on this item → block; else advise.
        blocking = any(f.severity == INTERACTION_CONTRAINDICATED for f in item_findings)
        partners = ", ".join(sorted({f.partner_label for f in item_findings}))
        verb = "contraindicada com" if blocking else "interage com"
        message = f"Interação medicamentosa: {item.drug.name} {verb} {partners}."
        severity = "contraindication" if blocking else "caution"

        with transaction.atomic():
            existing = (
                AISafetyAlert.objects.select_for_update()
                .filter(
                    prescription_item=item,
                    alert_type="drug_interaction",
                    source=AISafetyAlert.Source.ENGINE,
                )
                .first()
            )
            # Override-preservation (blocking) / idempotency (advise): an unchanged
            # finding on re-evaluation must not reset an acknowledgement or spam.
            if (
                existing is not None
                and existing.message == message
                and existing.severity == severity
                and (existing.status == "acknowledged" or severity == "caution")
            ):
                if existing.status == "acknowledged":
                    self._audit_interaction(
                        "drug_interaction_override_preserved", item, message, gate, existing.id
                    )
                return

            alert, _created = AISafetyAlert.objects.update_or_create(
                prescription_item=item,
                alert_type="drug_interaction",
                source=AISafetyAlert.Source.ENGINE,
                defaults={
                    "severity": severity,
                    "status": "flagged",
                    "message": message,
                    "acknowledged_by": None,
                    "override_reason": "",
                    "acknowledged_at": None,
                    "recommendation": (
                        "Avalie a interação. Se a combinação for clinicamente necessária, "
                        "reconheça com justificativa."
                    ),
                },
            )
            action = "drug_interaction_blocked" if blocking else "drug_interaction_advised"
            self._audit_interaction(action, item, message, gate, alert.id)

    def _resolve_interaction(self, item, gate: str) -> None:
        """No interaction: clear any stale engine 'drug_interaction' alert."""
        from apps.emr.models import AISafetyAlert

        with transaction.atomic():
            existing = AISafetyAlert.objects.filter(
                prescription_item=item,
                alert_type="drug_interaction",
                source=AISafetyAlert.Source.ENGINE,
            ).first()
            if existing is not None and existing.status != "safe":
                existing.severity = "caution"
                existing.status = "safe"
                existing.message = "Sem interação medicamentosa registrada."
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
                self._audit_interaction("drug_interaction_resolved", item, "", gate, existing.id)

    def _audit_interaction(self, action: str, item, message: str, gate: str, alert_id) -> None:
        AuditLog.objects.create(
            user=self.requesting_user,
            action=action,
            resource_type="prescription_item",
            resource_id=str(item.id),
            new_data={
                "correlation_id": self.correlation_id,
                "gate": gate,
                "alert_id": str(alert_id),
                "prescription_item_id": str(item.id),
                "drug": getattr(item.drug, "name", None),
                "message": message,
                "engine_version": ENGINE_VERSION,
            },
        )

    def _audit(self, action: str, item, verdict, gate: str, alert_id) -> None:
        """One AuditLog per side-effect, carrying the labeled-example flywheel fields."""
        drug = item.drug
        new_data = {
            "correlation_id": self.correlation_id,
            "gate": gate,
            "alert_id": str(alert_id),
            "prescription_item_id": str(item.id),
            "drug": getattr(drug, "name", None),
            "drug_id": str(drug.id) if drug is not None else None,
            "matched_substances": list(verdict.matched_substances) if verdict else [],
            "verdict": verdict.verdict if verdict else VERDICT_SAFE,
            "engine_version": ENGINE_VERSION,
        }
        AuditLog.objects.create(
            user=self.requesting_user,
            action=action,
            resource_type="prescription_item",
            resource_id=str(item.id),
            new_data=new_data,
        )
