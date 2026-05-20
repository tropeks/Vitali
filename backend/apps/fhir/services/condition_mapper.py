"""
FHIR R4 Condition mapper.

Maps `apps.emr.MedicalHistory` → FHIR Condition resources
(http://hl7.org/fhir/R4/condition.html). Each MedicalHistory row carries a
condition name, optional CID-10 code, type (chronic / acute / surgical /
family), and a clinical status (active / controlled / resolved).

Mapping decisions:
- `clinicalStatus`: `active` → active, `controlled` → active (FHIR has no
  "controlled" code; the clinically equivalent is `active` with a note),
  `resolved` → resolved.
- `category`: derived from the Vitali `type` — chronic/acute map to
  problem-list-item, surgical maps to encounter-diagnosis, family does not
  have a clean FHIR category (we surface it as encounter-diagnosis with a
  free-text discriminator so the data isn't silently dropped).
- `code`: emitted with the CID-10 (ICD-10-BR) coding when available, plus
  the free-text condition name in `code.text` as fallback.
"""

from __future__ import annotations

from typing import Any

CID10_SYSTEM = "http://hl7.org/fhir/sid/icd-10"
CLINICAL_STATUS_SYSTEM = "http://terminology.hl7.org/CodeSystem/condition-clinical"
CATEGORY_SYSTEM = "http://terminology.hl7.org/CodeSystem/condition-category"

_CLINICAL_STATUS_MAP = {
    "active": "active",
    "controlled": "active",
    "resolved": "resolved",
}

_CATEGORY_MAP = {
    "chronic": ("problem-list-item", "Problem List Item"),
    "acute": ("problem-list-item", "Problem List Item"),
    "surgical": ("encounter-diagnosis", "Encounter Diagnosis"),
    "family": ("encounter-diagnosis", "Encounter Diagnosis"),
}


def medical_history_to_fhir(history: Any, *, base_url: str = "") -> dict[str, Any]:
    """Convert one MedicalHistory instance to a FHIR Condition resource dict."""
    patient = getattr(history, "patient", None)
    status_value = (getattr(history, "status", "active") or "active").lower()
    type_value = (getattr(history, "type", "") or "").lower()

    resource: dict[str, Any] = {
        "resourceType": "Condition",
        "id": str(history.id),
        "clinicalStatus": _clinical_status(status_value),
        "verificationStatus": {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/condition-ver-status",
                    "code": "confirmed",
                }
            ]
        },
        "category": [_category(type_value)],
        "code": _code(history),
        "subject": _patient_reference(patient, base_url),
    }

    if status_value == "controlled":
        # FHIR has no "controlled" code; surface the original Vitali state
        # in a note so the information isn't silently lost.
        resource["note"] = [{"text": "Status: controlada"}]

    onset = getattr(history, "onset_date", None)
    if onset is not None:
        resource["onsetDateTime"] = onset.isoformat()

    recorded = getattr(history, "created_at", None)
    if recorded is not None:
        resource["recordedDate"] = recorded.isoformat()

    notes = (getattr(history, "notes", "") or "").strip()
    if notes:
        resource.setdefault("note", []).append({"text": notes})

    return {k: v for k, v in resource.items() if v not in (None, [], {})}


def _clinical_status(value: str) -> dict[str, Any]:
    code = _CLINICAL_STATUS_MAP.get(value, "active")
    return {"coding": [{"system": CLINICAL_STATUS_SYSTEM, "code": code, "display": code.title()}]}


def _category(type_value: str) -> dict[str, Any]:
    code, display = _CATEGORY_MAP.get(type_value, ("problem-list-item", "Problem List Item"))
    cat: dict[str, Any] = {
        "coding": [{"system": CATEGORY_SYSTEM, "code": code, "display": display}],
        "text": display,
    }
    if type_value == "family":
        cat["text"] = "Family history"
    return cat


def _code(history: Any) -> dict[str, Any]:
    name = (getattr(history, "condition", "") or "").strip()
    cid10 = (getattr(history, "cid10_code", "") or "").strip()
    code: dict[str, Any] = {"text": name or "Unspecified condition"}
    if cid10:
        code["coding"] = [{"system": CID10_SYSTEM, "code": cid10, "display": name or cid10}]
    return code


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
