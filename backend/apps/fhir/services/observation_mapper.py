"""
FHIR R4 Observation mapper.

Maps `apps.emr.VitalSigns` to FHIR Observation resources
(http://hl7.org/fhir/R4/observation.html). A single VitalSigns row is split
into N Observation resources — FHIR models each vital as its own observation
with a stable LOINC code so downstream EHRs can index them individually:

| Vital                         | LOINC   | UCUM unit |
|-------------------------------|---------|-----------|
| Weight                        | 29463-7 | kg        |
| Height                        | 8302-2  | cm        |
| Systolic blood pressure       | 8480-6  | mmHg      |
| Diastolic blood pressure      | 8462-4  | mmHg      |
| Heart rate                    | 8867-4  | /min      |
| Body temperature              | 8310-5  | Cel       |
| Oxygen saturation             | 59408-5 | %         |
| Body mass index               | 39156-5 | kg/m2     |

Each Observation derives its id from the VitalSigns pk + the LOINC code
(`<vs-id>-<code>`) so it stays stable across reads.

Out of scope:
- Lab results (no Lab model in the EMR today).
- Component observations (e.g., grouping BP systolic/diastolic into a single
  Observation with two components — clinically equivalent but more verbose;
  we ship separate atomic observations for simplicity).
"""

from __future__ import annotations

from typing import Any

LOINC_SYSTEM = "http://loinc.org"
UCUM_SYSTEM = "http://unitsofmeasure.org"

VITAL_SIGNS_CATEGORY = {
    "coding": [
        {
            "system": "http://terminology.hl7.org/CodeSystem/observation-category",
            "code": "vital-signs",
            "display": "Vital Signs",
        }
    ],
    "text": "Vital Signs",
}

# Each entry maps the source field name to a tuple:
#   (loinc_code, human_display, ucum_unit, value_converter)
# `value_converter` is `float` for numeric values; some need post-processing
# (BMI is computed not stored), so we keep the column explicit.
_VITAL_SPECS: dict[str, tuple[str, str, str]] = {
    "weight_kg": ("29463-7", "Body weight", "kg"),
    "height_cm": ("8302-2", "Body height", "cm"),
    "blood_pressure_systolic": ("8480-6", "Systolic blood pressure", "mm[Hg]"),
    "blood_pressure_diastolic": ("8462-4", "Diastolic blood pressure", "mm[Hg]"),
    "heart_rate": ("8867-4", "Heart rate", "/min"),
    "temperature_celsius": ("8310-5", "Body temperature", "Cel"),
    "oxygen_saturation": ("59408-5", "Oxygen saturation in Arterial blood", "%"),
}

# BMI is computed from height + weight (VitalSigns.bmi is already a property).
_BMI_SPEC = ("39156-5", "Body mass index (BMI) [Ratio]", "kg/m2")


def vital_signs_to_fhir_bundle(vital_signs: Any, *, base_url: str = "") -> list[dict[str, Any]]:
    """Return the list of FHIR Observation resources for one VitalSigns row."""
    if vital_signs is None:
        return []
    out: list[dict[str, Any]] = []
    for field, (code, display, unit) in _VITAL_SPECS.items():
        raw = getattr(vital_signs, field, None)
        if raw is None:
            continue
        out.append(
            _build_observation(
                vital_signs,
                code=code,
                display=display,
                unit=unit,
                value=float(raw),
                base_url=base_url,
            )
        )
    bmi = getattr(vital_signs, "bmi", None)
    if bmi is not None:
        out.append(
            _build_observation(
                vital_signs,
                code=_BMI_SPEC[0],
                display=_BMI_SPEC[1],
                unit=_BMI_SPEC[2],
                value=float(bmi),
                base_url=base_url,
            )
        )
    return out


def vital_signs_observation(
    vital_signs: Any, *, code: str, base_url: str = ""
) -> dict[str, Any] | None:
    """Return one Observation by LOINC code (used by the read endpoint)."""
    if vital_signs is None:
        return None
    field_by_code = {spec[0]: field for field, spec in _VITAL_SPECS.items()}
    if code == _BMI_SPEC[0]:
        bmi = getattr(vital_signs, "bmi", None)
        if bmi is None:
            return None
        return _build_observation(
            vital_signs,
            code=_BMI_SPEC[0],
            display=_BMI_SPEC[1],
            unit=_BMI_SPEC[2],
            value=float(bmi),
            base_url=base_url,
        )
    field = field_by_code.get(code)
    if field is None:
        return None
    raw = getattr(vital_signs, field, None)
    if raw is None:
        return None
    loinc, display, unit = _VITAL_SPECS[field]
    return _build_observation(
        vital_signs,
        code=loinc,
        display=display,
        unit=unit,
        value=float(raw),
        base_url=base_url,
    )


def _build_observation(
    vital_signs: Any,
    *,
    code: str,
    display: str,
    unit: str,
    value: float,
    base_url: str,
) -> dict[str, Any]:
    encounter = getattr(vital_signs, "encounter", None)
    patient = getattr(encounter, "patient", None) if encounter else None
    resource: dict[str, Any] = {
        "resourceType": "Observation",
        # `_` separator: UUIDs contain `-`, LOINC codes contain `-`, but
        # neither contains `_`. Splitting the id on the first `_` is therefore
        # unambiguous in the view.
        "id": f"{vital_signs.encounter_id}_{code}",
        "status": "final",
        "category": [VITAL_SIGNS_CATEGORY],
        "code": {
            "coding": [{"system": LOINC_SYSTEM, "code": code, "display": display}],
            "text": display,
        },
        "valueQuantity": {
            "value": value,
            "unit": unit,
            "system": UCUM_SYSTEM,
            "code": unit,
        },
    }
    if patient is not None:
        resource["subject"] = _ref(patient, "Patient", base_url, getattr(patient, "full_name", ""))
    if encounter is not None:
        resource["encounter"] = _ref(encounter, "Encounter", base_url)
    recorded = getattr(vital_signs, "recorded_at", None)
    if recorded is not None:
        resource["effectiveDateTime"] = recorded.isoformat()
    return resource


def _ref(obj: Any, type_name: str, base_url: str, display: str = "") -> dict[str, Any]:
    ref = f"{type_name}/{obj.pk}"
    full = f"{base_url}/{ref}" if base_url else ref
    out: dict[str, Any] = {"reference": full, "type": type_name}
    if display:
        out["display"] = display
    return out
