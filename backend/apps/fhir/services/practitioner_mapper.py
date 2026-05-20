"""
FHIR R4 Practitioner resource mapper.

Maps `apps.emr.Professional` → FHIR R4 Practitioner
(http://hl7.org/fhir/R4/practitioner.html). Pure transform, no DB.

Scope:
- Identifier: one per professional council registry (CRM / CRO / COREN /
  CRF / CREFITO / CRP), system URI per council. The combination
  (council_type, council_number, council_state) is unique in the data
  model — we surface it as a FHIR identifier with the state in the
  identifier's `assigner` slot.
- Name: official name from the linked User. No `usual` name (we don't store
  one at the Professional level).
- Telecom: User email when present.
- Active: from `is_active`.
- Qualification: CBO code (Brazilian Classificação Brasileira de Ocupações)
  when present, plus the council registration itself as a qualification
  with the issuer state.

Out of scope:
- Practitioner.address (not stored on Professional today)
- PractitionerRole (separate resource)
"""

from __future__ import annotations

from typing import Any

# Per-council URIs. Vitali councils all live under the same root namespace;
# the FHIR convention is one system URI per identifier *namespace*, so we
# vary the path per council.
_COUNCIL_BASE = "urn:vitali:council"

# CBO is the Brazilian occupational classification published by MTE; this is
# the canonical URI used by other Brazilian FHIR profiles.
_CBO_SYSTEM = "http://www.saude.gov.br/fhir/r4/CodeSystem/BRCBO"


def professional_to_fhir(professional: Any, *, base_url: str = "") -> dict[str, Any]:
    """Convert one Professional instance to a FHIR R4 Practitioner resource dict."""
    user = getattr(professional, "user", None)
    resource: dict[str, Any] = {
        "resourceType": "Practitioner",
        "id": str(professional.id),
        "active": bool(getattr(professional, "is_active", True)),
        "identifier": _build_identifiers(professional),
        "name": _build_names(user),
        "telecom": _build_telecom(user),
        "qualification": _build_qualifications(professional),
    }
    # Strip empty optional fields so the resource stays compact.
    return {k: v for k, v in resource.items() if v not in (None, [], {})}


def _build_identifiers(professional: Any) -> list[dict[str, Any]]:
    council_type = (getattr(professional, "council_type", "") or "").upper()
    council_number = (getattr(professional, "council_number", "") or "").strip()
    council_state = (getattr(professional, "council_state", "") or "").upper()
    if not (council_type and council_number):
        return []
    return [
        {
            "use": "official",
            "system": f"{_COUNCIL_BASE}/{council_type.lower()}",
            "value": council_number,
            "type": {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/v2-0203",
                        "code": "MD" if council_type == "CRM" else "LN",
                        "display": f"{council_type} license number",
                    }
                ]
            },
            "assigner": {"display": council_state} if council_state else {},
        }
    ]


def _build_names(user: Any) -> list[dict[str, Any]]:
    if user is None:
        return []
    full = (getattr(user, "full_name", "") or "").strip()
    if not full:
        return []
    parts = full.split()
    family = parts[-1] if len(parts) > 1 else ""
    given = parts[:-1] if len(parts) > 1 else parts
    return [{"use": "official", "text": full, "family": family, "given": given}]


def _build_telecom(user: Any) -> list[dict[str, Any]]:
    if user is None:
        return []
    email = (getattr(user, "email", "") or "").strip()
    if not email:
        return []
    return [{"system": "email", "value": email}]


def _build_qualifications(professional: Any) -> list[dict[str, Any]]:
    qualifications: list[dict[str, Any]] = []
    council_type = (getattr(professional, "council_type", "") or "").upper()
    council_state = (getattr(professional, "council_state", "") or "").upper()
    specialty = (getattr(professional, "specialty", "") or "").strip()
    cbo = (getattr(professional, "cbo_code", "") or "").strip()
    if council_type:
        qualifications.append(
            {
                "code": {
                    "coding": [
                        {
                            "system": f"{_COUNCIL_BASE}/{council_type.lower()}",
                            "code": council_type,
                            "display": council_type,
                        }
                    ],
                    "text": (
                        f"{council_type} ({council_state})" if council_state else council_type
                    ),
                },
                "issuer": {"display": council_state} if council_state else {},
            }
        )
    if cbo:
        qualifications.append(
            {
                "code": {
                    "coding": [
                        {
                            "system": _CBO_SYSTEM,
                            "code": cbo,
                            "display": specialty or "CBO code",
                        }
                    ],
                    "text": specialty or cbo,
                }
            }
        )
    elif specialty:
        # Specialty without CBO code — emit as a free-text qualification so
        # the information is not silently dropped.
        qualifications.append({"code": {"text": specialty}})
    # Drop qualification entries whose `issuer` came out empty so the
    # resource stays compact.
    cleaned: list[dict[str, Any]] = []
    for q in qualifications:
        cleaned.append({k: v for k, v in q.items() if v not in (None, {}, [])})
    return cleaned
