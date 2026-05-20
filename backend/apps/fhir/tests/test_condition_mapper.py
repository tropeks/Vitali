"""Unit tests for the FHIR R4 Condition mapper (MedicalHistory → Condition)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

from apps.fhir.services.condition_mapper import (
    CID10_SYSTEM,
    medical_history_to_fhir,
)


def _patient(pk="pat-1", full_name="Ana"):
    return SimpleNamespace(pk=pk, full_name=full_name)


def _history(**overrides):
    base = {
        "id": "cond-1",
        "patient": _patient(),
        "condition": "Diabetes Mellitus tipo 2",
        "cid10_code": "E11",
        "type": "chronic",
        "status": "active",
        "onset_date": date(2019, 3, 1),
        "notes": "Boa adesão ao tratamento.",
        "created_at": datetime(2026, 1, 10, 12, 0, tzinfo=UTC),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class TestConditionMapper:
    def test_resource_type_and_id(self):
        resource = medical_history_to_fhir(_history())
        assert resource["resourceType"] == "Condition"
        assert resource["id"] == "cond-1"

    def test_cid10_emitted_as_coding(self):
        resource = medical_history_to_fhir(_history())
        coding = resource["code"]["coding"][0]
        assert coding["system"] == CID10_SYSTEM
        assert coding["code"] == "E11"
        assert resource["code"]["text"] == "Diabetes Mellitus tipo 2"

    def test_no_cid10_omits_coding(self):
        resource = medical_history_to_fhir(_history(cid10_code=""))
        assert "coding" not in resource["code"]
        assert resource["code"]["text"] == "Diabetes Mellitus tipo 2"

    def test_active_status(self):
        resource = medical_history_to_fhir(_history())
        assert resource["clinicalStatus"]["coding"][0]["code"] == "active"

    def test_controlled_status_maps_to_active_with_note(self):
        resource = medical_history_to_fhir(_history(status="controlled"))
        assert resource["clinicalStatus"]["coding"][0]["code"] == "active"
        notes = [n.get("text") for n in resource["note"]]
        assert any("controlada" in (text or "") for text in notes)

    def test_resolved_status(self):
        resource = medical_history_to_fhir(_history(status="resolved"))
        assert resource["clinicalStatus"]["coding"][0]["code"] == "resolved"

    def test_chronic_type_maps_to_problem_list_item(self):
        resource = medical_history_to_fhir(_history(type="chronic"))
        assert resource["category"][0]["coding"][0]["code"] == "problem-list-item"

    def test_surgical_type_maps_to_encounter_diagnosis(self):
        resource = medical_history_to_fhir(_history(type="surgical"))
        assert resource["category"][0]["coding"][0]["code"] == "encounter-diagnosis"

    def test_family_type_keeps_encounter_diagnosis_with_family_text(self):
        resource = medical_history_to_fhir(_history(type="family"))
        assert resource["category"][0]["coding"][0]["code"] == "encounter-diagnosis"
        assert resource["category"][0]["text"] == "Family history"

    def test_onset_date_iso8601(self):
        resource = medical_history_to_fhir(_history())
        assert resource["onsetDateTime"] == "2019-03-01"

    def test_notes_emitted_as_note_text(self):
        resource = medical_history_to_fhir(_history())
        notes = [n["text"] for n in resource["note"]]
        assert "Boa adesão ao tratamento." in notes

    def test_subject_reference_emitted(self):
        resource = medical_history_to_fhir(_history())
        assert resource["subject"]["reference"] == "Patient/pat-1"
        assert resource["subject"]["display"] == "Ana"

    def test_verification_status_is_confirmed(self):
        resource = medical_history_to_fhir(_history())
        assert resource["verificationStatus"]["coding"][0]["code"] == "confirmed"
