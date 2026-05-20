"""Unit tests for the FHIR R4 Observation mapper (VitalSigns → Observation)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from apps.fhir.services.observation_mapper import (
    LOINC_SYSTEM,
    vital_signs_observation,
    vital_signs_to_fhir_bundle,
)


def _patient(pk="pat-1", full_name="Ana Souza"):
    return SimpleNamespace(pk=pk, full_name=full_name)


def _encounter(pk="enc-1", patient=None):
    return SimpleNamespace(pk=pk, patient=patient or _patient())


def _vital_signs(**overrides):
    base = {
        "encounter_id": "enc-1",
        "encounter": _encounter(),
        "weight_kg": 70.5,
        "height_cm": 175,
        "blood_pressure_systolic": 120,
        "blood_pressure_diastolic": 80,
        "heart_rate": 72,
        "temperature_celsius": 36.5,
        "oxygen_saturation": 98,
        "bmi": 23.0,
        "recorded_at": datetime(2026, 5, 20, 14, 0, tzinfo=UTC),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class TestObservationMapper:
    def test_bundle_emits_one_observation_per_vital(self):
        bundle = vital_signs_to_fhir_bundle(_vital_signs())
        codes = {obs["code"]["coding"][0]["code"] for obs in bundle}
        # 7 stored vitals + computed BMI = 8 observations.
        assert {
            "29463-7",
            "8302-2",
            "8480-6",
            "8462-4",
            "8867-4",
            "8310-5",
            "59408-5",
            "39156-5",
        }.issubset(codes)
        assert len(bundle) == 8

    def test_missing_vital_omits_observation(self):
        vs = _vital_signs(temperature_celsius=None, bmi=None)
        codes = {obs["code"]["coding"][0]["code"] for obs in vital_signs_to_fhir_bundle(vs)}
        assert "8310-5" not in codes  # temperature
        assert "39156-5" not in codes  # bmi

    def test_observation_id_is_encounter_plus_loinc(self):
        bundle = vital_signs_to_fhir_bundle(_vital_signs())
        ids = {obs["id"] for obs in bundle}
        assert "enc-1_29463-7" in ids

    def test_loinc_and_ucum_systems_present(self):
        bundle = vital_signs_to_fhir_bundle(_vital_signs())
        for obs in bundle:
            assert obs["code"]["coding"][0]["system"] == LOINC_SYSTEM
            assert obs["valueQuantity"]["system"] == "http://unitsofmeasure.org"

    def test_status_is_final_and_category_is_vital_signs(self):
        bundle = vital_signs_to_fhir_bundle(_vital_signs())
        for obs in bundle:
            assert obs["status"] == "final"
            assert obs["category"][0]["coding"][0]["code"] == "vital-signs"

    def test_subject_and_encounter_references_emitted(self):
        bundle = vital_signs_to_fhir_bundle(_vital_signs())
        for obs in bundle:
            assert obs["subject"]["reference"] == "Patient/pat-1"
            assert obs["encounter"]["reference"] == "Encounter/enc-1"

    def test_effective_datetime_is_recorded_at(self):
        bundle = vital_signs_to_fhir_bundle(_vital_signs())
        assert bundle[0]["effectiveDateTime"] == "2026-05-20T14:00:00+00:00"

    def test_vital_signs_observation_returns_matching_code(self):
        vs = _vital_signs()
        obs = vital_signs_observation(vs, code="8480-6")
        assert obs is not None
        assert obs["code"]["coding"][0]["code"] == "8480-6"
        assert obs["valueQuantity"]["value"] == 120.0

    def test_vital_signs_observation_unknown_code_returns_none(self):
        assert vital_signs_observation(_vital_signs(), code="00000-0") is None

    def test_vital_signs_observation_bmi_uses_computed_property(self):
        obs = vital_signs_observation(_vital_signs(bmi=24.7), code="39156-5")
        assert obs is not None
        assert obs["valueQuantity"]["value"] == 24.7
        assert obs["valueQuantity"]["unit"] == "kg/m2"

    def test_bundle_for_none_vital_signs_returns_empty(self):
        assert vital_signs_to_fhir_bundle(None) == []
