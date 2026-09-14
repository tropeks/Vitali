"""
Tests for apps.ai.phi_scrubber (Onda 3 / 3.1).

Covers what the scrubber DOES catch (the module docstring is explicit about
what it does not — these tests only assert the documented guarantees).
"""

import datetime
import re
from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.ai.phi_scrubber import scrub_for_llm, scrub_generic, scrub_patient_identifiers


def _patient(**overrides):
    defaults = {
        "full_name": "Maria das Dores Ferreira",
        "social_name": "",
        "mother_name": "Joana Ferreira",
        "father_name": "",
        "cpf": "123.456.789-00",
        "cns": "123456789012345",
        "identity_document": "12.345.678-9",
        "phone": "(11) 98888-7777",
        "email": "maria.ferreira@example.com",
        "birth_date": datetime.date(1990, 4, 12),
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class ScrubPatientIdentifiersTest(SimpleTestCase):
    def test_removes_known_full_name(self):
        text = "Paciente Maria das Dores Ferreira comparece à consulta."
        out = scrub_patient_identifiers(text, _patient())
        self.assertNotIn("Maria das Dores Ferreira", out)
        self.assertIn("[NOME_", out)

    def test_removes_known_cpf_regardless_of_punctuation(self):
        text = "CPF: 123.456.789-00"
        out = scrub_patient_identifiers(text, _patient())
        self.assertNotIn("123.456.789-00", out)
        self.assertIn("[CPF_", out)

    def test_removes_known_birth_date_multiple_formats(self):
        patient = _patient()
        for text in ("Nasceu em 12/04/1990.", "DN 12-04-1990", "12/04/90"):
            out = scrub_patient_identifiers(text, patient)
            self.assertNotIn("1990", out, msg=f"leaked in: {text!r}")

    def test_same_value_produces_same_stable_token(self):
        patient = _patient()
        out1 = scrub_patient_identifiers("Falou com Maria das Dores Ferreira.", patient)
        out2 = scrub_patient_identifiers(
            "Retornou, Maria das Dores Ferreira relata melhora.", patient
        )
        token1 = re.search(r"\[NOME_[0-9A-F]+\]", out1).group(0)
        token2 = re.search(r"\[NOME_[0-9A-F]+\]", out2).group(0)
        self.assertEqual(token1, token2)

    def test_scrubs_informal_surname_mention(self):
        """Individual name parts (>= 4 chars) are also scrubbed — see docstring trade-off."""
        out = scrub_patient_identifiers("Dona Ferreira retornou hoje.", _patient())
        self.assertNotIn("Ferreira", out)

    def test_none_patient_is_noop(self):
        text = "Texto qualquer sem paciente associado."
        self.assertEqual(scrub_patient_identifiers(text, None), text)

    def test_blank_fields_are_skipped(self):
        patient = _patient(social_name="", father_name="")
        text = "Nada a esconder aqui."
        self.assertEqual(scrub_patient_identifiers(text, patient), text)

    def test_does_not_catch_unregistered_third_party_name(self):
        """Documented limitation: names NOT on file for this patient pass through."""
        out = scrub_patient_identifiers("Encaminhei para o Dr. Ricardo Albuquerque.", _patient())
        self.assertIn("Ricardo Albuquerque", out)


class ScrubGenericTest(SimpleTestCase):
    def test_scrubs_cpf_without_patient_context(self):
        out = scrub_generic("O cônjuge, CPF 987.654.321-00, também é paciente daqui.")
        self.assertNotIn("987.654.321-00", out)
        self.assertIn("[CPF_", out)

    def test_scrubs_email(self):
        out = scrub_generic("Contato: joao.silva@example.com")
        self.assertNotIn("joao.silva@example.com", out)
        self.assertIn("[EMAIL_", out)

    def test_scrubs_phone(self):
        out = scrub_generic("Ligar no (21) 99999-1234 se piorar.")
        self.assertNotIn("99999-1234", out)
        self.assertIn("[TEL_", out)

    def test_leaves_clinical_text_untouched(self):
        text = "Paciente com cefaleia tensional, PA 120/80, afebril."
        # PA 120/80 must not be mistaken for a phone/date pattern.
        out = scrub_generic(text)
        self.assertIn("cefaleia tensional", out)
        self.assertIn("PA 120/80", out)

    def test_does_not_catch_free_form_name(self):
        """Documented limitation: scrub_generic has no notion of person names."""
        out = scrub_generic("Paciente João da Silva Neto compareceu à consulta.")
        self.assertIn("João da Silva Neto", out)


class ScrubForLLMTest(SimpleTestCase):
    def test_combines_directed_and_generic_layers(self):
        patient = _patient()
        text = (
            "Paciente Maria das Dores Ferreira, CPF 123.456.789-00. "
            "Cônjuge com CPF 111.222.333-44 também compareceu."
        )
        out = scrub_for_llm(text, patient=patient)
        self.assertNotIn("Maria das Dores Ferreira", out)
        self.assertNotIn("123.456.789-00", out)
        # The spouse's CPF is not on the Patient record — only scrub_generic catches it.
        self.assertNotIn("111.222.333-44", out)

    def test_no_patient_still_runs_generic_sweep(self):
        out = scrub_for_llm("CPF 555.666.777-88 mencionado no relato.", patient=None)
        self.assertNotIn("555.666.777-88", out)
