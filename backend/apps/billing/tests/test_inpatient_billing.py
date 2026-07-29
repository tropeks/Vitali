"""
B2 — Admission → diárias de leito (acúmulo faturável).

accrue_daily_charges percorre a estada de uma internação e materializa uma
DailyCharge por dia faturável (regra de pernoites: cobra a admissão e cada dia
subsequente, mas NÃO o dia da alta; admite+alta no mesmo dia = 1). É idempotente
e resolve o TUSS da diária via AccommodationTuss a partir do tipo de leito.
"""

import datetime

from django.utils import timezone

from apps.billing.inpatient_models import AccommodationTuss, DailyCharge
from apps.billing.services.inpatient_billing import accrue_daily_charges
from apps.core.models import BedType, Role, TUSSCode, User
from apps.emr.models import (
    Admission,
    Bed,
    InpatientUnit,
    Patient,
    Professional,
    Room,
)
from apps.organization.models import Facility, LegalEntity
from apps.test_utils import TenantTestCase


class InpatientBillingTestCase(TenantTestCase):
    def setUp(self):
        role = Role.objects.create(name="inp_bill", permissions=["emr.read", "emr.write"])
        self.user = User.objects.create_user(email="inp-bill@example.com", password="pw", role=role)
        self.prof = Professional.objects.create(
            user=self.user, council_type="CRM", council_number="I-1", council_state="SP"
        )
        self.patient = Patient.objects.create(
            full_name="Inp Paciente", birth_date="1980-01-01", gender="M", cpf="52998224725"
        )

        # Estrutura física do leito.
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

        # TUSS da diária + mapeamento tipo-de-leito → TUSS.
        self.tuss_diaria = TUSSCode.objects.create(
            code="60007650", description="Diária de UTI", group="diária", version="2024-01"
        )
        self.mapping = AccommodationTuss.objects.create(
            bed_type_code="74", tuss_code=self.tuss_diaria, active=True
        )

    # ── helper ────────────────────────────────────────────────────────────────
    def _dt(self, y, m, d, h=12):
        return timezone.make_aware(datetime.datetime(y, m, d, h, 0))

    def _admission(self, *, admit, discharge=None, bed=True, status=None):
        if status is None:
            status = Admission.Status.DISCHARGED if discharge else Admission.Status.ADMITTED
        return Admission.objects.create(
            patient=self.patient,
            admitting_professional=self.prof,
            attending_professional=self.prof,
            current_bed=self.bed if bed else None,
            admission_datetime=admit,
            actual_discharge_datetime=discharge,
            status=status,
        )

    # ── testes ──────────────────────────────────────────────────────────────
    def test_three_day_stay_charges_three_days_not_discharge_day(self):
        # Admite dia 1, alta dia 4 → diárias nos dias 1, 2, 3 (dia 4 não).
        adm = self._admission(admit=self._dt(2026, 3, 1), discharge=self._dt(2026, 3, 4))
        charges = accrue_daily_charges(adm)
        dates = sorted(c.service_date for c in charges)
        self.assertEqual(
            dates,
            [datetime.date(2026, 3, 1), datetime.date(2026, 3, 2), datetime.date(2026, 3, 3)],
        )
        self.assertEqual(DailyCharge.objects.filter(admission=adm).count(), 3)
        for c in charges:
            self.assertEqual(c.quantity, 1)
            self.assertEqual(c.tuss_code_id, self.tuss_diaria.id)
            self.assertEqual(c.bed_type_code, "74")

    def test_idempotent_rerun_does_not_duplicate(self):
        adm = self._admission(admit=self._dt(2026, 3, 1), discharge=self._dt(2026, 3, 4))
        first = accrue_daily_charges(adm)
        second = accrue_daily_charges(adm)
        self.assertEqual(len(first), 3)
        self.assertEqual(len(second), 0)  # nada novo criado
        self.assertEqual(DailyCharge.objects.filter(admission=adm).count(), 3)

    def test_active_admission_accrues_through_today_inclusive(self):
        today = timezone.now().date()
        admit_dt = timezone.now() - datetime.timedelta(days=2)
        adm = self._admission(admit=admit_dt, status=Admission.Status.ADMITTED)
        charges = accrue_daily_charges(adm)
        dates = sorted(c.service_date for c in charges)
        expected = [
            admit_dt.date(),
            admit_dt.date() + datetime.timedelta(days=1),
            today,
        ]
        self.assertEqual(dates, expected)
        self.assertIn(today, dates)  # hoje inclusive

    def test_same_day_admit_and_discharge_charges_one(self):
        adm = self._admission(admit=self._dt(2026, 3, 1, 8), discharge=self._dt(2026, 3, 1, 20))
        charges = accrue_daily_charges(adm)
        self.assertEqual(len(charges), 1)
        self.assertEqual(charges[0].service_date, datetime.date(2026, 3, 1))
        self.assertEqual(charges[0].quantity, 1)

    def test_no_mapping_for_bed_type_yields_no_charges(self):
        self.mapping.delete()  # sem AccommodationTuss para o tipo de leito
        adm = self._admission(admit=self._dt(2026, 3, 1), discharge=self._dt(2026, 3, 4))
        charges = accrue_daily_charges(adm)
        self.assertEqual(charges, [])
        self.assertEqual(DailyCharge.objects.filter(admission=adm).count(), 0)

    def test_inactive_mapping_is_ignored(self):
        self.mapping.active = False
        self.mapping.save(update_fields=["active"])
        adm = self._admission(admit=self._dt(2026, 3, 1), discharge=self._dt(2026, 3, 4))
        charges = accrue_daily_charges(adm)
        self.assertEqual(charges, [])

    def test_no_current_bed_yields_no_charges(self):
        adm = self._admission(
            admit=self._dt(2026, 3, 1),
            discharge=self._dt(2026, 3, 4),
            bed=False,
        )
        charges = accrue_daily_charges(adm)
        self.assertEqual(charges, [])
