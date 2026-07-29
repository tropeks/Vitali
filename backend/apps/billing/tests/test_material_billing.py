"""
B4b — SurgicalMaterial → SP/SADT material billing / glosa bridge.
=================================================================
``bill_surgical_materials_for_case`` materializa cada ``SurgicalMaterial``
CONSUMIDO de um caso cirúrgico FINALIZADO na guia SP/SADT da cirurgia (a mesma do
B1, idempotente):

  * material com Simpro tabelado (Simpro + TUSS + preço negociado > 0) vira um
    ``TISSGuideItem`` precificado (valor negociado);
  * material sem Simpro/TUSS ou sem preço vira um ``GlosaSafetyAlert``
    NOT_IN_TABLE/ADVISE (não faturável, risco de glosa);
  * idempotente: re-rodar não duplica itens nem alertas;
  * cross-schema PROTECT: deletar um ``SimproMaterial`` referenciado por um
    ``SurgicalMaterial`` levanta ``ProtectedError``.

Espelha ``apps.billing.tests.test_surgery_billing`` e ``test_material_pricing``
(ambos usam ``TenantTestCase``).
"""

import datetime
from decimal import Decimal

from django.db import transaction
from django.db.models.deletion import ProtectedError
from rest_framework.exceptions import ValidationError

from apps.billing.material_models import MaterialPriceItem
from apps.billing.models import (
    GlosaSafetyAlert,
    InsuranceProvider,
    PriceTable,
    PriceTableItem,
    TISSGuideItem,
)
from apps.billing.services.material_billing import bill_surgical_materials_for_case
from apps.core.models import Role, SimproMaterial, TUSSCode, User
from apps.emr.models import (
    Encounter,
    Patient,
    PatientInsurance,
    Professional,
    SurgicalCase,
    SurgicalMaterial,
    SurgicalProcedure,
)
from apps.test_utils import TenantTestCase


