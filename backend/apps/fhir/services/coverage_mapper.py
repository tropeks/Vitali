"""
FHIR R4 Coverage resource mapper.

Maps a Vitali ``apps.emr.PatientInsurance`` (convênio) row to a FHIR R4 Coverage
resource (http://hl7.org/fhir/R4/coverage.html). Coverage is the standard channel
EHRs and payer-integration tools use to discover a patient's insurance context.

Mapping decisions:
- `status`: `active` while the card is active, else `cancelled`.
- `beneficiary` / `subscriber`: both reference the Patient. Vitali does not model
  a distinct policy-holder, so the patient is treated as their own subscriber.
- `payor`: the ANS operadora. Vitali has no FHIR Organization resource yet, so the
  payor is a contained-free reference carrying the operadora name (`display`) and
  the ANS code as a business `identifier` (system `urn:vitali:ans`).
- `identifier`: the carteirinha (card number) under `urn:vitali:insurance-card`.

Out of scope: Coverage.class (plan/group tiers), costToBeneficiary, relationship
coding, and a real Organization payor reference.
"""

from __future__ import annotations

from typing import Any

# Business-identifier system URIs (tenant-local, mirroring patient_mapper style).
SYSTEM_ANS = "urn:vitali:ans"  # ANS operadora code
SYSTEM_INSURANCE_CARD = "urn:vitali:insurance-card"  # carteirinha


def patient_insurance_to_fhir(insurance: Any) -> dict[str, Any]:
    """Convert one PatientInsurance instance to a FHIR R4 Coverage resource dict.

    The caller is responsible for permission/module gating.
    """
    patient_ref = {"reference": f"Patient/{insurance.patient_id}"}
    payor: dict[str, Any] = {"display": insurance.provider_name or ""}
    ans_code = (insurance.provider_ans_code or "").strip()
    if ans_code:
        payor["identifier"] = {"system": SYSTEM_ANS, "value": ans_code}

    resource: dict[str, Any] = {
        "resourceType": "Coverage",
        "id": str(insurance.pk),
        "status": "active" if insurance.is_active else "cancelled",
        "beneficiary": patient_ref,
        "subscriber": patient_ref,
        "payor": [payor],
    }

    card = (insurance.card_number or "").strip()
    if card:
        resource["identifier"] = [{"system": SYSTEM_INSURANCE_CARD, "value": card}]
    if insurance.valid_until:
        resource["period"] = {"end": insurance.valid_until.isoformat()}

    return {k: v for k, v in resource.items() if v not in (None, [], {})}
