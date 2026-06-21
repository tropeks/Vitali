"""
FHIR R4 DocumentReference resource mapper.

Maps `apps.emr.ClinicalDocument` rows whose `doc_type` is `certificate`
(Atestado Médico) to a FHIR R4 DocumentReference
(http://hl7.org/fhir/R4/documentreference.html) — the standard resource for
indexing and retrieving a clinical document/attachment.

Mapping decisions:
- `status` is always `current` (Vitali never tombstones documents in place);
  `docStatus` is `final` once signed, else `preliminary`.
- `content.attachment` embeds the document body inline as base64 `text/plain`.
  The body is decrypted server-side; callers are already `fhir.read`-gated, the
  same trust boundary under which every other clinical resource is exposed.
- `author` references the encounter's Practitioner when one is linked.

Diagnostic findings (doc_type `report`) are deliberately NOT surfaced here — they
map to DiagnosticReport. Referral / exam-request documents map to ServiceRequest.
"""

from __future__ import annotations

import base64
from typing import Any

DOCUMENT_TYPE_SYSTEM = "urn:vitali:document-type"

# Vitali doc_type → (FHIR type code, display) for the document-type CodeableConcept.
_TYPE_DISPLAY = {
    "certificate": "Atestado Médico",
}


def clinical_document_to_document_reference(document: Any) -> dict[str, Any]:
    """Convert one ClinicalDocument (certificate) to a FHIR DocumentReference dict.

    The caller is responsible for permission/module gating and for ensuring the
    document's `doc_type` is a DocumentReference-eligible type.
    """
    encounter = document.encounter
    patient_id = encounter.patient_id
    signed = document.signed_at is not None
    when = document.signed_at or document.created_at
    display = _TYPE_DISPLAY.get(document.doc_type, document.get_doc_type_display())

    resource: dict[str, Any] = {
        "resourceType": "DocumentReference",
        "id": str(document.pk),
        "status": "current",
        "docStatus": "final" if signed else "preliminary",
        "type": {
            "coding": [
                {"system": DOCUMENT_TYPE_SYSTEM, "code": document.doc_type, "display": display}
            ],
            "text": display,
        },
        "subject": {"reference": f"Patient/{patient_id}"},
        "content": [_attachment(document, title=display)],
        "context": {"encounter": [{"reference": f"Encounter/{document.encounter_id}"}]},
    }
    if when is not None:
        resource["date"] = when.isoformat()

    author = _author_reference(encounter)
    if author is not None:
        resource["author"] = [author]

    return {k: v for k, v in resource.items() if v not in (None, [], {})}


def _attachment(document: Any, *, title: str) -> dict[str, Any]:
    body = document.content or ""
    attachment: dict[str, Any] = {
        "contentType": "text/plain",
        "data": base64.b64encode(body.encode("utf-8")).decode("ascii"),
        "title": title,
    }
    if document.created_at is not None:
        attachment["creation"] = document.created_at.isoformat()
    return {"attachment": attachment}


def _author_reference(encounter: Any) -> dict[str, Any] | None:
    professional = getattr(encounter, "professional", None)
    if professional is None:
        return None
    ref: dict[str, Any] = {"reference": f"Practitioner/{professional.pk}"}
    user = getattr(professional, "user", None)
    name = (getattr(user, "full_name", "") or "").strip()
    if name:
        ref["display"] = name
    return ref
