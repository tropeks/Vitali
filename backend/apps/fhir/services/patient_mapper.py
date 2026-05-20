"""
FHIR R4 Patient resource mapper.

Maps a Vitali `apps.emr.Patient` record to the FHIR R4 Patient resource
shape (http://hl7.org/fhir/R4/patient.html). This is the smallest useful
interoperability primitive — once the Patient resource is exposed, EHR/PEP
integrations can import patient demographics through a standard channel
without writing per-clinic custom adapters.

Scope of this mapper:
- Core demographics: id, MRN identifier, CPF identifier (when present),
  active flag, name (full + social), telecom (phone, mobile/whatsapp, email),
  gender, birthDate, address.
- LGPD: CPF is exposed as a FHIR identifier with a `system` URI that flags
  it as a national identifier. Callers must already be authenticated and
  authorized with `fhir.read` — the gating is enforced at the view layer.

Out of scope (later resource types or follow-up work):
- Patient.contact (emergency contact), Patient.communication, Patient.deceased
- Patient.managingOrganization
- Observation, Encounter, MedicationRequest, Practitioner resources
- Bundle responses (search returns a Bundle in FHIR but we use the simpler
  searchset shape here, layered into a proper Bundle in a follow-up).
"""

from __future__ import annotations

from typing import Any

# FHIR Patient gender values are constrained: male | female | other | unknown.
_GENDER_MAP = {
    "M": "male",
    "F": "female",
    "O": "other",
    "N": "unknown",
}

# System URIs identifying each identifier type. The MRN system is local
# (tenant-scoped); the CPF system is the Brazilian national identifier URN
# from the HL7 BR-Core IG.
SYSTEM_MRN = "urn:vitali:mrn"
SYSTEM_CPF = "urn:oid:2.16.840.1.113883.13.236"  # Brazilian CPF OID (HL7 BR-Core)


def patient_to_fhir(patient: Any) -> dict[str, Any]:
    """
    Convert one Patient model instance to a FHIR R4 Patient resource dict.

    The caller is responsible for permission/module gating; this function is
    a pure transform and does not enforce LGPD by itself.
    """
    resource: dict[str, Any] = {
        "resourceType": "Patient",
        "id": str(patient.id),
        "active": bool(getattr(patient, "is_active", True)),
        "identifier": _build_identifiers(patient),
        "name": _build_names(patient),
        "telecom": _build_telecom(patient),
        "gender": _GENDER_MAP.get(getattr(patient, "gender", "N"), "unknown"),
        "birthDate": patient.birth_date.isoformat() if patient.birth_date else None,
    }
    address = _build_address(patient)
    if address:
        resource["address"] = [address]
    # Strip keys that came back empty so the resource stays compact.
    return {k: v for k, v in resource.items() if v not in (None, [], {})}


def _build_identifiers(patient: Any) -> list[dict[str, Any]]:
    identifiers: list[dict[str, Any]] = []
    mrn = getattr(patient, "medical_record_number", "") or ""
    if mrn:
        identifiers.append(
            {
                "use": "official",
                "system": SYSTEM_MRN,
                "value": mrn,
                "type": {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/v2-0203",
                            "code": "MR",
                            "display": "Medical Record Number",
                        }
                    ]
                },
            }
        )
    cpf = getattr(patient, "cpf", "") or ""
    if cpf:
        identifiers.append(
            {
                "use": "official",
                "system": SYSTEM_CPF,
                "value": cpf,
                "type": {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/v2-0203",
                            "code": "NI",
                            "display": "National unique individual identifier",
                        }
                    ]
                },
            }
        )
    return identifiers


def _build_names(patient: Any) -> list[dict[str, Any]]:
    names: list[dict[str, Any]] = []
    full = (getattr(patient, "full_name", "") or "").strip()
    if full:
        parts = full.split()
        family = parts[-1] if len(parts) > 1 else ""
        given = parts[:-1] if len(parts) > 1 else parts
        names.append({"use": "official", "text": full, "family": family, "given": given})
    social = (getattr(patient, "social_name", "") or "").strip()
    if social and social != full:
        names.append({"use": "usual", "text": social})
    return names


def _build_telecom(patient: Any) -> list[dict[str, Any]]:
    telecom: list[dict[str, Any]] = []
    phone = (getattr(patient, "phone", "") or "").strip()
    if phone:
        telecom.append({"system": "phone", "value": phone, "use": "home"})
    whatsapp = (getattr(patient, "whatsapp", "") or "").strip()
    if whatsapp and whatsapp != phone:
        telecom.append({"system": "phone", "value": whatsapp, "use": "mobile"})
    email = (getattr(patient, "email", "") or "").strip()
    if email:
        telecom.append({"system": "email", "value": email})
    return telecom


def _build_address(patient: Any) -> dict[str, Any]:
    raw = getattr(patient, "address", None) or {}
    if not isinstance(raw, dict) or not raw:
        return {}
    line: list[str] = []
    street = (raw.get("street") or "").strip()
    number = (raw.get("number") or "").strip()
    if street:
        line.append(f"{street}, {number}".strip(", "))
    complement = (raw.get("complement") or "").strip()
    if complement:
        line.append(complement)
    neighborhood = (raw.get("neighborhood") or "").strip()
    if neighborhood:
        line.append(neighborhood)

    address: dict[str, Any] = {"use": "home", "country": "BR"}
    if line:
        address["line"] = line
    city = (raw.get("city") or "").strip()
    if city:
        address["city"] = city
    state = (raw.get("state") or "").strip()
    if state:
        address["state"] = state
    postal_code = (raw.get("zip_code") or raw.get("postal_code") or "").strip()
    if postal_code:
        address["postalCode"] = postal_code
    return address
