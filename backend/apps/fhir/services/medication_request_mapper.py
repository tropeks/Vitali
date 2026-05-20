"""
FHIR R4 MedicationRequest mapper.

FHIR models prescriptions as one `MedicationRequest` resource per medication
item — a Vitali `Prescription` therefore maps to N MedicationRequest entries
(one per `PrescriptionItem`). The mapper exposes:

- `prescription_to_fhir_bundle(prescription)` — returns the list of FHIR
  MedicationRequest resources covering every item on a Vitali prescription.
  Used by the search endpoint when listing all items.
- `prescription_item_to_fhir(item)` — single-resource transform; the FHIR id
  is the PrescriptionItem id, with a stable `groupIdentifier` carrying the
  parent Vitali Prescription uuid so the items can be grouped client-side.

Out of scope (follow-up):
- Medication resource (we emit `medicationCodeableConcept` inline with
  generic_name; the contained Medication resource would carry RxNorm /
  ANVISA codes once those are wired into the catalogue).
- DispenseRequest (pharmacy-side; tracked in our pharmacy module).
- Substitution / priorPrescription chains.
"""

from __future__ import annotations

from typing import Any

# Vitali Prescription.status → FHIR MedicationRequest.status (constrained:
# active | on-hold | cancelled | completed | entered-in-error | stopped |
# draft | unknown). The mapping below favours the FHIR vocab closest to the
# Vitali lifecycle.
_STATUS_MAP = {
    "draft": "draft",
    "signed": "active",
    "partially_dispensed": "active",
    "dispensed": "completed",
    "cancelled": "cancelled",
}


def prescription_item_to_fhir(item: Any, *, base_url: str = "") -> dict[str, Any]:
    """Convert one PrescriptionItem to a FHIR MedicationRequest resource."""
    prescription = getattr(item, "prescription", None)
    patient = getattr(prescription, "patient", None) if prescription else None
    prescriber = getattr(prescription, "prescriber", None) if prescription else None
    encounter = getattr(prescription, "encounter", None) if prescription else None

    status_value = getattr(prescription, "status", "draft") if prescription else "draft"

    resource: dict[str, Any] = {
        "resourceType": "MedicationRequest",
        "id": str(item.id),
        "status": _STATUS_MAP.get(status_value, "unknown"),
        "intent": "order",
        "subject": _ref(patient, "Patient", base_url),
    }
    if encounter is not None:
        resource["encounter"] = _ref(encounter, "Encounter", base_url)
    if prescriber is not None:
        resource["requester"] = _ref(prescriber, "Practitioner", base_url)

    resource["medicationCodeableConcept"] = _medication_concept(item)

    if prescription is not None:
        resource["groupIdentifier"] = {
            "use": "official",
            "system": "urn:vitali:prescription",
            "value": str(prescription.id),
        }
        signed_at = getattr(prescription, "signed_at", None)
        if signed_at is not None:
            resource["authoredOn"] = signed_at.isoformat()
        elif getattr(prescription, "created_at", None) is not None:
            resource["authoredOn"] = prescription.created_at.isoformat()

    dosage = _dosage_instruction(item)
    if dosage:
        resource["dosageInstruction"] = [dosage]

    return {k: v for k, v in resource.items() if v not in (None, [], {})}


def prescription_to_fhir_bundle(prescription: Any, *, base_url: str = "") -> list[dict[str, Any]]:
    """Return the list of MedicationRequest resources for a Prescription."""
    items = getattr(prescription, "items", None)
    if items is None:
        return []
    iterable = items.all() if hasattr(items, "all") else items
    return [prescription_item_to_fhir(it, base_url=base_url) for it in iterable]


def _ref(obj: Any, type_name: str, base_url: str) -> dict[str, Any]:
    if obj is None:
        return {}
    ref = f"{type_name}/{obj.pk}"
    full = f"{base_url}/{ref}" if base_url else ref
    out: dict[str, Any] = {"reference": full, "type": type_name}
    display = getattr(obj, "full_name", None) or getattr(obj, "__str__", lambda: None)()
    if display:
        out["display"] = str(display)
    return out


def _medication_concept(item: Any) -> dict[str, Any]:
    name = (getattr(item, "generic_name", "") or "").strip()
    if not name:
        drug = getattr(item, "drug", None)
        if drug is not None:
            name = (getattr(drug, "generic_name", "") or getattr(drug, "name", "") or "").strip()
    if not name:
        name = "Unspecified medication"
    return {"text": name}


def _dosage_instruction(item: Any) -> dict[str, Any]:
    quantity = getattr(item, "quantity", None)
    unit = (getattr(item, "unit_of_measure", "") or "").strip()
    instructions = (getattr(item, "dosage_instructions", "") or "").strip()
    out: dict[str, Any] = {}
    if instructions:
        out["text"] = instructions
    if quantity is not None and unit:
        out["doseAndRate"] = [
            {"doseQuantity": {"value": float(quantity), "unit": unit, "system": "urn:vitali:unit"}}
        ]
    return out
