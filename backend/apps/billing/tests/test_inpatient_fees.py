"""B6 — Taxas e gases medicinais de internação.

A diária de leito era a única coisa que uma estada gerava. Na conta hospitalar
brasileira ela é minoria: a tabela TUSS 18 tem 3.595 termos, dos quais ~1.590 são
TAXA (incubadora, almofada, equipamento…) e ~890 são gases medicinais. Sem elas,
a guia de internação sai sistematicamente subfaturada.

Diferença de forma em relação à diária, que é o motivo de existir um model
próprio em vez de reusar ``DailyCharge``:

* a diária tem ``UniqueConstraint(admission, service_date)`` — uma por dia;
* taxa NÃO: no mesmo dia cabem incubadora + oxigênio + bomba de infusão;
* e a taxa tem **unidade temporal própria** — o TUSS 18 distingue
  "TAXA DE INCUBADORA, POR DIA" de "TAXA DE INCUBADORA COM OXIGÊNIO, POR HORA",
  então a quantidade só significa alguma coisa junto da unidade.
"""

import datetime
from decimal import Decimal

from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.billing.inpatient_models import AccommodationTuss, InpatientFee
from apps.billing.models import (
    InsuranceProvider,
    PriceTable,
    PriceTableItem,
    TISSGuide,
)
from apps.billing.services.inpatient_billing import (
    generate_internacao_guide_for_admission,
    record_inpatient_fee,
)
from apps.core.models import BedType, Role, TUSSCode, User
from apps.emr.models import (
    Admission,
    Bed,
    Encounter,
    InpatientUnit,
    Patient,
    PatientInsurance,
    Professional,
    Room,
)
from apps.organization.models import Facility, LegalEntity
from apps.test_utils import TenantTestCase


