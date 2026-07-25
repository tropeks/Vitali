"""
Sprint M1-S4 · S4-T3 — Honorários guide.

Adds "honorarios" to TISSGuide.guide_type choices + minimal honorarios-specific
fields (executor professional, procedure valuation via CBHPM porte).

Run: python manage.py test apps.billing.tests.test_honorarios
"""

import datetime
from decimal import Decimal

from apps.billing.models import InsuranceProvider, TISSGuide
from apps.core.models import CBHPMItem, User
from apps.emr.models import Encounter, Patient, Professional
from apps.test_utils import TenantTestCase


class HonorariosGuideTestCase(TenantTestCase):
    def setUp(self):
        self.provider = InsuranceProvider.objects.create(name="Op Hon", ans_code="990001")
        prof_user = User.objects.create_user(
            email="exec@x.com", full_name="Dr Exec", password="Str0ng!Pass#2024"
        )
        self.executor = Professional.objects.create(
            user=prof_user, council_type="CRM", council_number="123", council_state="SP"
        )
        self.patient = Patient.objects.create(
            full_name="Joao", cpf="222.222.222-22", birth_date=datetime.date(1980, 1, 1), gender="M"
        )
        self.encounter = Encounter.objects.create(patient=self.patient, professional=self.executor)
        # valor() == 15 × 3 == 45.00
        self.cbhpm = CBHPMItem.objects.create(
            code="40404040",
            display="Honorário porte",
            porte=Decimal("15.0000"),
            valor_ch=Decimal("3.000000"),
        )

    def test_honorarios_guide_creatable_and_priced(self):
        guide = TISSGuide.objects.create(
            guide_type="honorarios",
            encounter=self.encounter,
            patient=self.patient,
            provider=self.provider,
            insured_card_number="0001234567890099",
            competency="2026-04",
            executor=self.executor,
            honorario_cbhpm=self.cbhpm,
        )
        self.assertEqual(guide.guide_type, "honorarios")
        self.assertEqual(guide.executor_id, self.executor.id)

        guide.price_honorario()
        guide.refresh_from_db()
        self.assertEqual(guide.honorario_value, Decimal("45.0000"))
        self.assertEqual(guide.total_value, Decimal("45.00"))
