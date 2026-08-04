"""B5 — As diárias não podem se perder entre a alta e o faturamento.

``accrue_daily_charges`` sabe acumular, mas até aqui só era chamado por quem
gerava a guia. Como ``adt.discharge`` zera ``Admission.current_bed``, uma guia
emitida DEPOIS da alta não tem mais como resolver o tipo de leito: as diárias
não acumuladas somem em silêncio — receita perdida sem erro nenhum.

Duas defesas, testadas aqui:

* **na alta** — o ADT emite ``admission_pre_bed_release`` com o leito ainda
  atribuído, e o billing acumula ouvindo esse sinal (o ADT não importa billing:
  o contrato do import-linter proíbe ``apps.emr -> apps.billing``);
* **diária** — uma task periódica acumula as internações ativas, para que uma
  estada longa não dependa de ninguém lembrar de faturar.
"""

import datetime

from django.utils import timezone

from apps.billing.inpatient_models import AccommodationTuss, DailyCharge
from apps.core.models import BedType, Role, TUSSCode, User
from apps.emr.models import (
    Admission,
    Bed,
    InpatientUnit,
    Patient,
    Professional,
    Room,
)
from apps.emr.services import adt
from apps.organization.models import Facility, LegalEntity
from apps.test_utils import TenantTestCase


