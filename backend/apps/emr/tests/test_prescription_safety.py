"""
Tests for S-063 AI Prescription Safety Checker.

Tests:
  - Safety check fires via on_commit (not directly in post_save)
  - Cache prevents duplicate LLM calls
  - Allergy crosscheck fires for patient with known allergy
  - Safe prescription creates no alert
  - Acknowledge alert requires reason for contraindication
"""

import json
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.cache import cache

from apps.test_utils import TenantTestCase

User = get_user_model()


class TestPrescriptionSafety(TenantTestCase):
    def setUp(self):
        import datetime

        from apps.core.models import Role
        from apps.emr.models import (
            Encounter,
            Patient,
            Prescription,
            Professional,
        )
        from apps.pharmacy.models import Drug

        # Clinical role with emr.write (the floor for dose-override acknowledge)
        self.clinical_role = Role.objects.create(
            name="medico",
            permissions=["emr.read", "emr.write", "emr.sign"],
        )
        self.user = User.objects.create_user(
            email="safety_test@clinic.test",
            password="TestPass123!",
            full_name="Safety Doctor",
            role=self.clinical_role,
        )

        # Create drug (minimal)
        self.drug = Drug.objects.create(
            name="Amoxicilina 500mg",
            generic_name="amoxicilina",
            controlled_class="none",
        )
        self.drug2 = Drug.objects.create(
            name="Warfarina 5mg",
            generic_name="varfarina",
            controlled_class="none",
        )

        self.patient = Patient.objects.create(
            full_name="João Safety",
            cpf="111.222.333-44",
            birth_date=datetime.date(1985, 3, 10),
            gender="M",
        )
        self.professional = Professional.objects.create(
            user=self.user,
            council_type="CRM",
            council_number="123456",
            council_state="SP",
        )
        from django.utils import timezone

        self.encounter = Encounter.objects.create(
            patient=self.patient,
            professional=self.professional,
            encounter_date=timezone.now(),
        )
        self.prescription = Prescription.objects.create(
            encounter=self.encounter,
            patient=self.patient,
            prescriber=self.professional,
        )
        cache.clear()

    def _make_client(self, user):
        from rest_framework.test import APIClient

        client = APIClient()
        client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        return client

    def _create_item(self, drug=None):
        from apps.emr.models import PrescriptionItem

        return PrescriptionItem(
            prescription=self.prescription,
            drug=drug or self.drug,
            generic_name=(drug or self.drug).generic_name,
            quantity=1,
            unit_of_measure="cx",
            dosage_instructions="1 comp 8/8h por 7 dias",
        )

    def test_safety_check_fires_via_on_commit_not_post_save(self):
        """
        Safety task should be dispatched via transaction.on_commit,
        not directly inside the post_save handler.
        """
        from apps.emr.models import PrescriptionItem

        with patch("apps.emr.tasks.check_prescription_safety.delay") as mock_delay:
            with self.captureOnCommitCallbacks(execute=True):
                item = PrescriptionItem.objects.create(
                    prescription=self.prescription,
                    drug=self.drug,
                    generic_name="amoxicilina",
                    quantity=1,
                    unit_of_measure="cx",
                    dosage_instructions="1 comp 8/8h",
                )
            # .delay() should have been called after commit
            mock_delay.assert_called_once_with(str(item.id))

    def test_cache_prevents_duplicate_llm_calls(self):
        """Second check() call with same inputs should not call LLM."""
        from apps.emr.services.prescription_safety import PrescriptionSafetyChecker

        item = self._create_item()
        item.save()

        mock_llm_response = json.dumps({"alerts": []})

        with (
            patch("apps.emr.services.prescription_safety.get_tenant_ai_config") as mock_cfg,
            patch("apps.emr.services.prescription_safety._check_dpa_signed", return_value=True),
            patch("apps.emr.services.prescription_safety.is_rate_limited", return_value=False),
            patch("apps.emr.services.prescription_safety.is_open", return_value=False),
            patch(
                "apps.ai.gateway.ClaudeGateway.complete", return_value=(mock_llm_response, 100, 50)
            ),
        ):
            mock_cfg.return_value = MagicMock(
                ai_prescription_safety=True,
                rate_limit_per_hour=500,
            )

            checker = PrescriptionSafetyChecker()

            result1 = checker.check(item, self.prescription)
            self.assertFalse(result1.degraded)
            self.assertFalse(result1.cached)

            result2 = checker.check(item, self.prescription)
            self.assertTrue(result2.cached)

    def test_allergy_crosscheck_fires_for_patient_with_known_allergy(self):
        """
        If patient has active allergy to penicillin, and we prescribe amoxicilina,
        the LLM should be called and allergy alert should be returned.
        """
        from apps.emr.models import Allergy
        from apps.emr.services.prescription_safety import PrescriptionSafetyChecker

        Allergy.objects.create(
            patient=self.patient,
            substance="Penicilina",
            severity="severe",
            status="active",
        )

        item = self._create_item()
        item.save()

        mock_response = json.dumps(
            {
                "alerts": [
                    {
                        "type": "allergy",
                        "severity": "contraindication",
                        "message": "Amoxicilina é uma penicilina — contraindicado para alergia a Penicilina.",
                        "recommendation": "Considerar macrolídeo como alternativa.",
                    }
                ]
            }
        )

        with (
            patch("apps.emr.services.prescription_safety.get_tenant_ai_config") as mock_cfg,
            patch("apps.emr.services.prescription_safety._check_dpa_signed", return_value=True),
            patch("apps.emr.services.prescription_safety.is_rate_limited", return_value=False),
            patch("apps.emr.services.prescription_safety.is_open", return_value=False),
            patch("apps.ai.gateway.ClaudeGateway.complete", return_value=(mock_response, 200, 80)),
        ):
            mock_cfg.return_value = MagicMock(
                ai_prescription_safety=True,
                rate_limit_per_hour=500,
            )
            cache.clear()

            checker = PrescriptionSafetyChecker()
            result = checker.check(item, self.prescription)

        self.assertFalse(result.is_safe)
        self.assertEqual(len(result.alerts), 1)
        self.assertEqual(result.alerts[0].alert_type, "allergy")
        self.assertEqual(result.alerts[0].severity, "contraindication")

    def test_safe_prescription_creates_no_alert(self):
        """When LLM returns empty alerts, SafetyResult.is_safe is True."""
        from apps.emr.services.prescription_safety import PrescriptionSafetyChecker

        item = self._create_item()
        item.save()

        mock_response = json.dumps({"alerts": []})

        with (
            patch("apps.emr.services.prescription_safety.get_tenant_ai_config") as mock_cfg,
            patch("apps.emr.services.prescription_safety._check_dpa_signed", return_value=True),
            patch("apps.emr.services.prescription_safety.is_rate_limited", return_value=False),
            patch("apps.emr.services.prescription_safety.is_open", return_value=False),
            patch("apps.ai.gateway.ClaudeGateway.complete", return_value=(mock_response, 100, 30)),
        ):
            mock_cfg.return_value = MagicMock(
                ai_prescription_safety=True,
                rate_limit_per_hour=500,
            )
            cache.clear()

            checker = PrescriptionSafetyChecker()
            result = checker.check(item, self.prescription)

        self.assertTrue(result.is_safe)
        self.assertEqual(result.alerts, [])
        self.assertFalse(result.degraded)

    def test_acknowledge_alert_requires_reason_for_contraindication(self):
        """AcknowledgeSafetyAlertView requires reason >= 10 chars for contraindications."""
        from rest_framework_simplejwt.tokens import RefreshToken

        from apps.emr.models import AISafetyAlert, PrescriptionItem

        client = self._make_client(self.user)
        refresh = RefreshToken.for_user(self.user)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {str(refresh.access_token)}")

        item = PrescriptionItem.objects.create(
            prescription=self.prescription,
            drug=self.drug,
            generic_name="amoxicilina",
            quantity=1,
            unit_of_measure="cx",
        )
        alert = AISafetyAlert.objects.create(
            prescription_item=item,
            alert_type="allergy",
            severity="contraindication",
            message="Alergia grave a penicilinas",
        )

        url = f"/api/v1/safety-alerts/{alert.id}/acknowledge/"

        # Short reason → 400
        response = client.post(url, {"reason": "curto"})
        self.assertEqual(response.status_code, 400)

        # Valid reason → 200
        response = client.post(url, {"reason": "Paciente informou tolerância prévia documentada"})
        self.assertEqual(response.status_code, 200)

        alert.refresh_from_db()
        self.assertEqual(alert.status, "acknowledged")

    def test_acknowledge_alert_forbidden_without_emr_write(self):
        """HIGH-1: a non-clinical role (recepcao) lacking emr.write gets 403."""
        from rest_framework_simplejwt.tokens import RefreshToken

        from apps.core.models import Role
        from apps.emr.models import AISafetyAlert, PrescriptionItem

        recepcao_role = Role.objects.create(
            name="recepcao",
            permissions=[
                "patients.limited_read",
                "schedule.read",
                "schedule.write",
                "billing.read",
            ],
        )
        recepcao_user = User.objects.create_user(
            email="recepcao_safety@clinic.test",
            password="TestPass123!",
            full_name="Recepcao User",
            role=recepcao_role,
        )

        client = self._make_client(recepcao_user)
        refresh = RefreshToken.for_user(recepcao_user)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {str(refresh.access_token)}")

        item = PrescriptionItem.objects.create(
            prescription=self.prescription,
            drug=self.drug,
            generic_name="amoxicilina",
            quantity=1,
            unit_of_measure="cx",
        )
        alert = AISafetyAlert.objects.create(
            prescription_item=item,
            alert_type="allergy",
            severity="caution",
            message="Cautela",
        )

        url = f"/api/v1/safety-alerts/{alert.id}/acknowledge/"
        response = client.post(url, {"reason": "qualquer motivo aqui"})
        self.assertEqual(response.status_code, 403)

        alert.refresh_from_db()
        self.assertEqual(alert.status, "flagged")
        self.assertIsNone(alert.acknowledged_by)

    def test_acknowledge_already_acknowledged_returns_409(self):
        """LOW-1: re-acking a non-flagged alert returns 409 and preserves origin."""
        from rest_framework_simplejwt.tokens import RefreshToken

        from apps.emr.models import AISafetyAlert, PrescriptionItem

        client = self._make_client(self.user)
        refresh = RefreshToken.for_user(self.user)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {str(refresh.access_token)}")

        item = PrescriptionItem.objects.create(
            prescription=self.prescription,
            drug=self.drug,
            generic_name="amoxicilina",
            quantity=1,
            unit_of_measure="cx",
        )
        alert = AISafetyAlert.objects.create(
            prescription_item=item,
            alert_type="allergy",
            severity="caution",
            message="Cautela",
        )

        # First ack succeeds
        url = f"/api/v1/safety-alerts/{alert.id}/acknowledge/"
        response = client.post(url, {"reason": "primeiro motivo registrado"})
        self.assertEqual(response.status_code, 200)
        alert.refresh_from_db()
        original_by = alert.acknowledged_by_id
        original_at = alert.acknowledged_at
        original_reason = alert.override_reason

        # Second ack rejected with 409, origin unchanged
        response = client.post(url, {"reason": "segundo motivo diferente"})
        self.assertEqual(response.status_code, 409)
        alert.refresh_from_db()
        self.assertEqual(alert.acknowledged_by_id, original_by)
        self.assertEqual(alert.acknowledged_at, original_at)
        self.assertEqual(alert.override_reason, original_reason)

    def test_safety_check_get_forbidden_without_emr_read(self):
        """HIGH-1: safety-check GET requires emr.read; recepcao (no emr.read) → 403."""
        from rest_framework_simplejwt.tokens import RefreshToken

        from apps.core.models import Role
        from apps.emr.models import PrescriptionItem

        recepcao_role = Role.objects.create(
            name="recepcao2",
            permissions=["patients.limited_read", "schedule.read"],
        )
        recepcao_user = User.objects.create_user(
            email="recepcao_check@clinic.test",
            password="TestPass123!",
            full_name="Recepcao Check",
            role=recepcao_role,
        )

        item = PrescriptionItem.objects.create(
            prescription=self.prescription,
            drug=self.drug,
            generic_name="amoxicilina",
            quantity=1,
            unit_of_measure="cx",
        )

        client = self._make_client(recepcao_user)
        refresh = RefreshToken.for_user(recepcao_user)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {str(refresh.access_token)}")

        url = f"/api/v1/prescription-items/{item.id}/safety-check/"
        response = client.get(url)
        self.assertEqual(response.status_code, 403)

        # A user WITH emr.read now dispatches the handler successfully (the URL/
        # signature arity bug — view required prescription_id the route never
        # supplied — is fixed: the view is keyed by item_id alone).
        ok_client = self._make_client(self.user)
        ok_refresh = RefreshToken.for_user(self.user)
        ok_client.credentials(HTTP_AUTHORIZATION=f"Bearer {str(ok_refresh.access_token)}")
        get_resp = ok_client.get(url)
        self.assertEqual(get_resp.status_code, 200)
        self.assertIn("status", get_resp.json())
        # POST re-queues the safety check → 202.
        post_resp = ok_client.post(url)
        self.assertEqual(post_resp.status_code, 202)
        # Unknown item id → 404 (keyed by item_id alone).
        missing = ok_client.get(
            "/api/v1/prescription-items/00000000-0000-0000-0000-000000000000/safety-check/"
        )
        self.assertEqual(missing.status_code, 404)

    def test_feature_flag_off_returns_no_degraded(self):
        """When ai_prescription_safety is OFF, returns is_safe=True, degraded=False."""
        from apps.emr.services.prescription_safety import PrescriptionSafetyChecker

        item = self._create_item()

        with patch("apps.emr.services.prescription_safety.get_tenant_ai_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(ai_prescription_safety=False)
            checker = PrescriptionSafetyChecker()
            result = checker.check(item, self.prescription)

        self.assertTrue(result.is_safe)
        self.assertFalse(result.degraded)
