"""Unit tests for the FHIR R4 AllergyIntolerance mapper."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from apps.fhir.services.allergy_mapper import (
    CLINICAL_STATUS_SYSTEM,
    allergy_to_fhir,
)


def _patient(pk="pat-uuid", full_name="Ana Souza"):
    return SimpleNamespace(pk=pk, full_name=full_name)


def _allergy(**overrides):
    base = {
        "id": "all-uuid",
        "patient": _patient(),
        "substance": "Penicilina",
        "reaction": "Urticária generalizada",
        "severity": "moderate",
        "status": "active",
        "confirmed_by": SimpleNamespace(pk=1),
        "confirmed_by_id": 1,
        "created_at": datetime(2026, 5, 20, 12, 0, tzinfo=UTC),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class TestAllergyMapper:
    def test_resource_type_and_id(self):
        resource = allergy_to_fhir(_allergy())
        assert resource["resourceType"] == "AllergyIntolerance"
        assert resource["id"] == "all-uuid"

    def test_clinical_status_active(self):
        resource = allergy_to_fhir(_allergy())
        coding = resource["clinicalStatus"]["coding"][0]
        assert coding["system"] == CLINICAL_STATUS_SYSTEM
        assert coding["code"] == "active"

    def test_clinical_status_resolved(self):
        resource = allergy_to_fhir(_allergy(status="resolved"))
        assert resource["clinicalStatus"]["coding"][0]["code"] == "resolved"

    def test_criticality_high_for_severe_severity(self):
        for sev in ("moderate", "severe", "life_threatening"):
            resource = allergy_to_fhir(_allergy(severity=sev))
            assert resource["criticality"] == "high"

    def test_criticality_low_for_mild(self):
        resource = allergy_to_fhir(_allergy(severity="mild"))
        assert resource["criticality"] == "low"

    def test_verification_status_confirmed_when_confirmed_by_present(self):
        resource = allergy_to_fhir(_allergy())
        coding = resource["verificationStatus"]["coding"][0]
        assert coding["code"] == "confirmed"

    def test_verification_status_unconfirmed_when_not_confirmed(self):
        resource = allergy_to_fhir(_allergy(confirmed_by=None, confirmed_by_id=None))
        coding = resource["verificationStatus"]["coding"][0]
        assert coding["code"] == "unconfirmed"

    def test_substance_emitted_in_code_text(self):
        resource = allergy_to_fhir(_allergy())
        assert resource["code"]["text"] == "Penicilina"

    def test_patient_reference_emitted(self):
        resource = allergy_to_fhir(_allergy())
        ref = resource["patient"]
        assert ref["reference"] == "Patient/pat-uuid"
        assert ref["display"] == "Ana Souza"

    def test_reaction_manifestation_and_severity(self):
        resource = allergy_to_fhir(_allergy(severity="severe"))
        reaction = resource["reaction"][0]
        assert reaction["manifestation"][0]["text"] == "Urticária generalizada"
        assert reaction["severity"] == "severe"

    def test_no_reaction_omits_reaction_field(self):
        resource = allergy_to_fhir(_allergy(reaction=""))
        assert "reaction" not in resource

    def test_recorded_date_iso(self):
        resource = allergy_to_fhir(_allergy())
        assert resource["recordedDate"] == "2026-05-20T12:00:00+00:00"
