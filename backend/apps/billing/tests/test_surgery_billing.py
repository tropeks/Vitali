"""
B1 — SurgicalCase → SP/SADT billing bridge.

generate_sadt_guide_for_surgical_case turns a FINALIZED SurgicalCase into one TISS
SP/SADT guide, pricing its procedures from the provider's active PriceTable, and
is idempotent (one guide per case). Non-billable cases raise ValidationError.
"""

import datetime
from decimal import Decimal

from rest_framework.exceptions import ValidationError

from apps.billing.models import (
    InsuranceProvider,
    PriceTable,
    PriceTableItem,
    TISSGuide,
)
from apps.billing.services.surgery_billing import generate_sadt_guide_for_surgical_case
from apps.core.models import Role, TUSSCode, User
from apps.emr.models import (
    Encounter,
    Patient,
    PatientInsurance,
    Professional,
    SurgicalCase,
    SurgicalProcedure,
)
from apps.test_utils import TenantTestCase


class SurgeryBillingTestCase(TenantTestCase):
    def setUp(self):
        role = Role.objects.create(name="surg_bill", permissions=["emr.read", "emr.write"])
        self.user = User.objects.create_user(
            email="surg-bill@example.com", password="pw", role=role
        )
        self.surgeon = Professional.objects.create(
            user=self.user, council_type="CRM", council_number="S-1", council_state="SP"
        )
        self.patient = Patient.objects.create(
            full_name="Surg Paciente", birth_date="1980-01-01", gender="M", cpf="54444444444"
        )
        self.encounter = Encounter.objects.create(patient=self.patient, professional=self.surgeon)
        self.provider = InsuranceProvider.objects.create(name="Unimed Test", ans_code="333333")
        PatientInsurance.objects.create(
            patient=self.patient,
            provider_ans_code="333333",
            provider_name="Unimed Test",
            card_number="9990001112223",
            is_active=True,
        )
        # TUSS-coded surgical procedures.
        self.tuss_a = TUSSCode.objects.create(
            code="30731011", description="Colecistectomia", group="procedimento", version="2024-01"
        )
        self.tuss_b = TUSSCode.objects.create(
            code="31003010", description="Herniorrafia", group="procedimento", version="2024-01"
        )
        # Active negotiated price table.
        self.price_table = PriceTable.objects.create(
            provider=self.provider,
            name="Unimed 2026",
            valid_from=datetime.date(2026, 1, 1),
            is_active=True,
        )
        PriceTableItem.objects.create(
            table=self.price_table, tuss_code=self.tuss_a, negotiated_value=Decimal("1200.00")
        )
        PriceTableItem.objects.create(
            table=self.price_table, tuss_code=self.tuss_b, negotiated_value=Decimal("800.00")
        )

    def _make_case(self, *, status=SurgicalCase.Status.FINALIZADA, encounter=True, procedures=True):
        case = SurgicalCase.objects.create(
            patient=self.patient,
            encounter=self.encounter if encounter else None,
            surgeon=self.surgeon,
            status=status,
        )
        if procedures:
            SurgicalProcedure.objects.create(case=case, tuss_code=self.tuss_a, quantity=1)
            SurgicalProcedure.objects.create(case=case, tuss_code=self.tuss_b, quantity=2)
        return case

    def test_finalized_case_generates_sadt_guide_with_priced_items(self):
        case = self._make_case()
        guide = generate_sadt_guide_for_surgical_case(case)
        self.assertEqual(guide.guide_type, "sadt")
        self.assertEqual(guide.surgical_case_id, case.id)
        self.assertEqual(guide.insured_card_number, "9990001112223")
        self.assertEqual(guide.provider_id, self.provider.id)
        by_code = {i.tuss_code.code: (i.quantity, i.unit_value) for i in guide.items.all()}
        self.assertEqual(by_code["30731011"], (Decimal("1"), Decimal("1200.00")))
        self.assertEqual(by_code["31003010"], (Decimal("2"), Decimal("800.00")))
        # total = 1×1200 + 2×800 = 2800
        self.assertEqual(guide.total_value, Decimal("2800.00"))

    def test_idempotent_no_duplicate_guide(self):
        case = self._make_case()
        first = generate_sadt_guide_for_surgical_case(case)
        second = generate_sadt_guide_for_surgical_case(case)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(TISSGuide.objects.filter(surgical_case=case).count(), 1)

    def test_unpriced_procedure_defaults_to_zero(self):
        tuss_x = TUSSCode.objects.create(
            code="30101018", description="Sem preço", group="procedimento", version="2024-01"
        )
        case = self._make_case()
        SurgicalProcedure.objects.create(case=case, tuss_code=tuss_x, quantity=1)
        guide = generate_sadt_guide_for_surgical_case(case)
        item = guide.items.get(tuss_code=tuss_x)
        self.assertEqual(item.unit_value, Decimal("0"))

    def test_not_finalized_case_raises(self):
        case = self._make_case(status=SurgicalCase.Status.EM_ANDAMENTO)
        with self.assertRaises(ValidationError):
            generate_sadt_guide_for_surgical_case(case)

    def test_no_encounter_raises(self):
        case = self._make_case(encounter=False)
        with self.assertRaises(ValidationError):
            generate_sadt_guide_for_surgical_case(case)

    def test_no_active_insurance_raises(self):
        PatientInsurance.objects.filter(patient=self.patient).update(is_active=False)
        case = self._make_case()
        with self.assertRaises(ValidationError):
            generate_sadt_guide_for_surgical_case(case)
