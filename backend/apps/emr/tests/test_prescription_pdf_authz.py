"""
Authz tests for PrescriptionPDFView (CSO finding — IDOR of PHI).

The PDF endpoint returns prescription (PHI) bytes. It must be gated on
``emr.read``: a role without it (e.g. front-desk with only patients.read) gets
403; a clinical role with ``emr.read`` gets the PDF for a SIGNED prescription.
"""

import datetime
from unittest.mock import patch

from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.test_utils import TenantTestCase


class TestPrescriptionPDFAuthz(TenantTestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model

        from apps.core.models import Role
        from apps.core.permissions import DEFAULT_ROLES
        from apps.emr.models import Encounter, Patient, Prescription, Professional

        User = get_user_model()

        # Role WITHOUT emr.read (front-desk-like: só patients.read).
        self.no_emr_role = Role.objects.create(
            name="recepcao_pdf_authz", permissions=["patients.read"]
        )
        # Clinical role WITH emr.read/write/sign.
        self.clinical_role = Role.objects.create(
            name="medico_pdf_authz", permissions=DEFAULT_ROLES["medico"]
        )

        self.no_emr_user = User.objects.create_user(
            email="recep_pdf_authz@clinic.test",
            password="TestPass123!",
            full_name="Recep PDF",
            role=self.no_emr_role,
        )
        self.clinical_user = User.objects.create_user(
            email="medico_pdf_authz@clinic.test",
            password="TestPass123!",
            full_name="Dr PDF Authz",
            role=self.clinical_role,
        )

        self.patient = Patient.objects.create(
            full_name="Authz Patient",
            cpf="123.456.789-00",
            birth_date=datetime.date(1980, 6, 15),
            gender="M",
        )
        self.professional = Professional.objects.create(
            user=self.clinical_user,
            council_type="CRM",
            council_number="123123",
            council_state="SP",
        )
        self.encounter = Encounter.objects.create(
            patient=self.patient,
            professional=self.professional,
            encounter_date=timezone.now(),
        )
        self.prescription_signed = Prescription.objects.create(
            encounter=self.encounter,
            patient=self.patient,
            prescriber=self.professional,
        )
        self.prescription_signed.sign(self.clinical_user)

    def _client_for(self, user):
        client = APIClient()
        client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        refresh = RefreshToken.for_user(user)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {str(refresh.access_token)}")
        return client

    def test_pdf_denied_for_role_without_emr_read(self):
        """A role without emr.read (patients.read only) gets 403 — no PHI leak."""
        client = self._client_for(self.no_emr_user)
        response = client.get(f"/api/v1/prescriptions/{self.prescription_signed.id}/pdf/")
        self.assertEqual(response.status_code, 403)

    @patch("apps.emr.views_pdf.PrescriptionPDFGenerator")
    def test_pdf_allowed_for_emr_read_on_signed(self, mock_generator_cls):
        """A clinical role with emr.read gets 200 (PDF) for a signed prescription."""
        mock_generator_cls.return_value.generate.return_value = b"%PDF-1.4 fake"

        client = self._client_for(self.clinical_user)
        response = client.get(f"/api/v1/prescriptions/{self.prescription_signed.id}/pdf/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF-"))