class MaterialBillingTestCase(TenantTestCase):
    def setUp(self):
        role = Role.objects.create(name="mat_bill", permissions=["emr.read", "emr.write"])
        self.user = User.objects.create_user(email="mat-bill@example.com", password="pw", role=role)
        self.surgeon = Professional.objects.create(
            user=self.user, council_type="CRM", council_number="M-1", council_state="SP"
        )
        self.patient = Patient.objects.create(
            full_name="Mat Paciente", birth_date="1980-01-01", gender="M", cpf="54444444444"
        )
        self.encounter = Encounter.objects.create(patient=self.patient, professional=self.surgeon)
        self.provider = InsuranceProvider.objects.create(name="Unimed Mat", ans_code="444444")
        PatientInsurance.objects.create(
            patient=self.patient,
            provider_ans_code="444444",
            provider_name="Unimed Mat",
            card_number="1112223334445",
            is_active=True,
        )
        # Procedure TUSS + price so the SP/SADT guide (B1) is generatable.
        self.tuss_proc = TUSSCode.objects.create(
            code="30731011", description="Colecistectomia", group="procedimento", version="2024-01"
        )
        self.price_table = PriceTable.objects.create(
            provider=self.provider,
            name="Unimed 2026",
            valid_from=datetime.date(2026, 1, 1),
            is_active=True,
        )
        PriceTableItem.objects.create(
            table=self.price_table, tuss_code=self.tuss_proc, negotiated_value=Decimal("1200.00")
        )
        # Material TUSS codes (tabela 20 material) for the Simpro items.
        self.tuss_mat_a = TUSSCode.objects.create(
            code="90000010", description="Parafuso pedicular", group="material", version="2026-01"
        )
        self.tuss_mat_b = TUSSCode.objects.create(
            code="90000027", description="Placa de titânio", group="material", version="2026-01"
        )
        # Simpro catalog items (SHARED) with a TUSS correspondence.
        self.simpro_a = SimproMaterial.objects.create(
            code="SP-001",
            display="Parafuso de titânio 4.5mm",
            kind=SimproMaterial.Kind.OPME,
            tuss_code=self.tuss_mat_a,
            reference_price=Decimal("1250.0000"),
            edition="2026-07",
        )
        self.simpro_b = SimproMaterial.objects.create(
            code="SP-002",
            display="Placa de titânio 8 furos",
            kind=SimproMaterial.Kind.OPME,
            tuss_code=self.tuss_mat_b,
            reference_price=Decimal("2000.0000"),
            edition="2026-07",
        )
        # Negotiated prices for both materials.
        MaterialPriceItem.objects.create(
            table=self.price_table, simpro=self.simpro_a, negotiated_value=Decimal("980.00")
        )
        MaterialPriceItem.objects.create(
            table=self.price_table, simpro=self.simpro_b, negotiated_value=Decimal("1600.00")
        )

    def _make_case(self, status=SurgicalCase.Status.FINALIZADA):
        case = SurgicalCase.objects.create(
            patient=self.patient,
            encounter=self.encounter,
            surgeon=self.surgeon,
            status=status,
        )
        SurgicalProcedure.objects.create(case=case, tuss_code=self.tuss_proc, quantity=1)
        return case

    def _material_items(self, guide_id):
        return TISSGuideItem.objects.filter(guide_id=guide_id, surgical_material__isnull=False)

    def _not_in_table_alerts(self, guide_id):
        return GlosaSafetyAlert.objects.filter(
            guide_id=guide_id, check_code=GlosaSafetyAlert.CheckCode.NOT_IN_TABLE
        )

    # ── happy path: both materials tabulated + priced ────────────────────────
    def test_two_tabulated_materials_become_priced_guide_items(self):
        case = self._make_case()
        SurgicalMaterial.objects.create(
            case=case, kind=SurgicalMaterial.Kind.OPME, simpro=self.simpro_a, quantity_consumed=2
        )
        SurgicalMaterial.objects.create(
            case=case, kind=SurgicalMaterial.Kind.OPME, simpro=self.simpro_b, quantity_consumed=1
        )
        result = bill_surgical_materials_for_case(case)

        self.assertEqual(result.items_created, 2)
        self.assertEqual(result.alerts, 0)
        items = self._material_items(result.guide_id)
        self.assertEqual(items.count(), 2)
        by_code = {i.tuss_code.code: (i.quantity, i.unit_value, i.total_value) for i in items}
        self.assertEqual(by_code["90000010"], (Decimal("2"), Decimal("980.00"), Decimal("1960.00")))
        self.assertEqual(
            by_code["90000027"], (Decimal("1"), Decimal("1600.00"), Decimal("1600.00"))
        )
        self.assertEqual(self._not_in_table_alerts(result.guide_id).count(), 0)

    # ── material without simpro (free-text OPME) → glosa alert ────────────────
    def test_material_without_simpro_emits_glosa_alert(self):
        case = self._make_case()
        SurgicalMaterial.objects.create(
            case=case,
            kind=SurgicalMaterial.Kind.OPME,
            description="Prótese importada sem cadastro",
            quantity_consumed=1,
        )
        result = bill_surgical_materials_for_case(case)

        self.assertEqual(result.items_created, 0)
        self.assertEqual(result.alerts, 1)
        self.assertEqual(self._material_items(result.guide_id).count(), 0)
        alerts = self._not_in_table_alerts(result.guide_id)
        self.assertEqual(alerts.count(), 1)
        alert = alerts.first()
        self.assertEqual(alert.severity, GlosaSafetyAlert.Severity.ADVISE)
        self.assertIn("Prótese importada sem cadastro", alert.message)

    # ── material with simpro but no negotiated price (0) → glosa alert ────────
    def test_material_with_simpro_but_no_price_emits_glosa_alert(self):
        case = self._make_case()
        # Simpro tabelado (com TUSS) mas SEM MaterialPriceItem nesta tabela.
        simpro_c = SimproMaterial.objects.create(
            code="SP-003",
            display="Fio de sutura especial",
            kind=SimproMaterial.Kind.MATERIAL,
            tuss_code=self.tuss_mat_a,
            reference_price=Decimal("50.0000"),
            edition="2026-07",
        )
        SurgicalMaterial.objects.create(
            case=case, kind=SurgicalMaterial.Kind.MATERIAL, simpro=simpro_c, quantity_consumed=3
        )
        result = bill_surgical_materials_for_case(case)

        self.assertEqual(result.items_created, 0)
        self.assertEqual(result.alerts, 1)
        self.assertEqual(self._material_items(result.guide_id).count(), 0)
        self.assertEqual(self._not_in_table_alerts(result.guide_id).count(), 1)

    # ── idempotência: rodar 2x não duplica ───────────────────────────────────
    def test_idempotent_no_duplicate_items_or_alerts(self):
        case = self._make_case()
        SurgicalMaterial.objects.create(
            case=case, kind=SurgicalMaterial.Kind.OPME, simpro=self.simpro_a, quantity_consumed=2
        )
        SurgicalMaterial.objects.create(
            case=case,
            kind=SurgicalMaterial.Kind.OPME,
            description="OPME sem Simpro",
            quantity_consumed=1,
        )
        first = bill_surgical_materials_for_case(case)
        self.assertEqual(first.items_created, 1)
        self.assertEqual(first.alerts, 1)

        second = bill_surgical_materials_for_case(case)
        self.assertEqual(second.items_created, 0)
        self.assertEqual(second.items_existing, 1)
        self.assertEqual(second.alerts, 1)

        self.assertEqual(self._material_items(first.guide_id).count(), 1)
        self.assertEqual(self._not_in_table_alerts(first.guide_id).count(), 1)

    # ── quantity_consumed == 0 → ignorado ────────────────────────────────────
    def test_zero_consumed_material_is_ignored(self):
        case = self._make_case()
        SurgicalMaterial.objects.create(
            case=case,
            kind=SurgicalMaterial.Kind.OPME,
            simpro=self.simpro_a,
            quantity_planned=1,
            quantity_consumed=0,
        )
        result = bill_surgical_materials_for_case(case)
        self.assertEqual(result.items_created, 0)
        self.assertEqual(result.alerts, 0)
        self.assertEqual(self._material_items(result.guide_id).count(), 0)
        self.assertEqual(self._not_in_table_alerts(result.guide_id).count(), 0)

    # ── caso não finalizado → erro ───────────────────────────────────────────
    def test_not_finalized_case_raises(self):
        case = self._make_case(status=SurgicalCase.Status.EM_ANDAMENTO)
        SurgicalMaterial.objects.create(
            case=case, kind=SurgicalMaterial.Kind.OPME, simpro=self.simpro_a, quantity_consumed=1
        )
        with self.assertRaises(ValidationError):
            bill_surgical_materials_for_case(case)

    # ── cross-schema PROTECT: SimproMaterial usado por SurgicalMaterial ──────
    def test_delete_simpro_blocked_when_referenced_by_surgical_material(self):
        case = self._make_case()
        # Simpro referenciado APENAS por um SurgicalMaterial (sem MaterialPriceItem),
        # para exercitar especificamente o novo braço do guard (B4b) — o braço
        # MaterialPriceItem (B4a) já é coberto por test_material_pricing.
        simpro_only_surg = SimproMaterial.objects.create(
            code="SP-SURG-ONLY",
            display="OPME só cirúrgico",
            kind=SimproMaterial.Kind.OPME,
            tuss_code=self.tuss_mat_a,
        )
        SurgicalMaterial.objects.create(
            case=case,
            kind=SurgicalMaterial.Kind.OPME,
            simpro=simpro_only_surg,
            quantity_consumed=1,
        )
        with self.assertRaises(ProtectedError) as ctx, transaction.atomic():
            simpro_only_surg.delete()
        self.assertIn("SimproMaterial", str(ctx.exception))
        self.assertIn("SurgicalMaterial", str(ctx.exception))
        self.assertTrue(SimproMaterial.objects.filter(pk=simpro_only_surg.pk).exists())
