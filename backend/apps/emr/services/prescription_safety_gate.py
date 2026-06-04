"""Generalized prescription-safety gate — allergy/interaction wedge PR A1.

The sign/dispense soft-stop originally blocked only on engine DOSE
contraindications. This module generalizes it so the SAME gate blocks on ANY
engine-sourced contraindication across the safety wedges (dose, allergy, …),
while preserving each wedge's "flag OFF → gate released" property.

A blocking alert is: ``source="engine"`` AND ``severity="contraindication"`` AND
``status="flagged"`` AND ``alert_type`` in the set of CURRENTLY-ENABLED wedges.
Gating on the enabled set (not just any flagged row) means a stale flagged row
left over from a wedge whose flag was later turned OFF can never permanently lock
the gate. LLM rows (``source="llm"``) are never blocking.
"""

from __future__ import annotations


def _enabled_blocking_alert_types() -> list[str]:
    """alert_types whose engine contraindications currently block (per live flags)."""
    from apps.emr.services.allergy_safety import AllergySafetyService
    from apps.emr.services.dose_safety import DoseCheckService

    types: list[str] = []
    if DoseCheckService.is_enabled():
        types.append("dose")
    if AllergySafetyService.is_enabled():
        # The allergy wedge owns both direct-allergy and drug-interaction blocks.
        types.append("allergy")
        types.append("drug_interaction")
    return types


def blocking_safety_alerts(prescription):
    """Queryset of the outstanding blocking engine alerts (empty if no wedge on)."""
    from apps.emr.models import AISafetyAlert

    types = _enabled_blocking_alert_types()
    if not types:
        return AISafetyAlert.objects.none()
    return AISafetyAlert.objects.filter(
        prescription_item__prescription=prescription,
        alert_type__in=types,
        source=AISafetyAlert.Source.ENGINE,
        severity="contraindication",
        status="flagged",
    ).select_related("prescription_item")


def has_blocking_safety_alert(prescription) -> bool:
    """True if any enabled-wedge engine contraindication is outstanding."""
    return blocking_safety_alerts(prescription).exists()


def _blocking_kind(alert) -> str:
    """Structural reason a client can branch on, per alert_type."""
    if alert.alert_type == "dose":
        from apps.emr.services.dose_safety import DoseCheckService

        return DoseCheckService.classify_blocking_kind(alert)
    if alert.alert_type == "allergy":
        return "allergy_conflict"
    return alert.alert_type


def build_block_payload(prescription) -> dict:
    """409 body listing every outstanding blocking alert (dose + allergy + …).

    Keeps ``code="dose_safety_block"`` so the existing frontend modal (which keys
    on that code) fires for allergy blocks too; the per-alert ``blocking_kind``
    distinguishes them (``allergy_conflict`` falls through to normal
    override-with-reason, which is correct — an allergy block IS overridable).
    """
    alerts = [
        {
            "id": str(a.id),
            "prescription_item": str(a.prescription_item_id),
            "alert_type": a.alert_type,
            "severity": a.severity,
            "status": a.status,
            "message": a.message,
            "recommendation": a.recommendation,
            "blocking_kind": _blocking_kind(a),
        }
        for a in blocking_safety_alerts(prescription)
    ]
    return {
        "detail": (
            "Há alertas de segurança bloqueantes nesta prescrição. Reconheça-os "
            "com justificativa antes de prosseguir."
        ),
        "code": "dose_safety_block",
        "alerts": alerts,
    }
