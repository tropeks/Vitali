"""B7 — Cirurgia pelo SUS deixa de ser infaturável.

``SurgicalProcedure`` só tinha ``tuss_code``, que é o eixo do convênio. Sem
codificação SIGTAP, uma cirurgia feita pelo SUS não entrava em AIH, BPA nem
APAC: o procedimento acontecia, consumia sala e equipe, e não virava receita
nenhuma. O ``EncounterProcedure`` já carregava os dois eixos (TUSS e SIGTAP) —
aqui a cirurgia passa a carregar também.

O procedimento **principal** da AIH continua sendo decisão humana de
codificação, como o ``generate_aih_for_admission`` já exige e documenta. O que
a cirurgia faz é entrar como **secundária** (auto-puxada, igual às do encounter)
e expor seu SIGTAP para quem for codificar escolher com conhecimento de causa.
"""

import datetime

from django.core.exceptions import ValidationError
from django.db.models import ProtectedError
from django.utils import timezone

from apps.billing.services.aih_billing import generate_aih_for_admission
from apps.billing.services.surgery_sus import sigtap_candidates_for_admission
from apps.billing.sus_models import SusCompetencia
from apps.core.models import Role, SIGTAPProcedure, TUSSCode, User
from apps.emr.models import Admission, Encounter, Patient, Professional
from apps.emr.surgery_models import SurgicalCase, SurgicalProcedure
from apps.organization.models import Facility, LegalEntity
from apps.test_utils import TenantTestCase


