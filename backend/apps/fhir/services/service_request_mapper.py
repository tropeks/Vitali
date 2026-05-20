"""
FHIR R4 ServiceRequest mapper.

Maps `apps.emr.ClinicalDocument` rows whose `doc_type` is `referral` or
`exam_request` to FHIR ServiceRequest resources
(http://hl7.org/fhir/R4/servicerequest.html).

Mapping decisions:
- `status`: `draft` when unsigned, `active` once signed. `revoked` only when
  the underlying record is soft-marked unsigned by an amendment (not modelled
  yet, so we ship draft / active for now).
- `intent`: `order` for both referral and exam request — both are clinical
  orders. FHIR distinguishes `proposal` / `plan` / `order` / `original-order`
  but Vitali clinical documents are always orders signed by the prescriber.
- `category`: differentiates between `referral` and `exam_request`. The
  `referral` doc maps to the FHIR category `referral`; `exam_request` maps
  to `laboratory` / `imaging` — without a finer-grained discriminator on
  the document we default to `laboratory` and surface the original Vitali
  type in `category.text` so consumers can disambiguate.

Out of scope:
- Linking the referred specialist (no model field today).
- Lab catalogue codes (LOINC) — exam requests are free-text in Vitali
  currently; CID-10 + procedure code mapping is a follow-up.
"""

from __future__ import annotations

from typing import Any

CATEGORY_SYSTEM = "http://snomed.info/sct"

# Vitali doc_type → (FHIR category code, display, original Vitali display)
_CATEGORY_MAP = {
    "referral": ("306206005", "Referral to service", "Encaminhamento"),
    "exam_request": ("108252007", "Laboratory procedure", "Solicitação de exame"),
}


def clinical_document_to_fhir(document: Any, *, base_url: str = "") -> dict[str, Any]:
    """Convert one ClinicalDocument to a FHIR ServiceRequest resource."""
    doc_type = (getattr(document, "doc_type", "") or "").lower()
    encounter = getattr(document, "encounter", None)
    patient = getattr(encounter, "patient", None) if encounter else None
    professional = getattr(encounter, "professional", None) if encounter else None

    resource: dict[str, Any] = {
        "resourceType": "ServiceRequest",
        "id": str(document.id),
        "status": "active" if getattr(document, "is_signed", False) else "draft",
        "intent": "order",
        "category": [_category(doc_type)],
        "code": {"text": (getattr(document, "content", "") or "")[:200] or doc_type or "Order"},
        "subject": _ref(patient, "Patient", base_url, getattr(patient, "full_name", "")),
    }
    if encounter is not None:
        resource["encounter"] = _ref(encounter, "Encounter", base_url)
    if professional is not None:
        resource["requester"] = _ref(professional, "Practitioner", base_url)

    authored = getattr(document, "signed_at", None) or getattr(document, "created_at", None)
    if authored is not None:
        resource["authoredOn"] = authored.isoformat()

    notes = (getattr(document, "content", "") or "").strip()
    if notes and len(notes) > 200:
        resource["note"] = [{"text": notes}]

    return {k: v for k, v in resource.items() if v not in (None, [], {})}


def _category(doc_type: str) -> dict[str, Any]:
    code, display, vitali_label = _CATEGORY_MAP.get(
        doc_type, ("", doc_type or "Order", doc_type or "Order")
    )
    cat: dict[str, Any] = {"text": vitali_label}
    if code:
        cat["coding"] = [{"system": CATEGORY_SYSTEM, "code": code, "display": display}]
    return cat


def _ref(obj: Any, type_name: str, base_url: str, display: str = "") -> dict[str, Any]:
    if obj is None:
        return {}
    ref = f"{type_name}/{obj.pk}"
    full = f"{base_url}/{ref}" if base_url else ref
    out: dict[str, Any] = {"reference": full, "type": type_name}
    if display:
        out["display"] = display
    return out
