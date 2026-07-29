"""
AI2 — Bridge Admission → AIH (faturamento SUS de internação).
=============================================================
Espelha ``test_aih.py`` (AI1) e ``test_surgery_billing.py`` (ponte clínica →
faturamento). Cobre o serviço ``generate_aih_for_admission`` + o endpoint
``from-admission`` (tudo local, sem rede):

  * Geração a partir de uma internação com alta, com encounter contendo 1 SIGTAP
    principal + 1 secundário → AIH valorada SH+SP, secundário criado, caráter/
    motivo/datas mapeados.
  * Idempotência (2ª chamada devolve a mesma AIH).
  * Pré-condições (sem alta / sem principal) → ValidationError.
  * Mapeamentos de caráter e motivo.
  * Número AIH provisório (formato YYYYMM+seq).
  * Endpoint ``from-admission`` (gating sus.write, 201, ValidationError → 400).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from django.core.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.billing.services.aih_billing import generate_aih_for_admission
from apps.billing.sus_models import AihAutorizacao, AihProcedimentoSecundario, SusCompetencia
from apps.core.models import CBOCode, Role, TUSSCode, User
from apps.core.sigtap_catalog_models import SIGTAPProcedure
from apps.emr.adt_models import Admission
from apps.emr.models import Encounter, EncounterProcedure, Patient, Professional
from apps.organization.models import Facility, LegalEntity
from apps.test_utils import TenantTestCase

BASE = "/api/v1/billing"


class AihBillingTestBase(TenantTestCase):
    def setUp(self):
        self.write_role = Role.objects.create(
            name="faturista_sus", permissions=["sus.read", "sus.write"]
        )
        self.read_role = Role.objects.create(name="leitor_sus", permissions=["sus.read"])
        self.writer = User.objects.create_user(email="w@t.com", password="pw", role=self.write_role)
        self.reader = User.objects.create_user(email="r@t.com", password="pw", role=self.read_role)

        self.legal = LegalEntity.objects.create(code="LE1", name="Rede SUS")
        self.facility = Facility.objects.create(
            code="FAC1",
            name="Hospital Central",
            legal_entity=self.legal,
            legacy_cnes_text="1234567",
        )
        self.cbo = CBOCode.objects.create(code="225125", display="Médico clínico", family="2251")
        self.sigtap_princ = SIGTAPProcedure.objects.create(
            code="0303010010",
            display="Tratamento de pneumonia",
            instrumento_registro="aih",
            valor_sh=Decimal("300.00"),
            valor_sp=Decimal("120.00"),
        )
        self.sigtap_sec = SIGTAPProcedure.objects.create(
            code="0303010029",
            display="Procedimento secundário",
            instrumento_registro="aih",
            valor_sh=Decimal("50.00"),
            valor_sp=Decimal("10.00"),
        )
        self.prof = Professional.objects.create(
            user=self.writer,
            council_type="CRM",
            council_number="12345",
            council_state="SP",
            cbo=self.cbo,
            cns="700000000000001",
        )
        self.patient = Patient.objects.create(
            full_name="João Paciente",
            birth_date="1980-01-01",
            gender="M",
            cpf="52998224725",
            cns="700000000000009",
        )
        self.tuss = TUSSCode.objects.create(
            code="30731011", description="Proc TUSS", group="procedimento", version="2024-01"
        )

    def _competencia(self, competencia="2026-07", status="aberta"):
        return SusCompetencia.objects.create(
            establishment=self.facility,
            competencia=competencia,
            status=status,
            created_by=self.writer,
        )

    def _encounter_with_procs(self, *, principal=True, secundario=True):
        enc = Encounter.objects.create(patient=self.patient, professional=self.prof)
        if principal:
            EncounterProcedure.objects.create(
                encounter=enc, tuss_code=self.tuss, sigtap=self.sigtap_princ, quantity=Decimal("1")
            )
        if secundario:
            EncounterProcedure.objects.create(
                encounter=enc, tuss_code=self.tuss, sigtap=self.sigtap_sec, quantity=Decimal("1")
            )
        return enc

    def _admission(
        self,
        *,
        status=Admission.Status.DISCHARGED,
        source=Admission.AdmissionSource.EMERGENCIA,
        disposition=Admission.Disposition.ALTA_MELHORADA,
        encounter=None,
        discharge=True,
    ):
        return Admission.objects.create(
            patient=self.patient,
            admitting_professional=self.prof,
            attending_professional=self.prof,
            encounter=encounter,
            admission_source=source,
            admission_datetime=datetime(2026, 7, 1, 8, 0, tzinfo=UTC),
            actual_discharge_datetime=(
                datetime(2026, 7, 5, 10, 0, tzinfo=UTC) if discharge else None
            ),
            disposition=disposition,
            status=status,
        )

    def _client(self, user):
        c = APIClient()
        c.defaults["SERVER_NAME"] = self.__class__.domain.domain
        c.force_authenticate(user)
        return c


# ─── Serviço ──────────────────────────────────────────────────────────────────


class TestGenerateAihForAdmission(AihBillingTestBase):
    def test_discharged_admission_generates_valued_aih_with_secondary(self):
        comp = self._competencia()
        enc = self._encounter_with_procs()
        adm = self._admission(encounter=enc)

        aih = generate_aih_for_admission(adm, comp, procedimento_principal=self.sigtap_princ)

        self.assertEqual(aih.admission_id, adm.id)
        self.assertEqual(aih.competencia_id, comp.id)
        self.assertEqual(aih.patient_id, self.patient.id)
        # snapshot do CNS do paciente
        self.assertEqual(aih.cns, "700000000000009")
        self.assertEqual(aih.professional_responsavel_id, self.prof.id)
        # datas vindas da internação
        self.assertEqual(str(aih.data_internacao), "2026-07-01")
        self.assertEqual(str(aih.data_saida), "2026-07-05")
        # EMERGENCIA → URGENCIA ; ALTA_MELHORADA → ALTA_MELHORADO
        self.assertEqual(aih.carater_internacao, AihAutorizacao.CaraterInternacao.URGENCIA)
        self.assertEqual(aih.motivo_saida, AihAutorizacao.MotivoSaida.ALTA_MELHORADO)
        # 1 secundário auto-puxado do encounter (o principal é excluído)
        secs = list(aih.procedimentos_secundarios.all())
        self.assertEqual(len(secs), 1)
        self.assertEqual(secs[0].sigtap_id, self.sigtap_sec.id)
        # secundário: (50+10)×1 = 60 ; header: principal(300+120) + 60 = 480
        self.assertEqual(secs[0].valor, Decimal("60.00"))
        self.assertEqual(aih.valor, Decimal("480.00"))

    def test_idempotent_returns_same_aih(self):
        comp = self._competencia()
        enc = self._encounter_with_procs()
        adm = self._admission(encounter=enc)
        first = generate_aih_for_admission(adm, comp, procedimento_principal=self.sigtap_princ)
        second = generate_aih_for_admission(adm, comp, procedimento_principal=self.sigtap_princ)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(AihAutorizacao.objects.filter(admission=adm).count(), 1)
        # não duplicou secundários
        self.assertEqual(AihProcedimentoSecundario.objects.filter(aih=first).count(), 1)

    def test_admitted_admission_raises(self):
        comp = self._competencia()
        adm = self._admission(status=Admission.Status.ADMITTED, discharge=False)
        with self.assertRaises(ValidationError):
            generate_aih_for_admission(adm, comp, procedimento_principal=self.sigtap_princ)

    def test_missing_principal_raises(self):
        comp = self._competencia()
        adm = self._admission()
        with self.assertRaises(ValidationError):
            generate_aih_for_admission(adm, comp, procedimento_principal=None)

    def test_carater_urgencia_and_motivo_obito_mapping(self):
        comp = self._competencia()
        adm = self._admission(
            source=Admission.AdmissionSource.EMERGENCIA,
            disposition=Admission.Disposition.OBITO,
        )
        aih = generate_aih_for_admission(adm, comp, procedimento_principal=self.sigtap_princ)
        self.assertEqual(aih.carater_internacao, AihAutorizacao.CaraterInternacao.URGENCIA)
        self.assertEqual(aih.motivo_saida, AihAutorizacao.MotivoSaida.OBITO)

    def test_carater_eletivo_from_ambulatorio(self):
        comp = self._competencia()
        adm = self._admission(
            source=Admission.AdmissionSource.AMBULATORIO,
            disposition=Admission.Disposition.ALTA_A_PEDIDO,
        )
        aih = generate_aih_for_admission(adm, comp, procedimento_principal=self.sigtap_princ)
        self.assertEqual(aih.carater_internacao, AihAutorizacao.CaraterInternacao.ELETIVO)
        self.assertEqual(aih.motivo_saida, AihAutorizacao.MotivoSaida.ALTA_MELHORADO)

    def test_provisional_numero_aih_format(self):
        comp = self._competencia()
        adm = self._admission()
        aih = generate_aih_for_admission(adm, comp, procedimento_principal=self.sigtap_princ)
        # YYYYMM + 7 dígitos de sequência
        self.assertEqual(len(aih.numero_aih), 13)
        self.assertTrue(aih.numero_aih.isdigit())
        self.assertEqual(aih.numero_aih[6:], "0000001")

    def test_explicit_numero_aih_is_used(self):
        comp = self._competencia()
        adm = self._admission()
        aih = generate_aih_for_admission(
            adm, comp, procedimento_principal=self.sigtap_princ, numero_aih="9999999999999"
        )
        self.assertEqual(aih.numero_aih, "9999999999999")

    def test_no_encounter_no_secondaries(self):
        comp = self._competencia()
        adm = self._admission(encounter=None)
        aih = generate_aih_for_admission(adm, comp, procedimento_principal=self.sigtap_princ)
        self.assertEqual(aih.procedimentos_secundarios.count(), 0)
        # só o principal (300+120)
        self.assertEqual(aih.valor, Decimal("420.00"))

    def test_explicit_secundarios_override_encounter(self):
        comp = self._competencia()
        enc = self._encounter_with_procs()
        adm = self._admission(encounter=enc)
        aih = generate_aih_for_admission(
            adm,
            comp,
            procedimento_principal=self.sigtap_princ,
            secundarios=[(self.sigtap_sec, 3)],
        )
        secs = list(aih.procedimentos_secundarios.all())
        self.assertEqual(len(secs), 1)
        self.assertEqual(secs[0].quantidade, 3)
        # (50+10)×3 = 180 ; header 420 + 180 = 600
        self.assertEqual(aih.valor, Decimal("600.00"))


# ─── Endpoint from-admission ──────────────────────────────────────────────────


class TestAihFromAdmissionEndpoint(AihBillingTestBase):
    def test_writer_generates_aih_from_admission(self):
        comp = self._competencia()
        enc = self._encounter_with_procs()
        adm = self._admission(encounter=enc)
        resp = self._client(self.writer).post(
            f"{BASE}/aih-autorizacoes/from-admission/",
            {
                "admission_id": str(adm.id),
                "competencia_id": comp.id,
                "procedimento_principal_id": "0303010010",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.data["admission"], adm.id)
        self.assertEqual(resp.data["valor"], "480.00")
        self.assertEqual(AihAutorizacao.objects.filter(admission=adm).count(), 1)

    def test_reader_forbidden(self):
        comp = self._competencia()
        adm = self._admission()
        resp = self._client(self.reader).post(
            f"{BASE}/aih-autorizacoes/from-admission/",
            {
                "admission_id": str(adm.id),
                "competencia_id": comp.id,
                "procedimento_principal_id": "0303010010",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_admitted_admission_returns_400(self):
        comp = self._competencia()
        adm = self._admission(status=Admission.Status.ADMITTED, discharge=False)
        resp = self._client(self.writer).post(
            f"{BASE}/aih-autorizacoes/from-admission/",
            {
                "admission_id": str(adm.id),
                "competencia_id": comp.id,
                "procedimento_principal_id": "0303010010",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.content)

    def test_idempotent_endpoint(self):
        comp = self._competencia()
        adm = self._admission()
        c = self._client(self.writer)
        payload = {
            "admission_id": str(adm.id),
            "competencia_id": comp.id,
            "procedimento_principal_id": "0303010010",
        }
        r1 = c.post(f"{BASE}/aih-autorizacoes/from-admission/", payload, format="json")
        r2 = c.post(f"{BASE}/aih-autorizacoes/from-admission/", payload, format="json")
        self.assertEqual(r1.status_code, 201, r1.content)
        self.assertEqual(r2.data["id"], r1.data["id"])
        self.assertEqual(AihAutorizacao.objects.filter(admission=adm).count(), 1)
