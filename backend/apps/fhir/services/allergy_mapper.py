"""
FHIR R4 AllergyIntolerance mapper.

Maps `apps.emr.Allergy` → FHIR R4 AllergyIntolerance
(http://hl7.org/fhir/R4/allergyintolerance.html). Pure transform, no DB.

The mapping intentionally favours interop-clarity over fidelity to obscure
fields: criticality + clinicalStatus are the two signals every downstream
EHR cares about, plus the substance code (free-text for now — until we
plug RxNorm / SNOMED translation in a follow-up).
"""

from __future__ import annotations

from typing import Any

# Vitali severity → FHIR criticality (constrained valueset: low | high |
# unable-to-assess). "moderate" maps to "high" because FHIR offers no middle
# step and downstream consumers should treat moderate as actionable.
_CRITICALITY_MAP = {
    "mild": "low",
    "moderate": "high",
    "severe": "high",
    "life_threatening": "high",
}

# Vitali clinical status → FHIR clinicalStatus codes (active | inactive |
# resolved). The codes are identical so this is a passthrough; we still
# define the map explicitly so the source of truth is one place.
_CLINICAL_STATUS_MAP = {
    "active": "active",
    "inactive": "inactive",
    "resolved": "resolved",
}

# Reaction severity (one per AllergyIntolerance.reaction) — mild | moderate |
# severe (FHIR R4). Vitali "life_threatening" rolls up to severe in the
# reaction sub-element while still surfacing as `criticality=high` on the
# parent.
_REACTION_SEVERITY_MAP = {
    "mild": "mild",
    "moderate": "moderate",
    "severe": "severe",
    "life_threatening": "severe",
}

CLINICAL_STATUS_SYSTEM = "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical"


def allergy_to_fhir(allergy: Any, *, base_url: str = "") -> dict[str, Any]:
    """Convert one Allergy instance to a FHIR R4 AllergyIntolerance resource dict."""
    patient = getattr(allergy, "patient", None)
    severity = (getattr(allergy, "severity", "") or "").lower()
    clinical = (getattr(allergy, "status", "active") or "active").lower()

    resource: dict[str, Any] = {
        "resourceType": "AllergyIntolerance",
        "id": str(allergy.id),
        "clinicalStatus": _clinical_status(clinical),
        "verificationStatus": _verification_status(allergy),
        "code": {"text": getattr(allergy, "substance", "") or "Unspecified substance"},
        "criticality": _CRITICALITY_MAP.get(severity, "unable-to-assess"),
        "patient": _patient_reference(patient, base_url),
    }
    recorded = getattr(allergy, "created_at", None)
    if recorded is not None:
        resource["recordedDate"] = recorded.isoformat()
    reaction = (getattr(allergy, "reaction", "") or "").strip()
    if reaction:
        resource["reaction"] = [
            {
                "manifestation": [{"text": reaction}],
                "severity": _REACTION_SEVERITY_MAP.get(severity, "mild"),
            }
        ]
    return {k: v for k, v in resource.items() if v not in (None, [], {})}


def _clinical_status(value: str) -> dict[str, Any]:
    code = _CLINICAL_STATUS_MAP.get(value, "active")
    return {"coding": [{"system": CLINICAL_STATUS_SYSTEM, "code": code, "display": code.title()}]}


def _verification_status(allergy: Any) -> dict[str, Any]:
    confirmed = getattr(allergy, "confirmed_by_id", None) or getattr(allergy, "confirmed_by", None)
    code = "confirmed" if confirmed else "unconfirmed"
    return {
        "coding": [
            {
                "system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-verification",
                "code": code,
                "display": code.title(),
            }
        ]
    }


def _patient_reference(patient: Any, base_url: str) -> dict[str, Any]:
    if patient is None:
        return {}
    ref = f"Patient/{patient.pk}"
    full = f"{base_url}/{ref}" if base_url else ref
    out: dict[str, Any] = {"reference": full, "type": "Patient"}
    display = (getattr(patient, "full_name", "") or "").strip()
    if display:
        out["display"] = display
    return out
