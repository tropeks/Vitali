"""
B3 — Admission → Guia TISS de Resumo de Internação.

generate_internacao_guide_for_admission monta as DailyCharge acumuladas (B2) numa
guia ``guide_type='internacao'``, precificando cada TUSS de diária pela PriceTable
ativa do convênio e agregando as diárias por TUSS. É idempotente (uma guia por
internação). Internações não faturáveis levantam ValidationError.
"""

import datetime
from decimal import Decimal

from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.billing.inpatient_models import AccommodationTuss, DailyCharge
from apps.billing.models import (
    InsuranceProvider,
    PriceTable,
    PriceTableItem,
    TISSGuide,
)
from apps.billing.services.inpatient_billing import (
    generate_internacao_guide_for_admission,
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


class InpatientGuideTestCase(TenantTestCase):
    def setUp(self):
        role = Role.objects.create(name="inp_guide", permissions=["emr.read", "emr.write"])
        self.user = User.objects.create_user(
            email="inp-guide@example.com", password="pw", role=role
        )
        self.prof = Professional.objects.create(
            user=self.user, council_type="CRM", council_number="G-1", council_state="SP"
        )
        self.patient = Patient.objects.create(
            full_name="Inp Guia Paciente", birth_date="1980-01-01", gender="M", cpf="52998224725"
        )
        self.encounter = Encounter.objects.create(patient=self.patient, professional=self.prof)

        # Convênio + carteirinha ativos.
        self.provider = InsuranceProvider.objects.create(name="Unimed Test", ans_code="333333")
        PatientInsurance.objects.create(
            patient=self.patient,
            provider_ans_code="333333",
            provider_name="Unimed Test",
            card_number="9990001112223",
            is_active=True,
        )

        # Estrutura física do leito (tipo 74 = UTI).
        self.legal = LegalEntity.objects.create(code="LE1", name="Hospital SA")
        self.facility = Facility.objects.create(
            code="FAC1", name="Hospital Central", legal_entity=self.legal
        )
        self.bed_type = BedType.objects.create(
            code="74", display="UTI adulto tipo II", category="Complementar"
        )
        self.unit = InpatientUnit.objects.create(facility=self.facility, name="Ala A", code="ALA-A")
        self.room = Room.objects.create(unit=self.unit, name="101")
        self.bed = Bed.objects.create(
            room=self.room, unit=self.unit, identifier="101-A", bed_type=self.bed_type
        )

        # TUSS de diária + mapeamento tipo-de-leito → TUSS + preço negociado.
        self.tuss_uti = TUSSCode.objects.create(
            code="60007650", description="Diária de UTI", group="diária", version="2024-01"
        )
        self.mapping = AccommodationTuss.objects.create(
            bed_type_code="74", tuss_code=self.tuss_uti, active=True
        )
        self.tuss_apto = TUSSCode.objects.create(
            code="60007600", description="Diária de Apartamento", group="diária", version="2024-01"
        )
        self.price_table = PriceTable.objects.create(
            provider=self.provider,
            name="Unimed 2026",
            valid_from=datetime.date(2026, 1, 1),
            is_active=True,
        )
        PriceTableItem.objects.create(
            table=self.price_table, tuss_code=self.tuss_uti, negotiated_value=Decimal("500.00")
        )
        PriceTableItem.objects.create(
            table=self.price_table, tuss_code=self.tuss_apto, negotiated_value=Decimal("300.00")
        )

    # ── helpers ─────────────────────────────────────────────────────────────
    def _dt(self, y, m, d, h=12):
        return timezone.make_aware(datetime.datetime(y, m, d, h, 0))

    def _admission(self, *, admit, discharge=None, bed=True, encounter=True, status=None):
        if status is None:
            status = Admission.Status.DISCHARGED if discharge else Admission.Status.ADMITTED
        return Admission.objects.create(
            patient=self.patient,
            admitting_professional=self.prof,
            attending_professional=self.prof,
            encounter=self.encounter if encounter else None,
            current_bed=self.bed if bed else None,
            admission_datetime=admit,
            actual_discharge_datetime=discharge,
            status=status,
        )

    # ── testes ──────────────────────────────────────────────────────────────
    def test_three_day_stay_generates_internacao_guide_one_priced_item(self):
        # Admite dia 1, alta dia 4 → 3 diárias de UTI → 1 item quantity=3.
        adm = self._admission(admit=self._dt(2026, 3, 1), discharge=self._dt(2026, 3, 4))
        guide = generate_internacao_guide_for_admission(adm)

        self.assertEqual(guide.guide_type, "internacao")
        self.assertEqual(guide.admission_id, adm.id)
        self.assertEqual(guide.provider_id, self.provider.id)
        self.assertEqual(guide.insured_card_number, "9990001112223")
        self.assertEqual(guide.price_table_id, self.price_table.id)

        items = list(guide.items.all())
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item.tuss_code_id, self.tuss_uti.id)
        self.assertEqual(item.quantity, Decimal("3"))
        self.assertEqual(item.unit_value, Decimal("500.00"))
        self.assertEqual(item.total_value, Decimal("1500.00"))
        # total = 3 × 500 = 1500
        self.assertEqual(guide.total_value, Decimal("1500.00"))

    def test_idempotent_no_duplicate_guide(self):
        adm = self._admission(admit=self._dt(2026, 3, 1), discharge=self._dt(2026, 3, 4))
        first = generate_internacao_guide_for_admission(adm)
        second = generate_internacao_guide_for_admission(adm)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(TISSGuide.objects.filter(admission=adm).count(), 1)

    def test_no_encounter_raises(self):
        adm = self._admission(
            admit=self._dt(2026, 3, 1), discharge=self._dt(2026, 3, 4), encounter=False
        )
        with self.assertRaises(ValidationError):
            generate_internacao_guide_for_admission(adm)
        self.assertEqual(TISSGuide.objects.filter(admission=adm).count(), 0)

    def test_no_active_insurance_raises(self):
        PatientInsurance.objects.filter(patient=self.patient).update(is_active=False)
        adm = self._admission(admit=self._dt(2026, 3, 1), discharge=self._dt(2026, 3, 4))
        with self.assertRaises(ValidationError):
            generate_internacao_guide_for_admission(adm)

    def test_no_daily_charges_raises_and_rolls_back(self):
        # Sem mapeamento de diária → accrue não cria nenhuma diária → erro, guia rollback.
        self.mapping.delete()
        adm = self._admission(admit=self._dt(2026, 3, 1), discharge=self._dt(2026, 3, 4))
        with self.assertRaises(ValidationError):
            generate_internacao_guide_for_admission(adm)
        self.assertEqual(TISSGuide.objects.filter(admission=adm).count(), 0)
        self.assertEqual(DailyCharge.objects.filter(admission=adm).count(), 0)

    def test_transfer_between_bed_types_aggregates_two_items_by_tuss(self):
        # Transferência: dias 1 e 2 em UTI, dia 3 em apartamento. Pré-materializa as
        # diárias com TUSS distintos; accrue não duplica (dias já presentes) → 2 itens.
        adm = self._admission(admit=self._dt(2026, 3, 1), discharge=self._dt(2026, 3, 4))
        for d, tuss, bt in (
            (1, self.tuss_uti, "74"),
            (2, self.tuss_uti, "74"),
            (3, self.tuss_apto, "31"),
        ):
            DailyCharge.objects.create(
                admission=adm,
                service_date=datetime.date(2026, 3, d),
                tuss_code=tuss,
                bed_type_code=bt,
                quantity=1,
            )

        guide = generate_internacao_guide_for_admission(adm)

        by_code = {
            i.tuss_code.code: (i.quantity, i.unit_value, i.total_value) for i in guide.items.all()
        }
        self.assertEqual(len(by_code), 2)
        self.assertEqual(by_code["60007650"], (Decimal("2"), Decimal("500.00"), Decimal("1000.00")))
        self.assertEqual(by_code["60007600"], (Decimal("1"), Decimal("300.00"), Decimal("300.00")))
        # total = 2×500 + 1×300 = 1300
        self.assertEqual(guide.total_value, Decimal("1300.00"))

    def test_unpriced_diaria_defaults_to_zero(self):
        # Diária sem item na PriceTable → unit_value 0 (nunca inventado).
        PriceTableItem.objects.filter(table=self.price_table, tuss_code=self.tuss_uti).delete()
        adm = self._admission(admit=self._dt(2026, 3, 1), discharge=self._dt(2026, 3, 2))
        guide = generate_internacao_guide_for_admission(adm)
        item = guide.items.get(tuss_code=self.tuss_uti)
        self.assertEqual(item.unit_value, Decimal("0"))
        self.assertEqual(item.total_value, Decimal("0"))