class SurgerySusTestCase(TenantTestCase):
    def setUp(self):
        role = Role.objects.create(name="sus_surg", permissions=["emr.read", "emr.write"])
        self.user = User.objects.create_user(email="sus-surg@example.com", password="pw", role=role)
        self.prof = Professional.objects.create(
            user=self.user, council_type="CRM", council_number="S-1", council_state="SP"
        )
        self.patient = Patient.objects.create(
            full_name="SUS Paciente", birth_date="1980-01-01", gender="M", cpf="52998224725"
        )
        # tuss_code segue obrigatorio no SurgicalProcedure (terminologia
        # unificada); o SIGTAP e o eixo SUS que faltava, adicionado como opcional.
        self.tuss = TUSSCode.objects.create(
            code="31003010", description="Colecistectomia", group="cirurgia", version="202607"
        )
        self.sig_principal = SIGTAPProcedure.objects.create(
            code="0407010173", display="COLECISTECTOMIA", version="202607"
        )
        self.sig_cirurgia = SIGTAPProcedure.objects.create(
            code="0407020055", display="HERNIORRAFIA INGUINAL", version="202607"
        )

        self.encounter = Encounter.objects.create(
            patient=self.patient, professional=self.prof, encounter_type="inpatient"
        )
        self.admission = Admission.objects.create(
            patient=self.patient,
            admitting_professional=self.prof,
            attending_professional=self.prof,
            encounter=self.encounter,
            admission_datetime=timezone.now() - datetime.timedelta(days=3),
            actual_discharge_datetime=timezone.now(),
            status=Admission.Status.DISCHARGED,
        )
        self.legal = LegalEntity.objects.create(code="LE7", name="Hospital SUS SA")
        self.facility = Facility.objects.create(
            code="FAC7", name="Hospital SUS", legal_entity=self.legal
        )
        self.competencia = SusCompetencia.objects.create(
            establishment=self.facility, competencia="202608", created_by=self.user
        )

    def _case(self, *, status=None):
        return SurgicalCase.objects.create(
            patient=self.patient,
            surgeon=self.prof,
            encounter=self.encounter,
            status=status or SurgicalCase.Status.FINALIZADA,
        )

    # ── o campo ───────────────────────────────────────────────────────────────

    def test_surgical_procedure_carries_sigtap(self):
        """A cirurgia passa a ter os dois eixos, como o EncounterProcedure."""
        case = self._case()
        proc = SurgicalProcedure.objects.create(
            case=case, tuss_code=self.tuss, sigtap=self.sig_cirurgia, quantity=1
        )
        proc.refresh_from_db()
        self.assertEqual(proc.sigtap_id, self.sig_cirurgia.pk)
        self.assertEqual(proc.sigtap_code_value, "0407020055")

    def test_sigtap_code_value_is_null_safe(self):
        case = self._case()
        proc = SurgicalProcedure.objects.create(case=case, tuss_code=self.tuss, quantity=1)
        self.assertEqual(proc.sigtap_code_value, "")

    def test_sigtap_referenced_by_surgery_cannot_be_deleted(self):
        """Mesma proteção cross-schema do EncounterProcedure: catálogo governado
        não pode sumir debaixo de um procedimento já codificado."""
        case = self._case()
        SurgicalProcedure.objects.create(
            case=case, tuss_code=self.tuss, sigtap=self.sig_cirurgia, quantity=1
        )
        with self.assertRaises(ProtectedError):
            self.sig_cirurgia.delete()

    # ── entra na AIH ──────────────────────────────────────────────────────────

    def test_surgery_sigtap_becomes_aih_secondary(self):
        case = self._case()
        SurgicalProcedure.objects.create(
            case=case, tuss_code=self.tuss, sigtap=self.sig_cirurgia, quantity=1
        )

        aih = generate_aih_for_admission(
            self.admission, self.competencia, procedimento_principal=self.sig_principal
        )

        secundarios = {
            s.sigtap.code for s in aih.procedimentos_secundarios.select_related("sigtap")
        }
        self.assertIn("0407020055", secundarios)

    def test_surgery_equal_to_principal_is_not_duplicated_as_secondary(self):
        """Se o codificador escolheu a própria cirurgia como principal, ela não
        pode voltar como secundária — seria faturar o mesmo ato duas vezes."""
        case = self._case()
        SurgicalProcedure.objects.create(
            case=case, tuss_code=self.tuss, sigtap=self.sig_principal, quantity=1
        )

        aih = generate_aih_for_admission(
            self.admission, self.competencia, procedimento_principal=self.sig_principal
        )

        codigos = [s.sigtap.code for s in aih.procedimentos_secundarios.select_related("sigtap")]
        self.assertNotIn(self.sig_principal.code, codigos)

    def test_unfinished_surgery_does_not_reach_the_aih(self):
        """Cirurgia agendada/em andamento não é ato executado — não fatura."""
        case = self._case(status=SurgicalCase.Status.AGENDADA)
        SurgicalProcedure.objects.create(
            case=case, tuss_code=self.tuss, sigtap=self.sig_cirurgia, quantity=1
        )

        aih = generate_aih_for_admission(
            self.admission, self.competencia, procedimento_principal=self.sig_principal
        )

        codigos = [s.sigtap.code for s in aih.procedimentos_secundarios.select_related("sigtap")]
        self.assertNotIn(self.sig_cirurgia.code, codigos)

    def test_surgery_without_sigtap_is_simply_ignored(self):
        """Cirurgia só com TUSS (paciente de convênio) não polui a AIH."""
        case = self._case()
        SurgicalProcedure.objects.create(case=case, tuss_code=self.tuss, quantity=1)

        aih = generate_aih_for_admission(
            self.admission, self.competencia, procedimento_principal=self.sig_principal
        )
        self.assertEqual(aih.procedimentos_secundarios.count(), 0)

    # ── apoio à codificação ───────────────────────────────────────────────────

    def test_candidates_expose_surgery_sigtap_for_the_coder(self):
        """Quem codifica precisa VER o que a cirurgia registrou para escolher o
        principal. O sistema oferece, não decide."""
        case = self._case()
        SurgicalProcedure.objects.create(
            case=case, tuss_code=self.tuss, sigtap=self.sig_cirurgia, quantity=1
        )

        candidatos = sigtap_candidates_for_admission(self.admission)

        codigos = {c.code for c in candidatos}
        self.assertIn("0407020055", codigos)

    def test_candidates_empty_without_surgery(self):
        self.assertEqual(list(sigtap_candidates_for_admission(self.admission)), [])

    def test_candidates_refuses_admission_without_encounter(self):
        sem_enc = Admission.objects.create(
            patient=self.patient,
            admitting_professional=self.prof,
            attending_professional=self.prof,
            admission_datetime=timezone.now() - datetime.timedelta(days=1),
            status=Admission.Status.ADMITTED,
        )
        with self.assertRaises(ValidationError):
            sigtap_candidates_for_admission(sem_enc)
