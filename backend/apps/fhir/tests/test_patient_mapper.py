"""
Unit tests for the FHIR R4 Patient mapper (pure transform, no DB).
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from apps.fhir.services.patient_mapper import (
    SYSTEM_CPF,
    SYSTEM_MRN,
    patient_to_fhir,
)


def _patient(**overrides):
    base = {
        "id": "d3d3e1f5-1111-4111-8111-111111111111",
        "medical_record_number": "2026000001",
        "full_name": "Ana Maria Souza",
        "social_name": "",
        "cpf": "123.456.789-09",
        "birth_date": date(1985, 7, 14),
        "gender": "F",
        "phone": "11 3000-1000",
        "whatsapp": "11 99999-1234",
        "email": "ana@example.com",
        "is_active": True,
        "address": {
            "street": "Rua das Acácias",
            "number": "120",
            "complement": "Apto 7",
            "neighborhood": "Centro",
            "city": "São Paulo",
            "state": "SP",
            "zip_code": "01000-000",
        },
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class TestPatientMapper:
    def test_maps_core_demographics(self):
        resource = patient_to_fhir(_patient())

        assert resource["resourceType"] == "Patient"
        assert resource["id"] == "d3d3e1f5-1111-4111-8111-111111111111"
        assert resource["active"] is True
        assert resource["gender"] == "female"
        assert resource["birthDate"] == "1985-07-14"

    def test_emits_mrn_and_cpf_identifiers(self):
        resource = patient_to_fhir(_patient())

        systems = {ident["system"]: ident["value"] for ident in resource["identifier"]}
        assert systems[SYSTEM_MRN] == "2026000001"
        assert systems[SYSTEM_CPF] == "123.456.789-09"

    def test_omits_cpf_identifier_when_absent(self):
        resource = patient_to_fhir(_patient(cpf=""))
        systems = {ident["system"] for ident in resource["identifier"]}
        assert SYSTEM_CPF not in systems
        assert SYSTEM_MRN in systems

    def test_splits_official_name_and_emits_social_as_usual(self):
        resource = patient_to_fhir(_patient(social_name="Aninha"))

        names_by_use = {n["use"]: n for n in resource["name"]}
        official = names_by_use["official"]
        assert official["family"] == "Souza"
        assert official["given"] == ["Ana", "Maria"]
        assert official["text"] == "Ana Maria Souza"
        assert names_by_use["usual"]["text"] == "Aninha"

    def test_does_not_emit_usual_name_when_social_equals_full_name(self):
        resource = patient_to_fhir(_patient(social_name="Ana Maria Souza"))
        uses = {n["use"] for n in resource["name"]}
        assert uses == {"official"}

    def test_telecom_phone_mobile_email(self):
        resource = patient_to_fhir(_patient())
        telecom = resource["telecom"]
        phone = next(t for t in telecom if t.get("use") == "home")
        mobile = next(t for t in telecom if t.get("use") == "mobile")
        email = next(t for t in telecom if t.get("system") == "email")
        assert phone["value"] == "11 3000-1000"
        assert mobile["value"] == "11 99999-1234"
        assert email["value"] == "ana@example.com"

    def test_address_emits_line_city_state_postal(self):
        resource = patient_to_fhir(_patient())
        addr = resource["address"][0]
        assert addr["city"] == "São Paulo"
        assert addr["state"] == "SP"
        assert addr["postalCode"] == "01000-000"
        assert addr["country"] == "BR"
        assert any("Rua das Acácias" in line for line in addr["line"])

    def test_unknown_gender_maps_to_unknown(self):
        resource = patient_to_fhir(_patient(gender="N"))
        assert resource["gender"] == "unknown"

    def test_inactive_patient_active_flag_false(self):
        resource = patient_to_fhir(_patient(is_active=False))
        assert resource["active"] is False

    def test_empty_address_does_not_emit_address_key(self):
        resource = patient_to_fhir(_patient(address={}))
        assert "address" not in resource
