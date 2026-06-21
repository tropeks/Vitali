"""
FHIR R4 DiagnosticReport resource mapper.

Maps `apps.emr.ClinicalDocument` rows whose `doc_type` is `report` (Laudo) to a
FHIR R4 DiagnosticReport (http://hl7.org/fhir/R4/diagnosticreport.html) — the
standard resource carrying the findings/interpretation of a diagnostic study.

Mapping decisions:
- `status`: `final` once signed, else `preliminary`.
- `code` is required by FHIR; Vitali laudos are free-text without a discrete study
  code, so a generic LOINC report code is used with the Vitali label as `text`.
- `conclusion` carries the decrypted laudo body; `presentedForm` additionally
  embeds it as a base64 `text/plain` attachment for clients that prefer the
  document form. Callers are `fhir.read`-gated, the same trust boundary as every
  other clinical resource.
- `performer` references the encounter's Practitioner when one is linked.

Out of scope: discrete `result` Observations (lab analytes), `category` by service
section, and specimen linkage — Vitali laudos are narrative today.
"""

from __future__ import annotations

import base64
from typing import Any

# LOINC 11502-2 "Laboratory report" — a generic stand-in until discrete study
# codes are curated. The human-readable Vitali label rides along in `code.text`.
_REPORT_LOINC = {"system": "http://loinc.org", "code": "11502-2", "display": "Laboratory report"}


def clinical_document_to_diagnostic_report(document: Any) -> dict[str, Any]:
    """Convert one ClinicalDocument (report) to a FHIR DiagnosticReport dict.

    The caller is responsible for permission/module gating and for ensuring the
    document's `doc_type` is DiagnosticReport-eligible.
    """
    encounter = document.encounter
    patient_id = encounter.patient_id
    signed = document.signed_at is not None
    when = document.signed_at or document.created_at
    body = document.content or ""

    resource: dict[str, Any] = {
        "resourceType": "DiagnosticReport",
        "id": str(document.pk),
        "status": "final" if signed else "preliminary",
        "code": {"coding": [_REPORT_LOINC], "text": document.get_doc_type_display()},
        "subject": {"reference": f"Patient/{patient_id}"},
        "encounter": {"reference": f"Encounter/{document.encounter_id}"},
    }
    if when is not None:
        resource["effectiveDateTime"] = when.isoformat()
        resource["issued"] = when.isoformat()
    if body:
        resource["conclusion"] = body
        resource["presentedForm"] = [
            {
                "contentType": "text/plain",
                "data": base64.b64encode(body.encode("utf-8")).decode("ascii"),
                "title": document.get_doc_type_display(),
            }
        ]

    performer = _performer_reference(encounter)
    if performer is not None:
        resource["performer"] = [performer]

    return {k: v for k, v in resource.items() if v not in (None, [], {})}


def _performer_reference(encounter: Any) -> dict[str, Any] | None:
    professional = getattr(encounter, "professional", None)
    if professional is None:
        return None
    ref: dict[str, Any] = {"reference": f"Practitioner/{professional.pk}"}
    user = getattr(professional, "user", None)
    name = (getattr(user, "full_name", "") or "").strip()
    if name:
        ref["display"] = name
    return ref
