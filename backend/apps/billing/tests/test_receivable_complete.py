"""
Sprint M1-S4 · S4-T2 — Recebível completo (origin-agnostic AccountsReceivable).

A receivable can originate from a TISS guia OR a private bill OR a package OR a
PIX charge (the guia link is now nullable + an ``origin`` discriminator). Partial
settlement is tracked (paid_amount vs amount → open/partial/received) and the
cost center is a real FK to organization.CostCenter.

The existing settlement/reconciliation maker-checker flow MUST stay green — see
test_settlement_reconciliation.py (run alongside this file).

Run: python manage.py test apps.billing.tests.test_receivable_complete
"""

import datetime
from decimal import Decimal

from apps.billing.models import AccountsReceivable, InsuranceProvider, PIXCharge
from apps.billing.revenue_models import Package
from apps.core.models import User
from apps.emr.models import Appointment, Patient, Professional
from apps.organization.models import CostCenter, LegalEntity
from apps.test_utils import TenantTestCase


class RecebivelCompletoTestCase(TenantTestCase):
    def setUp(self):
        self.provider = InsuranceProvider.objects.create(name="Op Rec", ans_code="880001")

    # ── origin-agnostic: private / PIX / package receivables without a guia ──────

    def test_private_receivable_without_guide(self):
        rec = AccountsReceivable.objects.create(
            amount=Decimal("200.00"), origin="private", status="billed"
        )
        self.assertIsNone(rec.guide_id)
        self.assertEqual(rec.origin, "private")
        # __str__ must not blow up when guide is None
        self.assertIn("200.00", str(rec))

    def test_package_origin_receivable(self):
        pkg = Package.objects.create(name="Pac", provider=self.provider)
        rec = AccountsReceivable.objects.create(
            amount=Decimal("999.00"), origin="package", package=pkg
        )
        self.assertIsNone(rec.guide_id)
        self.assertEqual(rec.package_id, pkg.id)

    def test_pix_origin_receivable(self):
        prof_user = User.objects.create_user(
            email="p@x.com", full_name="P", password="Str0ng!Pass#2024"
        )
        professional = Professional.objects.create(
            user=prof_user, council_type="CRM", council_number="1", council_state="SP"
        )
        patient = Patient.objects.create(
            full_name="Ana", cpf="111.111.111-11", birth_date=datetime.date(1990, 1, 1), gender="F"
        )
        appt = Appointment.objects.create(
            patient=patient,
            professional=professional,
            start_time=datetime.datetime(2026, 4, 1, 10, 0),
            end_time=datetime.datetime(2026, 4, 1, 10, 30),
        )
        charge = PIXCharge.objects.create(
            appointment=appt,
            asaas_charge_id="ch_rec_1",
            amount=Decimal("150.00"),
            expires_at=datetime.datetime(2026, 4, 1, 11, 0),
        )
        rec = AccountsReceivable.objects.create(
            amount=Decimal("150.00"), origin="pix", pix_charge=charge
        )
        self.assertEqual(rec.pix_charge_id, charge.id)
        self.assertIsNone(rec.guide_id)

    # ── partial settlement math ──────────────────────────────────────────────────

    def test_partial_settlement_math(self):
        rec = AccountsReceivable.objects.create(
            amount=Decimal("100.00"), origin="private", status="billed"
        )
        self.assertEqual(rec.remaining_amount, Decimal("100.00"))

        rec.register_payment(Decimal("40.00"))
        rec.refresh_from_db()
        self.assertEqual(rec.paid_amount, Decimal("40.00"))
        self.assertEqual(rec.status, "partial")
        self.assertEqual(rec.remaining_amount, Decimal("60.00"))
        self.assertIsNone(rec.received_at)

        rec.register_payment(Decimal("60.00"))
        rec.refresh_from_db()
        self.assertEqual(rec.paid_amount, Decimal("100.00"))
        self.assertEqual(rec.status, "received")
        self.assertEqual(rec.remaining_amount, Decimal("0.00"))
        self.assertIsNotNone(rec.received_at)

    def test_overpayment_clamps_to_received(self):
        rec = AccountsReceivable.objects.create(amount=Decimal("100.00"), origin="private")
        rec.register_payment(Decimal("120.00"))
        rec.refresh_from_db()
        self.assertEqual(rec.status, "received")
        self.assertEqual(rec.remaining_amount, Decimal("0.00"))

    # ── cost_center FK ───────────────────────────────────────────────────────────

    def test_cost_center_fk(self):
        le = LegalEntity.objects.create(code="LE-REC", name="Clínica")
        cc = CostCenter.objects.create(code="CC-REC", name="Ambulatório", legal_entity=le)
        rec = AccountsReceivable.objects.create(
            amount=Decimal("300.00"), origin="private", cost_center=cc
        )
        rec.refresh_from_db()
        self.assertEqual(rec.cost_center_id, cc.id)
