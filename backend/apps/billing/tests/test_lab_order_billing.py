"""
M2-S3-T4 — LabOrder → SP/SADT billing bridge.

generate_sadt_guide_for_lab_order turns a finalized (COMPLETED) LabOrder into one
TISS SP/SADT guide, pricing its items from the provider's active PriceTable, and
is idempotent (one guide per lab order). Non-billable orders raise ValidationError.
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
from apps.billing.services.lab_order_billing import generate_sadt_guide_for_lab_order
from apps.core.models import Role, TUSSCode, User
from apps.emr.models import (
    Encounter,
    LabOrder,
    LabOrderItem,
    LabTest,
    Patient,
    PatientInsurance,
    Professional,
)
from apps.test_utils import TenantTestCase


class LabOrderBillingTestCase(TenantTestCase):
    def setUp(self):
        role = Role.objects.create(name="lab_bill", permissions=["emr.read", "emr.write"])
        self.user = User.objects.create_user(email="lab-bill@example.com", password="pw", role=role)
        self.professional = Professional.objects.create(
            user=self.user, council_type="CRM", council_number="B-1", council_state="SP"
        )
        self.patient = Patient.objects.create(
            full_name="Bill Paciente", birth_date="1980-01-01", gender="M", cpf="54444444444"
        )
        self.encounter = Encounter.objects.create(
            patient=self.patient, professional=self.professional
        )
        self.provider = InsuranceProvider.objects.create(name="Unimed Test", ans_code="333333")
        PatientInsurance.objects.create(
            patient=self.patient,
            provider_ans_code="333333",
            provider_name="Unimed Test",
            card_number="9990001112223",
            is_active=True,
        )
        # TUSS-coded lab procedures (LabTest.code == TUSSCode.code).
        self.tuss_hb = TUSSCode.objects.create(
            code="40304361", description="Hemograma", group="procedimento", version="2024-01"
        )
        self.tuss_gluc = TUSSCode.objects.create(
            code="40302024", description="Glicose", group="procedimento", version="2024-01"
        )
        self.test_hb = LabTest.objects.create(code="40304361", name="Hemograma")
        self.test_gluc = LabTest.objects.create(code="40302024", name="Glicose")
        # Active negotiated price table.
        self.price_table = PriceTable.objects.create(
            provider=self.provider,
            name="Unimed 2026",
            valid_from=datetime.date(2026, 1, 1),
            is_active=True,
        )
        PriceTableItem.objects.create(
            table=self.price_table, tuss_code=self.tuss_hb, negotiated_value=Decimal("50.00")
        )
        PriceTableItem.objects.create(
            table=self.price_table, tuss_code=self.tuss_gluc, negotiated_value=Decimal("30.00")
        )

    def _make_order(self, *, status=LabOrder.Status.COMPLETED, encounter=True):
        order = LabOrder.objects.create(
            patient=self.patient,
            encounter=self.encounter if encounter else None,
            requested_by=self.user,
            status=status,
        )
        for test in (self.test_hb, self.test_gluc):
            LabOrderItem.objects.create(order=order, test=test, test_name=test.name)
        return order

    def test_completed_order_generates_sadt_guide_with_priced_items(self):
        order = self._make_order()
        guide = generate_sadt_guide_for_lab_order(order)
        self.assertEqual(guide.guide_type, "sadt")
        self.assertEqual(guide.lab_order_id, order.id)
        self.assertEqual(guide.insured_card_number, "9990001112223")
        self.assertEqual(guide.provider_id, self.provider.id)
        codes = {i.tuss_code.code: i.unit_value for i in guide.items.all()}
        self.assertEqual(codes, {"40304361": Decimal("50.00"), "40302024": Decimal("30.00")})
        self.assertEqual(guide.total_value, Decimal("80.00"))

    def test_solicitante_herdado_de_quem_pediu_o_exame(self):
        """``requesting_professional`` sai de ``LabOrder.requested_by`` — o médico
        que pediu o exame É o solicitante da guia SP/SADT (dadosSolicitante).

        Trava o que NÃO pode acontecer: cair no executante. Aqui os dois são a
        mesma pessoa por acaso do fixture, então a asserção é sobre a ORIGEM do
        vínculo, não sobre o valor — o teste de ponta a ponta que separa os dois
        papéis vive em SadtSolicitanteResolutionTests.
        """
        order = self._make_order()

        guide = generate_sadt_guide_for_lab_order(order)

        self.assertEqual(guide.requesting_professional_id, order.requested_by.professional.id)

    def test_pedido_de_quem_nao_e_profissional_nao_vira_solicitante(self):
        """``requested_by`` é um ``core.User``, e nem todo usuário tem perfil de
        profissional — recepção que registra um pedido não tem conselho/CBO, que
        é justamente o que ``profissionalSolicitante`` exige. Fica nulo, e a
        emissão do XML falha alto depois; nunca se inventa um conselho."""
        recepcao = User.objects.create_user(
            email="recepcao-lab@example.com", password="pw", role=self.user.role
        )
        order = self._make_order()
        order.requested_by = recepcao
        order.save(update_fields=["requested_by"])

        guide = generate_sadt_guide_for_lab_order(order)

        self.assertIsNone(guide.requesting_professional_id)

    def test_idempotent_no_duplicate_guide(self):
        order = self._make_order()
        first = generate_sadt_guide_for_lab_order(order)
        second = generate_sadt_guide_for_lab_order(order)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(TISSGuide.objects.filter(lab_order=order).count(), 1)

    def test_unpriced_item_defaults_to_zero(self):
        # A TUSS-coded test with no PriceTableItem → unit_value 0 (never fabricated).
        tuss_x = TUSSCode.objects.create(
            code="40301010", description="TSH", group="procedimento", version="2024-01"
        )
        test_x = LabTest.objects.create(code="40301010", name="TSH")
        order = self._make_order()
        LabOrderItem.objects.create(order=order, test=test_x, test_name="TSH")
        guide = generate_sadt_guide_for_lab_order(order)
        tsh_item = guide.items.get(tuss_code=tuss_x)
        self.assertEqual(tsh_item.unit_value, Decimal("0"))

    def test_non_tuss_item_skipped(self):
        order = self._make_order()
        non_tuss = LabTest.objects.create(code="INTERNAL-XYZ", name="Exame interno")
        LabOrderItem.objects.create(order=order, test=non_tuss, test_name="Exame interno")
        guide = generate_sadt_guide_for_lab_order(order)
        self.assertEqual(guide.items.count(), 2)  # only the two TUSS-coded tests

    def test_not_completed_order_raises(self):
        order = self._make_order(status=LabOrder.Status.IN_PROGRESS)
        with self.assertRaises(ValidationError):
            generate_sadt_guide_for_lab_order(order)

    def test_no_encounter_raises(self):
        order = self._make_order(encounter=False)
        with self.assertRaises(ValidationError):
            generate_sadt_guide_for_lab_order(order)

    def test_no_active_insurance_raises(self):
        PatientInsurance.objects.filter(patient=self.patient).update(is_active=False)
        order = self._make_order()
        with self.assertRaises(ValidationError):
            generate_sadt_guide_for_lab_order(order)
