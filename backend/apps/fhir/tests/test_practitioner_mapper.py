"""Unit tests for the FHIR R4 Practitioner mapper (pure transform, no DB)."""

from __future__ import annotations

from types import SimpleNamespace

from apps.fhir.services.practitioner_mapper import professional_to_fhir


def _user(full_name="Dra Ana Silva", email="ana@example.com"):
    return SimpleNamespace(full_name=full_name, email=email)


def _professional(**overrides):
    base = {
        "id": "prac-uuid",
        "user": _user(),
        "council_type": "CRM",
        "council_number": "123456",
        "council_state": "SP",
        "specialty": "Clínica Médica",
        "cbo_code": "225125",
        "is_active": True,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class TestPractitionerMapper:
    def test_maps_resource_type_and_id(self):
        resource = professional_to_fhir(_professional())
        assert resource["resourceType"] == "Practitioner"
        assert resource["id"] == "prac-uuid"
        assert resource["active"] is True

    def test_council_emitted_as_identifier_with_state_assigner(self):
        resource = professional_to_fhir(_professional())
        ident = resource["identifier"][0]
        assert ident["system"] == "urn:vitali:council/crm"
        assert ident["value"] == "123456"
        assert ident["assigner"]["display"] == "SP"
        assert ident["type"]["coding"][0]["code"] == "MD"

    def test_non_crm_council_uses_LN_code(self):
        resource = professional_to_fhir(_professional(council_type="CRO"))
        assert resource["identifier"][0]["system"] == "urn:vitali:council/cro"
        assert resource["identifier"][0]["type"]["coding"][0]["code"] == "LN"

    def test_name_split_from_user_full_name(self):
        resource = professional_to_fhir(_professional())
        name = resource["name"][0]
        assert name["text"] == "Dra Ana Silva"
        assert name["family"] == "Silva"
        assert name["given"] == ["Dra", "Ana"]

    def test_telecom_email_from_user(self):
        resource = professional_to_fhir(_professional())
        telecom = resource["telecom"][0]
        assert telecom["system"] == "email"
        assert telecom["value"] == "ana@example.com"

    def test_emits_two_qualifications_when_cbo_present(self):
        resource = professional_to_fhir(_professional())
        codes = [q["code"]["coding"][0]["code"] for q in resource["qualification"]]
        assert "CRM" in codes
        assert "225125" in codes

    def test_specialty_without_cbo_emits_free_text_qualification(self):
        resource = professional_to_fhir(_professional(cbo_code=""))
        # Council qualification + specialty free-text
        texts = [q["code"].get("text") for q in resource["qualification"]]
        assert any(text == "Clínica Médica" for text in texts)

    def test_inactive_professional_active_flag_false(self):
        resource = professional_to_fhir(_professional(is_active=False))
        assert resource["active"] is False

    def test_missing_council_number_drops_identifier(self):
        resource = professional_to_fhir(_professional(council_number=""))
        assert "identifier" not in resource

    def test_missing_user_omits_name_and_telecom(self):
        resource = professional_to_fhir(_professional(user=None))
        assert "name" not in resource
        assert "telecom" not in resource
