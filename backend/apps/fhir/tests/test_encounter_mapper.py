"""
Unit tests for the FHIR R4 Encounter mapper (pure transform, no DB).
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from apps.fhir.services.encounter_mapper import encounter_to_fhir


def _user(full_name="Dra Ana Silva", email="ana@example.com"):
    return SimpleNamespace(full_name=full_name, email=email)


def _professional(user=None, pk="prof-uuid"):
    return SimpleNamespace(pk=pk, user=user)


def _patient(full_name="Bruno Lima", pk="pat-uuid"):
    return SimpleNamespace(pk=pk, full_name=full_name)


def _encounter(**overrides):
    base = {
        "id": "enc-uuid",
        "patient": _patient(),
        "professional": _professional(user=_user()),
        "status": "open",
        "encounter_date": datetime(2026, 5, 20, 9, 30, tzinfo=UTC),
        "signed_at": None,
        "chief_complaint": "Dor de cabeça há 3 dias.",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class TestEncounterMapper:
    def test_open_encounter_maps_to_in_progress(self):
        resource = encounter_to_fhir(_encounter())
        assert resource["resourceType"] == "Encounter"
        assert resource["status"] == "in-progress"
        assert resource["id"] == "enc-uuid"

    def test_signed_encounter_maps_to_finished_with_end_period(self):
        end = datetime(2026, 5, 20, 10, 5, tzinfo=UTC)
        resource = encounter_to_fhir(_encounter(status="signed", signed_at=end))
        assert resource["status"] == "finished"
        assert resource["period"]["end"] == end.isoformat()

    def test_cancelled_status_passes_through(self):
        resource = encounter_to_fhir(_encounter(status="cancelled"))
        assert resource["status"] == "cancelled"

    def test_unknown_status_maps_to_unknown(self):
        resource = encounter_to_fhir(_encounter(status="something_weird"))
        assert resource["status"] == "unknown"

    def test_ambulatory_class_always_present(self):
        resource = encounter_to_fhir(_encounter())
        assert resource["class"]["code"] == "AMB"
        assert resource["class"]["system"].endswith("v3-ActCode")

    def test_subject_reference_points_at_patient(self):
        resource = encounter_to_fhir(_encounter())
        assert resource["subject"]["reference"] == "Patient/pat-uuid"
        assert resource["subject"]["type"] == "Patient"
        assert resource["subject"]["display"] == "Bruno Lima"

    def test_participant_emits_practitioner_reference(self):
        resource = encounter_to_fhir(_encounter())
        participant = resource["participant"][0]
        assert participant["individual"]["reference"] == "Practitioner/prof-uuid"
        assert participant["individual"]["display"] == "Dra Ana Silva"
        assert participant["type"][0]["coding"][0]["code"] == "PPRF"

    def test_chief_complaint_becomes_reason_code(self):
        resource = encounter_to_fhir(_encounter())
        assert resource["reasonCode"][0]["text"] == "Dor de cabeça há 3 dias."

    def test_empty_chief_complaint_omits_reason_code(self):
        resource = encounter_to_fhir(_encounter(chief_complaint=""))
        assert "reasonCode" not in resource

    def test_period_start_is_iso8601(self):
        resource = encounter_to_fhir(_encounter())
        assert resource["period"]["start"] == "2026-05-20T09:30:00+00:00"
        assert "end" not in resource["period"]

    def test_base_url_prepended_when_provided(self):
        resource = encounter_to_fhir(_encounter(), base_url="https://api.example.com/fhir")
        assert resource["subject"]["reference"] == "https://api.example.com/fhir/Patient/pat-uuid"
        assert resource["participant"][0]["individual"]["reference"].startswith(
            "https://api.example.com/fhir/Practitioner/"
        )
