"""Unit tests for the FHIR R4 MedicationRequest mapper."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from apps.fhir.services.medication_request_mapper import (
    prescription_item_to_fhir,
    prescription_to_fhir_bundle,
)


def _patient(pk="pat-1", full_name="Ana Souza"):
    return SimpleNamespace(pk=pk, full_name=full_name)


def _professional(pk="prof-1", user_name="Dra Bia"):
    return SimpleNamespace(pk=pk, full_name=user_name)


def _encounter(pk="enc-1"):
    return SimpleNamespace(pk=pk)


def _prescription(**overrides):
    base = {
        "id": "rx-1",
        "pk": "rx-1",
        "patient": _patient(),
        "prescriber": _professional(),
        "encounter": _encounter(),
        "status": "signed",
        "signed_at": datetime(2026, 5, 20, 10, 0, tzinfo=UTC),
        "created_at": datetime(2026, 5, 20, 9, 30, tzinfo=UTC),
        "items": SimpleNamespace(all=lambda: []),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _drug(name="Amoxicilina"):
    return SimpleNamespace(generic_name=name, name=name)


def _item(**overrides):
    rx = _prescription()
    base = {
        "id": "item-1",
        "prescription": rx,
        "drug": _drug(),
        "generic_name": "Amoxicilina 500mg",
        "quantity": 21,
        "unit_of_measure": "cápsula",
        "dosage_instructions": "1 cápsula 8/8h por 7 dias.",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class TestMedicationRequestMapper:
    def test_resource_type_and_id_are_item_level(self):
        resource = prescription_item_to_fhir(_item())
        assert resource["resourceType"] == "MedicationRequest"
        assert resource["id"] == "item-1"

    def test_intent_is_order(self):
        assert prescription_item_to_fhir(_item())["intent"] == "order"

    def test_status_signed_maps_to_active(self):
        assert prescription_item_to_fhir(_item())["status"] == "active"

    def test_status_dispensed_maps_to_completed(self):
        rx = _prescription(status="dispensed")
        resource = prescription_item_to_fhir(_item(prescription=rx))
        assert resource["status"] == "completed"

    def test_status_draft_passes_through(self):
        rx = _prescription(status="draft", signed_at=None)
        resource = prescription_item_to_fhir(_item(prescription=rx))
        assert resource["status"] == "draft"

    def test_subject_and_requester_references(self):
        resource = prescription_item_to_fhir(_item())
        assert resource["subject"]["reference"] == "Patient/pat-1"
        assert resource["requester"]["reference"] == "Practitioner/prof-1"

    def test_encounter_reference(self):
        resource = prescription_item_to_fhir(_item())
        assert resource["encounter"]["reference"] == "Encounter/enc-1"

    def test_medication_concept_uses_generic_name(self):
        resource = prescription_item_to_fhir(_item())
        assert resource["medicationCodeableConcept"]["text"] == "Amoxicilina 500mg"

    def test_medication_concept_falls_back_to_drug_when_generic_blank(self):
        resource = prescription_item_to_fhir(_item(generic_name="", drug=_drug("Dipirona")))
        assert resource["medicationCodeableConcept"]["text"] == "Dipirona"

    def test_group_identifier_carries_parent_prescription_id(self):
        resource = prescription_item_to_fhir(_item())
        gi = resource["groupIdentifier"]
        assert gi["system"] == "urn:vitali:prescription"
        assert gi["value"] == "rx-1"

    def test_authored_on_uses_signed_at_when_present(self):
        resource = prescription_item_to_fhir(_item())
        assert resource["authoredOn"] == "2026-05-20T10:00:00+00:00"

    def test_authored_on_falls_back_to_created_at_when_unsigned(self):
        rx = _prescription(status="draft", signed_at=None)
        resource = prescription_item_to_fhir(_item(prescription=rx))
        assert resource["authoredOn"] == "2026-05-20T09:30:00+00:00"

    def test_dosage_instruction_text_and_quantity(self):
        resource = prescription_item_to_fhir(_item())
        dosage = resource["dosageInstruction"][0]
        assert dosage["text"] == "1 cápsula 8/8h por 7 dias."
        assert dosage["doseAndRate"][0]["doseQuantity"]["value"] == 21.0
        assert dosage["doseAndRate"][0]["doseQuantity"]["unit"] == "cápsula"

    def test_bundle_returns_one_entry_per_item(self):
        rx = _prescription()
        rx.items = SimpleNamespace(all=lambda: [_item(id="i-a"), _item(id="i-b")])
        bundle = prescription_to_fhir_bundle(rx)
        assert {res["id"] for res in bundle} == {"i-a", "i-b"}