class InpatientAccrualHooksTestCase(TenantTestCase):
    def setUp(self):
        role = Role.objects.create(name="accr_hook", permissions=["emr.read", "emr.write"])
        self.user = User.objects.create_user(
            email="accr-hook@example.com", password="pw", role=role
        )
        self.prof = Professional.objects.create(
            user=self.user, council_type="CRM", council_number="H-1", council_state="SP"
        )
        self.patient = Patient.objects.create(
            full_name="Hook Paciente", birth_date="1980-01-01", gender="M", cpf="52998224725"
        )
        self.legal = LegalEntity.objects.create(code="LE9", name="Hospital Hook SA")
        self.facility = Facility.objects.create(
            code="FAC9", name="Hospital Hook", legal_entity=self.legal
        )
        self.bed_type = BedType.objects.create(
            code="74", display="UTI adulto tipo II", category="Complementar"
        )
        self.unit = InpatientUnit.objects.create(facility=self.facility, name="Ala H", code="ALA-H")
        self.room = Room.objects.create(unit=self.unit, name="901")
        self.bed = Bed.objects.create(
            room=self.room, unit=self.unit, identifier="901-A", bed_type=self.bed_type
        )
        self.tuss_diaria = TUSSCode.objects.create(
            code="60007650", description="Diária de UTI", group="diária", version="202607"
        )
        AccommodationTuss.objects.create(
            bed_type_code="74", tuss_code=self.tuss_diaria, active=True
        )

    def _admit(self, days_ago: int) -> Admission:
        return Admission.objects.create(
            patient=self.patient,
            admitting_professional=self.prof,
            attending_professional=self.prof,
            current_bed=self.bed,
            admission_datetime=timezone.now() - datetime.timedelta(days=days_ago),
            status=Admission.Status.ADMITTED,
        )

    # ── na alta ───────────────────────────────────────────────────────────────

    def test_discharge_accrues_before_releasing_the_bed(self):
        """A alta acumula as diárias enquanto o leito ainda está atribuído.

        Sem isso, current_bed vira NULL e o tipo de leito — logo o TUSS da
        diária — deixa de ser resolvível para sempre.
        """
        admission = self._admit(days_ago=3)
        self.assertEqual(DailyCharge.objects.filter(admission=admission).count(), 0)

        adt.discharge(admission=admission, disposition="casa", actor=self.user)

        admission.refresh_from_db()
        self.assertIsNone(admission.current_bed)  # leito liberado, como antes
        charges = DailyCharge.objects.filter(admission=admission)
        # Regra de pernoites: cobra admissão e intermediários, não o dia da alta.
        self.assertEqual(charges.count(), 3)
        self.assertTrue(all(c.tuss_code_id == self.tuss_diaria.pk for c in charges))
        # O snapshot do tipo de leito sobrevive à liberação.
        self.assertTrue(all(c.bed_type_code == "74" for c in charges))

    def test_discharge_accrual_is_idempotent_with_prior_accrual(self):
        """Se já houve acúmulo durante a estada, a alta não duplica nada."""
        from apps.billing.services.inpatient_billing import accrue_daily_charges

        admission = self._admit(days_ago=3)
        accrue_daily_charges(admission)
        antes = DailyCharge.objects.filter(admission=admission).count()

        adt.discharge(admission=admission, disposition="casa", actor=self.user)

        depois = DailyCharge.objects.filter(admission=admission).count()
        self.assertGreaterEqual(depois, antes)
        datas = list(
            DailyCharge.objects.filter(admission=admission).values_list("service_date", flat=True)
        )
        self.assertEqual(len(datas), len(set(datas)))  # um por dia, sem duplicata

    def test_billing_failure_never_blocks_a_discharge(self):
        """Alta é ato clínico: faturamento quebrado não pode impedir o paciente de sair.

        A diária perdida é recuperável (a task diária acumula durante a estada);
        um paciente preso no leito por erro de billing, não.
        """
        from unittest.mock import patch

        admission = self._admit(days_ago=2)
        with patch(
            "apps.billing.services.inpatient_billing.accrue_daily_charges",
            side_effect=RuntimeError("billing pifou"),
        ):
            adt.discharge(admission=admission, disposition="casa", actor=self.user)

        admission.refresh_from_db()
        self.assertEqual(admission.status, Admission.Status.DISCHARGED)
        self.assertIsNone(admission.current_bed)

    def test_discharge_without_mapping_is_silent_and_harmless(self):
        """Internação sem AccommodationTuss (particular/sem config) não quebra a alta."""
        AccommodationTuss.objects.all().delete()
        admission = self._admit(days_ago=2)

        adt.discharge(admission=admission, disposition="casa", actor=self.user)

        admission.refresh_from_db()
        self.assertEqual(admission.status, Admission.Status.DISCHARGED)
        self.assertEqual(DailyCharge.objects.filter(admission=admission).count(), 0)

    # ── task periódica ────────────────────────────────────────────────────────

    def test_periodic_task_accrues_active_admissions(self):
        from apps.billing.services.tasks import _accrue_daily_charges_for_schema

        ativa = self._admit(days_ago=2)
        self.assertEqual(DailyCharge.objects.filter(admission=ativa).count(), 0)

        result = _accrue_daily_charges_for_schema(self.tenant.schema_name)

        self.assertGreaterEqual(result["charges"], 3)
        self.assertEqual(result["admissions"], 1)
        self.assertGreaterEqual(DailyCharge.objects.filter(admission=ativa).count(), 3)

    def test_periodic_task_skips_discharged_admissions(self):
        """Internação com alta já saiu da janela da task — quem cuidou dela foi o hook."""
        from apps.billing.services.tasks import _accrue_daily_charges_for_schema

        admission = self._admit(days_ago=2)
        adt.discharge(admission=admission, disposition="casa", actor=self.user)
        antes = DailyCharge.objects.filter(admission=admission).count()

        result = _accrue_daily_charges_for_schema(self.tenant.schema_name)

        self.assertEqual(result["admissions"], 0)
        self.assertEqual(DailyCharge.objects.filter(admission=admission).count(), antes)

    def test_periodic_task_is_idempotent(self):
        from apps.billing.services.tasks import _accrue_daily_charges_for_schema

        self._admit(days_ago=2)
        _accrue_daily_charges_for_schema(self.tenant.schema_name)
        total = DailyCharge.objects.count()

        segunda = _accrue_daily_charges_for_schema(self.tenant.schema_name)

        self.assertEqual(segunda["charges"], 0)  # nada novo no mesmo dia
        self.assertEqual(DailyCharge.objects.count(), total)