class InpatientFeeTestCase(TenantTestCase):
    def setUp(self):
        role = Role.objects.create(name="fee_role", permissions=["emr.read", "emr.write"])
        self.user = User.objects.create_user(email="fee@example.com", password="pw", role=role)
        self.prof = Professional.objects.create(
            user=self.user, council_type="CRM", council_number="F-1", council_state="SP"
        )
        self.patient = Patient.objects.create(
            full_name="Fee Paciente", birth_date="1980-01-01", gender="M", cpf="52998224725"
        )
        self.legal = LegalEntity.objects.create(code="LE8", name="Hospital Fee SA")
        self.facility = Facility.objects.create(
            code="FAC8", name="Hospital Fee", legal_entity=self.legal
        )
        self.bed_type = BedType.objects.create(
            code="74", display="UTI adulto tipo II", category="Complementar"
        )
        self.unit = InpatientUnit.objects.create(facility=self.facility, name="Ala F", code="ALA-F")
        self.room = Room.objects.create(unit=self.unit, name="801")
        self.bed = Bed.objects.create(
            room=self.room, unit=self.unit, identifier="801-A", bed_type=self.bed_type
        )

        # TUSS da tabela 18: uma diária, uma taxa por dia, um gás por hora.
        self.tuss_diaria = TUSSCode.objects.create(
            code="60007650",
            description="DIÁRIA DE UTI ADULTO",
            group="Diárias, taxas e gases medicinais",
            table_number="18",
            version="202607",
        )
        self.tuss_taxa_dia = TUSSCode.objects.create(
            code="60027118",
            description="TAXA DE INCUBADORA, POR DIA",
            group="Diárias, taxas e gases medicinais",
            table_number="18",
            version="202607",
        )
        self.tuss_gas_hora = TUSSCode.objects.create(
            code="60025263",
            description="TAXA DE INCUBADORA COM OXIGÊNIO, POR HORA",
            group="Diárias, taxas e gases medicinais",
            table_number="18",
            version="202607",
        )
        # Um TUSS de PROCEDIMENTO (tabela 22) — não pode virar taxa de internação.
        self.tuss_procedimento = TUSSCode.objects.create(
            code="10101012",
            description="Consulta em consultório",
            group="Procedimentos e eventos em saúde",
            table_number="22",
            version="202607",
        )
        AccommodationTuss.objects.create(
            bed_type_code="74", tuss_code=self.tuss_diaria, active=True
        )
        self.admission = Admission.objects.create(
            patient=self.patient,
            admitting_professional=self.prof,
            attending_professional=self.prof,
            current_bed=self.bed,
            admission_datetime=timezone.now() - datetime.timedelta(days=2),
            status=Admission.Status.ADMITTED,
        )

    # ── lançamento ────────────────────────────────────────────────────────────

    def test_record_fee_stores_quantity_with_its_unit(self):
        """A quantidade só significa algo junto da unidade que o TUSS 18 declara."""
        fee = record_inpatient_fee(
            admission=self.admission,
            tuss_code=self.tuss_gas_hora,
            quantity=Decimal("6.5"),
            unit=InpatientFee.Unit.HORA,
            actor=self.user,
        )
        fee.refresh_from_db()
        self.assertEqual(fee.quantity, Decimal("6.5"))
        self.assertEqual(fee.unit, InpatientFee.Unit.HORA)
        self.assertEqual(fee.admission_id, self.admission.pk)
        # Snapshot da descrição: o catálogo pode ser reimportado e mudar o texto.
        self.assertEqual(fee.description, "TAXA DE INCUBADORA COM OXIGÊNIO, POR HORA")

    def test_several_fees_on_the_same_day_are_allowed(self):
        """No mesmo dia cabem incubadora + oxigênio — ao contrário da diária."""
        hoje = timezone.now().date()
        record_inpatient_fee(
            admission=self.admission,
            tuss_code=self.tuss_taxa_dia,
            quantity=Decimal("1"),
            unit=InpatientFee.Unit.DIA,
            service_date=hoje,
        )
        record_inpatient_fee(
            admission=self.admission,
            tuss_code=self.tuss_gas_hora,
            quantity=Decimal("8"),
            unit=InpatientFee.Unit.HORA,
            service_date=hoje,
        )
        self.assertEqual(InpatientFee.objects.filter(admission=self.admission).count(), 2)

    def test_rejects_tuss_outside_table_18(self):
        """Taxa de internação vem da tabela 18. Um procedimento (22) na conta de
        diárias é erro de codificação que vira glosa."""
        with self.assertRaises(ValidationError) as ctx:
            record_inpatient_fee(
                admission=self.admission,
                tuss_code=self.tuss_procedimento,
                quantity=Decimal("1"),
                unit=InpatientFee.Unit.DIA,
            )
        self.assertIn("18", str(ctx.exception))

    def test_accepts_legacy_tuss_without_table_number(self):
        """Código importado antes de o table_number ser preenchido não pode ser
        recusado — seria punir o dado legado por uma lacuna nossa."""
        legado = TUSSCode.objects.create(
            code="60099999", description="TAXA LEGADA", group="taxa", version=""
        )
        self.assertIsNone(legado.table_number)
        fee = record_inpatient_fee(
            admission=self.admission,
            tuss_code=legado,
            quantity=Decimal("1"),
            unit=InpatientFee.Unit.DIA,
        )
        self.assertIsNotNone(fee.pk)

    def test_rejects_non_positive_quantity(self):
        for bad in (Decimal("0"), Decimal("-1")):
            with self.assertRaises(ValidationError):
                record_inpatient_fee(
                    admission=self.admission,
                    tuss_code=self.tuss_taxa_dia,
                    quantity=bad,
                    unit=InpatientFee.Unit.DIA,
                )

    def test_rejects_fee_on_discharged_admission(self):
        """Depois da alta a conta está fechada para lançamento novo."""
        self.admission.status = Admission.Status.DISCHARGED
        self.admission.actual_discharge_datetime = timezone.now()
        self.admission.save()
        with self.assertRaises(ValidationError):
            record_inpatient_fee(
                admission=self.admission,
                tuss_code=self.tuss_taxa_dia,
                quantity=Decimal("1"),
                unit=InpatientFee.Unit.DIA,
            )

    # ── entram na guia ────────────────────────────────────────────────────────

    def test_fees_become_guide_items_alongside_dailies(self):
        encounter = Encounter.objects.create(
            patient=self.patient, professional=self.prof, encounter_type="inpatient"
        )
        self.admission.encounter = encounter
        self.admission.save()

        provider = InsuranceProvider.objects.create(name="Operadora Fee", ans_code="99123")
        PatientInsurance.objects.create(
            patient=self.patient,
            provider_ans_code="99123",
            provider_name="Operadora Fee",
            card_number="C-1",
            is_active=True,
        )
        table = PriceTable.objects.create(
            provider=provider, name="Tab Fee", valid_from=timezone.now().date()
        )
        for tuss, valor in (
            (self.tuss_diaria, "500.00"),
            (self.tuss_taxa_dia, "80.00"),
            (self.tuss_gas_hora, "12.50"),
        ):
            PriceTableItem.objects.create(
                table=table, tuss_code=tuss, negotiated_value=Decimal(valor)
            )

        record_inpatient_fee(
            admission=self.admission,
            tuss_code=self.tuss_taxa_dia,
            quantity=Decimal("2"),
            unit=InpatientFee.Unit.DIA,
        )
        record_inpatient_fee(
            admission=self.admission,
            tuss_code=self.tuss_gas_hora,
            quantity=Decimal("4"),
            unit=InpatientFee.Unit.HORA,
        )

        guide = generate_internacao_guide_for_admission(self.admission)

        codigos = {i.tuss_code.code: i for i in guide.items.select_related("tuss_code")}
        self.assertIn(self.tuss_diaria.code, codigos)  # diárias continuam lá
        self.assertIn(self.tuss_taxa_dia.code, codigos)
        self.assertIn(self.tuss_gas_hora.code, codigos)
        self.assertEqual(codigos[self.tuss_taxa_dia.code].quantity, Decimal("2"))
        self.assertEqual(codigos[self.tuss_gas_hora.code].unit_value, Decimal("12.50"))
        self.assertEqual(codigos[self.tuss_gas_hora.code].total_value, Decimal("50.00"))

    def test_same_tuss_fee_launched_twice_is_aggregated_in_one_item(self):
        encounter = Encounter.objects.create(
            patient=self.patient, professional=self.prof, encounter_type="inpatient"
        )
        self.admission.encounter = encounter
        self.admission.save()
        provider = InsuranceProvider.objects.create(name="Operadora Fee2", ans_code="99124")
        PatientInsurance.objects.create(
            patient=self.patient,
            provider_ans_code="99124",
            provider_name="Operadora Fee2",
            card_number="C-2",
            is_active=True,
        )
        table = PriceTable.objects.create(
            provider=provider, name="Tab Fee2", valid_from=timezone.now().date()
        )
        PriceTableItem.objects.create(
            table=table, tuss_code=self.tuss_diaria, negotiated_value=Decimal("500.00")
        )
        PriceTableItem.objects.create(
            table=table, tuss_code=self.tuss_gas_hora, negotiated_value=Decimal("10.00")
        )

        hoje = timezone.now().date()
        record_inpatient_fee(
            admission=self.admission,
            tuss_code=self.tuss_gas_hora,
            quantity=Decimal("3"),
            unit=InpatientFee.Unit.HORA,
            service_date=hoje,
        )
        record_inpatient_fee(
            admission=self.admission,
            tuss_code=self.tuss_gas_hora,
            quantity=Decimal("5"),
            unit=InpatientFee.Unit.HORA,
            service_date=hoje - datetime.timedelta(days=1),
        )

        guide = generate_internacao_guide_for_admission(self.admission)
        item = guide.items.get(tuss_code=self.tuss_gas_hora)
        self.assertEqual(item.quantity, Decimal("8"))  # 3 + 5 horas
        self.assertEqual(item.total_value, Decimal("80.00"))

    def test_guide_with_only_fees_and_no_dailies_is_still_billable(self):
        """Internação sem mapeamento de diária mas com taxas ainda gera guia.

        Antes, 'sem diária acumulada' abortava a guia inteira — o que jogaria
        fora as taxas de uma estada legítima só porque o tipo de leito não tinha
        AccommodationTuss configurado.
        """
        AccommodationTuss.objects.all().delete()
        encounter = Encounter.objects.create(
            patient=self.patient, professional=self.prof, encounter_type="inpatient"
        )
        self.admission.encounter = encounter
        self.admission.save()
        provider = InsuranceProvider.objects.create(name="Operadora Fee3", ans_code="99125")
        PatientInsurance.objects.create(
            patient=self.patient,
            provider_ans_code="99125",
            provider_name="Operadora Fee3",
            card_number="C-3",
            is_active=True,
        )
        table = PriceTable.objects.create(
            provider=provider, name="Tab Fee3", valid_from=timezone.now().date()
        )
        PriceTableItem.objects.create(
            table=table, tuss_code=self.tuss_taxa_dia, negotiated_value=Decimal("80.00")
        )
        record_inpatient_fee(
            admission=self.admission,
            tuss_code=self.tuss_taxa_dia,
            quantity=Decimal("1"),
            unit=InpatientFee.Unit.DIA,
        )

        guide = generate_internacao_guide_for_admission(self.admission)
        self.assertEqual(guide.items.count(), 1)
        self.assertEqual(guide.items.first().tuss_code_id, self.tuss_taxa_dia.pk)

    def test_guide_with_neither_dailies_nor_fees_still_refuses(self):
        AccommodationTuss.objects.all().delete()
        encounter = Encounter.objects.create(
            patient=self.patient, professional=self.prof, encounter_type="inpatient"
        )
        self.admission.encounter = encounter
        self.admission.save()
        provider = InsuranceProvider.objects.create(name="Operadora Fee4", ans_code="99126")
        PatientInsurance.objects.create(
            patient=self.patient,
            provider_ans_code="99126",
            provider_name="Operadora Fee4",
            card_number="C-4",
            is_active=True,
        )
        PriceTable.objects.create(
            provider=provider, name="Tab Fee4", valid_from=timezone.now().date()
        )
        with self.assertRaises(ValidationError):
            generate_internacao_guide_for_admission(self.admission)
        self.assertFalse(TISSGuide.objects.filter(admission=self.admission).exists())
