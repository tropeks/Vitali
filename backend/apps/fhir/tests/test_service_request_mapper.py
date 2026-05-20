"""Unit tests for the FHIR R4 ServiceRequest mapper."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from apps.fhir.services.service_request_mapper import (
    CATEGORY_SYSTEM,
    clinical_document_to_fhir,
)


def _patient(pk="pat-1", full_name="Ana"):
    return SimpleNamespace(pk=pk, full_name=full_name)


def _professional(pk="prof-1"):
    return SimpleNamespace(pk=pk)


def _encounter(patient=None, professional=None):
    return SimpleNamespace(
        pk="enc-1",
        patient=patient or _patient(),
        professional=professional or _professional(),
    )


def _document(**overrides):
    base = {
        "id": "doc-1",
        "encounter": _encounter(),
        "doc_type": "referral",
        "content": "Encaminhamento para cardiologia.",
        "signed_at": datetime(2026, 5, 20, 12, 0, tzinfo=UTC),
        "created_at": datetime(2026, 5, 20, 11, 0, tzinfo=UTC),
        "is_signed": True,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class TestServiceRequestMapper:
    def test_resource_type_and_id(self):
        resource = clinical_document_to_fhir(_document())
        assert resource["resourceType"] == "ServiceRequest"
        assert resource["id"] == "doc-1"

    def test_signed_document_status_active(self):
        resource = clinical_document_to_fhir(_document())
        assert resource["status"] == "active"

    def test_unsigned_document_status_draft(self):
        resource = clinical_document_to_fhir(_document(signed_at=None, is_signed=False))
        assert resource["status"] == "draft"

    def test_intent_is_order(self):
        assert clinical_document_to_fhir(_document())["intent"] == "order"

    def test_referral_category_uses_snomed_code(self):
        resource = clinical_document_to_fhir(_document(doc_type="referral"))
        coding = resource["category"][0]["coding"][0]
        assert coding["system"] == CATEGORY_SYSTEM
        assert coding["code"] == "306206005"
        assert resource["category"][0]["text"] == "Encaminhamento"

    def test_exam_request_category_uses_laboratory_code(self):
        resource = clinical_document_to_fhir(_document(doc_type="exam_request"))
        coding = resource["category"][0]["coding"][0]
        assert coding["code"] == "108252007"
        assert resource["category"][0]["text"] == "Solicitação de exame"

    def test_subject_reference_emitted(self):
        resource = clinical_document_to_fhir(_document())
        assert resource["subject"]["reference"] == "Patient/pat-1"
        assert resource["subject"]["display"] == "Ana"

    def test_encounter_and_requester_references(self):
        resource = clinical_document_to_fhir(_document())
        assert resource["encounter"]["reference"] == "Encounter/enc-1"
        assert resource["requester"]["reference"] == "Practitioner/prof-1"

    def test_code_text_truncated_to_200_chars(self):
        long_content = "x" * 500
        resource = clinical_document_to_fhir(_document(content=long_content))
        assert len(resource["code"]["text"]) == 200

    def test_long_content_emitted_as_note(self):
        long_content = "x" * 500
        resource = clinical_document_to_fhir(_document(content=long_content))
        assert resource["note"][0]["text"] == long_content

    def test_short_content_does_not_emit_note(self):
        resource = clinical_document_to_fhir(_document(content="Curto."))
        assert "note" not in resource

    def test_authored_on_uses_signed_at_when_present(self):
        resource = clinical_document_to_fhir(_document())
        assert resource["authoredOn"] == "2026-05-20T12:00:00+00:00"

    def test_authored_on_falls_back_to_created_at(self):
        resource = clinical_document_to_fhir(_document(signed_at=None, is_signed=False))
        assert resource["authoredOn"] == "2026-05-20T11:00:00+00:00"
