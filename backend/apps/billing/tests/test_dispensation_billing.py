"""B9 — Medicamento dispensado vira linha de conta.

Material de centro cirúrgico já era cobrado. Medicamento dispensado em
enfermaria, emergência ou ambulatório saía do estoque e não virava receita
nenhuma: o remédio some da prateleira e ninguém cobra.

O que se testa aqui é o receiver, alimentado pelo sinal
``core.dispensation_signals.dispensation_billable`` — o mesmo payload primitivo
que a farmácia emite. Testar pelo sinal, e não chamando a farmácia, é
proposital: é exatamente assim que os dois domínios se falam, e o teste falharia
se alguém trocasse o contrato do payload.
"""

from decimal import Decimal
from uuid import uuid4

from apps.billing.models import InsuranceProvider, PriceTable, PriceTableItem, TISSGuideItem
from apps.core.dispensation_signals import dispensation_billable
from apps.core.models import Role, TUSSCode, User
from apps.emr.models import Encounter, Patient, PatientInsurance, Professional
from apps.test_utils import TenantTestCase


class DispensationBillingTestCase(TenantTestCase):
    def setUp(self):
        role = Role.objects.create(name="disp_bill", permissions=["emr.read"])
        self.user = User.objects.create_user(email="disp@example.com", password="pw", role=role)
        self.prof = Professional.objects.create(
            user=self.user, council_type="CRM", council_number="D-1", council_state="SP"
        )
        self.patient = Patient.objects.create(
            full_name="Disp Paciente", birth_date="1980-01-01", gender="M", cpf="52998224725"
        )
        self.encounter = Encounter.objects.create(patient=self.patient, professional=self.prof)

        self.provider = InsuranceProvider.objects.create(name="Operadora Disp", ans_code="88111")
        PatientInsurance.objects.create(
            patient=self.patient,
            provider_ans_code="88111",
            provider_name="Operadora Disp",
            card_number="D-9",
            is_active=True,
        )
        from django.utils import timezone

        self.table = PriceTable.objects.create(
            provider=self.provider, name="Tab Disp", valid_from=timezone.now().date()
        )
        # TUSS 20 com a ponte para o registro ANVISA (B8).
        self.tuss_med = TUSSCode.objects.create(
            code="90035593",
            description="ORENCIA 250MG",
            group="Medicamentos",
            table_number="20",
            anvisa_registro="1018003900019",
            version="202607",
        )
        PriceTableItem.objects.create(
            table=self.table, tuss_code=self.tuss_med, negotiated_value=Decimal("120.00")
        )

    def _dispense(self, **over):
        payload = {
            "encounter_id": self.encounter.pk,
            "patient_id": self.patient.pk,
            "anvisa_registro": "1018003900019",
            "quantity": Decimal("2"),
            "description": "ORENCIA",
            "source_id": uuid4(),
        }
        payload.update(over)
        dispensation_billable.send(sender=None, **payload)
        return payload["source_id"]

    def test_dispensation_becomes_a_priced_guide_item(self):
        source = self._dispense()
        item = TISSGuideItem.objects.get(dispensation_source_id=source)
        self.assertEqual(item.tuss_code_id, self.tuss_med.pk)
        self.assertEqual(item.quantity, Decimal("2"))
        self.assertEqual(item.unit_value, Decimal("120.00"))
        self.assertEqual(item.total_value, Decimal("240.00"))
        self.assertEqual(item.guide.encounter_id, self.encounter.pk)

    def test_reprocessing_does_not_bill_the_same_drug_twice(self):
        source = uuid4()
        self._dispense(source_id=source)
        self._dispense(source_id=source)
        self.assertEqual(TISSGuideItem.objects.filter(dispensation_source_id=source).count(), 1)

    def test_several_dispensations_share_one_guide_per_encounter(self):
        """Uma guia por atendimento, não uma por remédio."""
        self._dispense()
        self._dispense()
        guias = {i.guide_id for i in TISSGuideItem.objects.all()}
        self.assertEqual(len(guias), 1)
        self.assertEqual(TISSGuideItem.objects.count(), 2)

    def test_product_level_registro_still_resolves(self):
        """A dispensação costuma conhecer só o produto (9 dígitos)."""
        source = self._dispense(anvisa_registro="101800390")
        self.assertTrue(TISSGuideItem.objects.filter(dispensation_source_id=source).exists())

    # ── saídas silenciosas legítimas ──────────────────────────────────────────

    def test_drug_without_tuss_is_not_billed(self):
        source = self._dispense(anvisa_registro="9999999999999")
        self.assertFalse(TISSGuideItem.objects.filter(dispensation_source_id=source).exists())

    def test_patient_without_insurance_is_not_billed(self):
        PatientInsurance.objects.filter(patient=self.patient).update(is_active=False)
        source = self._dispense()
        self.assertFalse(TISSGuideItem.objects.filter(dispensation_source_id=source).exists())

    def test_zero_quantity_is_not_billed(self):
        source = self._dispense(quantity=Decimal("0"))
        self.assertFalse(TISSGuideItem.objects.filter(dispensation_source_id=source).exists())

    def test_dispensation_without_encounter_is_not_billed(self):
        source = self._dispense(encounter_id=None)
        self.assertFalse(TISSGuideItem.objects.filter(dispensation_source_id=source).exists())

    def test_billing_failure_never_propagates_to_the_dispenser(self):
        """Faturamento quebrado não pode impedir o remédio de chegar ao paciente."""
        from unittest.mock import patch

        with patch(
            "apps.billing.services.dispensation_billing._bill",
            side_effect=RuntimeError("billing pifou"),
        ):
            # Não levanta: o receiver engole e loga.
            self._dispense()
