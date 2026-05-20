"""
FHIR R4 Encounter resource mapper.

Maps a Vitali `apps.emr.Encounter` to the FHIR R4 Encounter shape
(http://hl7.org/fhir/R4/encounter.html). Consumed by the FHIR REST views;
pure transform, no DB.

Scope:
- Core lifecycle: id, status (mapped to FHIR-valid codes), subject (Patient
  reference), participant (Professional reference), period (start at
  `encounter_date`, end at `signed_at` for signed encounters).
- Reason: free-text `chief_complaint` exposed as Encounter.reasonCode.text.
- Class: every encounter defaults to ambulatory (AMB) — Vitali is outpatient
  focused; inpatient/emergency classes are a follow-up once those statuses
  exist in the model.

Out of scope (follow-up resources / fields):
- Encounter.diagnosis (links to Condition — not yet a FHIR resource)
- Encounter.location (no Location resource yet)
- Encounter.serviceProvider (no Organization resource yet)
- Encounter.account / billing fields
"""

from __future__ import annotations

from typing import Any

# Vitali Encounter.status → FHIR R4 Encounter.status (constrained valueset).
# FHIR valid values: planned | arrived | triaged | in-progress | onleave |
# finished | cancelled | entered-in-error | unknown.
_STATUS_MAP = {
    "open": "in-progress",
    "signed": "finished",
    "cancelled": "cancelled",
}


def encounter_to_fhir(encounter: Any, *, base_url: str = "") -> dict[str, Any]:
    """
    Convert one Encounter model instance to a FHIR R4 Encounter resource dict.

    `base_url` (optional) is prepended to internal references when emitting
    absolute URLs (e.g. `Patient/<uuid>` → `<base_url>/Patient/<uuid>`). When
    empty, references are emitted in the relative form FHIR servers accept.
    """
    period = _build_period(encounter)
    resource: dict[str, Any] = {
        "resourceType": "Encounter",
        "id": str(encounter.id),
        "status": _STATUS_MAP.get(getattr(encounter, "status", "open"), "unknown"),
        "class": _ambulatory_class(),
        "subject": _patient_reference(encounter, base_url),
        "participant": _participants(encounter, base_url),
    }
    if period:
        resource["period"] = period
    chief = (getattr(encounter, "chief_complaint", "") or "").strip()
    if chief:
        resource["reasonCode"] = [{"text": chief}]
    return resource


def _patient_reference(encounter: Any, base_url: str) -> dict[str, Any]:
    patient = getattr(encounter, "patient", None)
    if patient is None:
        return {}
    ref = f"Patient/{patient.pk}"
    full = f"{base_url}/{ref}" if base_url else ref
    display = (getattr(patient, "full_name", "") or "").strip()
    out: dict[str, Any] = {"reference": full, "type": "Patient"}
    if display:
        out["display"] = display
    return out


def _participants(encounter: Any, base_url: str) -> list[dict[str, Any]]:
    professional = getattr(encounter, "professional", None)
    if professional is None:
        return []
    user = getattr(professional, "user", None)
    display = ""
    if user is not None:
        display = (getattr(user, "full_name", "") or getattr(user, "email", "") or "").strip()
    ref = f"Practitioner/{professional.pk}"
    full = f"{base_url}/{ref}" if base_url else ref
    individual: dict[str, Any] = {"reference": full, "type": "Practitioner"}
    if display:
        individual["display"] = display
    return [
        {
            "type": [
                {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/v3-ParticipationType",
                            "code": "PPRF",
                            "display": "primary performer",
                        }
                    ]
                }
            ],
            "individual": individual,
        }
    ]


def _build_period(encounter: Any) -> dict[str, Any]:
    period: dict[str, Any] = {}
    start = getattr(encounter, "encounter_date", None)
    end = getattr(encounter, "signed_at", None)
    if start is not None:
        period["start"] = start.isoformat()
    if end is not None:
        period["end"] = end.isoformat()
    return period


def _ambulatory_class() -> dict[str, Any]:
    return {
        "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
        "code": "AMB",
        "display": "ambulatory",
    }
