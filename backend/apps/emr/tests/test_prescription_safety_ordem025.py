"""
Ordem 025 — PrescriptionSafetyChecker reads the FeatureFlag the DPA writes.

It used to read ``TenantAIConfig.ai_prescription_safety``, a field that does
not exist, so it never ran. The DPA is signed through the real
``DPASigningService`` (which enables the ``ai_prescription_safety``
FeatureFlag); only the network call to Anthropic is replaced. Lives in
apps.emr because it needs apps.pharmacy (import contract); the rest of the
order's tests are in apps/ai/tests/test_ia_atual_para_de_mentir.py.
"""

import json
from unittest.mock import patch

from django.core.cache import cache
from django.test import override_settings

from apps.test_utils import TenantTestCase


class _SignedTenantMixin:
    def _sign_dpa_for_real(self):
        from django.contrib.auth import get_user_model

        from apps.core.services.dpa import DPASigningService

        signer = get_user_model().objects.create_user(
            email="signatario.025@clinica.test", password="Signat!025#x", full_name="Signatário"
        )
        DPASigningService(requesting_user=signer).sign(tenant=self.__class__.tenant)


class PrescriptionSafetyFlagTest(_SignedTenantMixin, TenantTestCase):
    def setUp(self):
        import datetime

        from django.contrib.auth import get_user_model
        from django.utils import timezone

        from apps.emr.models import (
            Encounter,
            Patient,
            Prescription,
            PrescriptionItem,
            Professional,
        )
        from apps.pharmacy.models import Drug

        cache.clear()
        user = get_user_model().objects.create_user(
            email="prescritor.025@clinica.test", password="Prescr!025#x", full_name="Prescritor"
        )
        professional = Professional.objects.create(
            user=user, council_type="CRM", council_number="250250", council_state="SP"
        )
        patient = Patient.objects.create(
            full_name="Paciente 025",
            cpf="111.444.777-35",
            birth_date=datetime.date(1970, 1, 1),
            gender="M",
        )
        encounter = Encounter.objects.create(
            patient=patient, professional=professional, encounter_date=timezone.now()
        )
        self.prescription = Prescription.objects.create(
            encounter=encounter, patient=patient, prescriber=professional
        )
        drug = Drug.objects.create(
            name="Amoxicilina 500mg", generic_name="amoxicilina", controlled_class="none"
        )
        self.item = PrescriptionItem(
            prescription=self.prescription,
            drug=drug,
            generic_name="amoxicilina",
            quantity=1,
            unit_of_measure="cx",
            dosage_instructions="1 comp 8/8h",
        )
        self.item.save()

    def _check(self):
        from apps.emr.services.prescription_safety import PrescriptionSafetyChecker

        with patch(
            "apps.ai.gateway.ClaudeGateway.complete",
            return_value=(json.dumps({"alerts": []}), 40, 10),
        ) as complete:
            result = PrescriptionSafetyChecker().check(self.item, self.prescription)
        return result, complete

    @override_settings(FEATURE_AI_PRESCRIPTION_SAFETY=True)
    def test_flag_written_by_the_dpa_service_is_the_one_read(self):
        self._sign_dpa_for_real()
        result, complete = self._check()
        complete.assert_called_once()
        self.assertFalse(result.degraded)

    @override_settings(FEATURE_AI_PRESCRIPTION_SAFETY=True)
    def test_without_dpa_the_llm_is_never_called(self):
        from apps.core.models import FeatureFlag

        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key="ai_prescription_safety",
            defaults={"is_enabled": True},
        )
        result, complete = self._check()
        complete.assert_not_called()
        self.assertTrue(result.is_safe)

    def test_signing_the_dpa_alone_does_not_turn_it_on(self):
        self._sign_dpa_for_real()
        _, complete = self._check()
        complete.assert_not_called()
