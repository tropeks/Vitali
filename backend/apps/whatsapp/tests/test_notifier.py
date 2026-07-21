"""
Tests for the concrete patient-WhatsApp notifier (apps.whatsapp.notifier).

This is the whatsapp-domain half of the invite-delivery seam (issue #117):
the opt_in consent gate and the Evolution gateway live here, so they are
exercised here rather than in apps.patient_portal (which drives the notifier
through the apps.core port and must not import apps.whatsapp — P1-01).
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

from apps.emr.models import Patient
from apps.test_utils import TenantTestCase
from apps.whatsapp.models import WhatsAppContact
from apps.whatsapp.notifier import PatientWhatsAppNotifierProvider

GATEWAY_PATH = "apps.whatsapp.gateway.get_gateway"


class PatientWhatsAppNotifierProviderTest(TenantTestCase):
    def setUp(self):
        self.provider = PatientWhatsAppNotifierProvider()
        self.patient = Patient.objects.create(
            full_name="Ana Maria Souza",
            cpf="12345678909",
            birth_date=date(1985, 7, 14),
            gender="F",
            whatsapp="5511988887777",
            email="ana@email.test",
        )

    def test_sends_to_opted_in_contact(self):
        WhatsAppContact.objects.create(phone="5511988887777", patient=self.patient, opt_in=True)
        with patch(GATEWAY_PATH) as mock_get_gateway:
            gateway = MagicMock()
            mock_get_gateway.return_value = gateway
            ok = self.provider.send_text_to_opted_in_patient(patient=self.patient, text="oi")

        self.assertTrue(ok)
        gateway.send_text.assert_called_once_with("5511988887777", "oi")

    def test_no_contact_returns_false(self):
        with patch(GATEWAY_PATH) as mock_get_gateway:
            gateway = MagicMock()
            mock_get_gateway.return_value = gateway
            ok = self.provider.send_text_to_opted_in_patient(patient=self.patient, text="oi")

        self.assertFalse(ok)
        gateway.send_text.assert_not_called()

    def test_not_opted_in_returns_false(self):
        WhatsAppContact.objects.create(phone="5511988887777", patient=self.patient, opt_in=False)
        with patch(GATEWAY_PATH) as mock_get_gateway:
            gateway = MagicMock()
            mock_get_gateway.return_value = gateway
            ok = self.provider.send_text_to_opted_in_patient(patient=self.patient, text="oi")

        self.assertFalse(ok)
        gateway.send_text.assert_not_called()

    def test_send_failure_is_fail_open_returns_false(self):
        WhatsAppContact.objects.create(phone="5511988887777", patient=self.patient, opt_in=True)
        with patch(GATEWAY_PATH) as mock_get_gateway:
            gateway = MagicMock()
            gateway.send_text.side_effect = RuntimeError("evolution down")
            mock_get_gateway.return_value = gateway
            ok = self.provider.send_text_to_opted_in_patient(patient=self.patient, text="oi")

        self.assertFalse(ok)
