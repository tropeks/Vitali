"""
AI1 — AIH (Autorização de Internação Hospitalar / SISAIH), modelo + API.
=======================================================================
Espelha ``test_sus_remessa.py`` (APAC), adaptando à internação. Cobre (tudo
local, sem rede):

  * :class:`AihAutorizacao` — modelo + ``numero_aih`` único; UniqueConstraint
    parcial (uma AIH por internação); procedimentos secundários com ``valor``
    computado no save (SH+SP × quantidade).
  * Cross-schema SIGTAP delete-protection para AIH (principal + secundário).
  * Endpoints AIH: CRUD gated sus.read/write (``?competencia=`` / ``?aih=``).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.db.models.deletion import ProtectedError
from rest_framework.test import APIClient

from apps.billing.sus_models import (
    AihAutorizacao,
    AihProcedimentoSecundario,
    SusCompetencia,
)
from apps.core.models import CBOCode, Role, User
from apps.core.sigtap_catalog_models import SIGTAPProcedure
from apps.emr.adt_models import Admission
from apps.emr.models import Patient, Professional
from apps.organization.models import Facility, LegalEntity
from apps.test_utils import TenantTestCase

BASE = "/api/v1/billing"


class AihTestBase(TenantTestCase):
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
        # Procedimento hospitalar principal — valorado no eixo SH+SP.
        self.sigtap_aih = SIGTAPProcedure.objects.create(
            code="0303010010",
            display="Tratamento de pneumonia",
            instrumento_registro="aih",
            complexidade="media",
            valor_sh=Decimal("300.00"),
            valor_sp=Decimal("120.00"),
        )
        self.sigtap_sec = SIGTAPProcedure.objects.create(
            code="0303010029",
            display="Procedimento hospitalar secundário",
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

    def _client(self, user):
        c = APIClient()
        c.defaults["SERVER_NAME"] = self.__class__.domain.domain
        c.force_authenticate(user)
        return c

    @staticmethod
    def _rows(resp):
        return resp.data["results"] if "results" in resp.data else resp.data

    def _competencia(self, competencia="2026-07", status="aberta"):
        return SusCompetencia.objects.create(
            establishment=self.facility,
            competencia=competencia,
            status=status,
            created_by=self.writer,
        )

    def _admission(self):
        return Admission.objects.create(
            patient=self.patient,
            admitting_professional=self.prof,
            attending_professional=self.prof,
        )

    def _aih(self, comp, numero="1234567890123", admission=None):
        return AihAutorizacao.objects.create(
            competencia=comp,
            numero_aih=numero,
            admission=admission,
            procedimento_principal=self.sigtap_aih,
            cid_principal="J189",
            patient=self.patient,
            cns="700000000000009",
            professional_solicitante=self.prof,
            professional_responsavel=self.prof,
            data_internacao=date(2026, 7, 1),
            data_saida=date(2026, 7, 5),
            carater_internacao=AihAutorizacao.CaraterInternacao.URGENCIA,
            motivo_saida=AihAutorizacao.MotivoSaida.ALTA_MELHORADO,
            valor=Decimal("420.00"),
        )


# ─── AIH model ────────────────────────────────────────────────────────────────


class TestAihModel(AihTestBase):
    def test_create_aih_with_admission_and_secondary(self):
        comp = self._competencia()
        adm = self._admission()
        aih = self._aih(comp, admission=adm)
        sec = AihProcedimentoSecundario.objects.create(
            aih=aih, sigtap=self.sigtap_sec, quantidade=2
        )
        self.assertEqual(aih.competencia_id, comp.id)
        self.assertEqual(aih.admission_id, adm.id)
        self.assertEqual(aih.carater_internacao, "02")
        self.assertEqual(list(comp.aihs.all()), [aih])
        self.assertEqual(list(adm.aihs.all()), [aih])
        self.assertEqual(list(aih.procedimentos_secundarios.all()), [sec])

    def test_secundario_valor_computed_sh_plus_sp_times_qtd(self):
        comp = self._competencia()
        aih = self._aih(comp)
        sec = AihProcedimentoSecundario.objects.create(
            aih=aih, sigtap=self.sigtap_sec, quantidade=3
        )
        # (50.00 + 10.00) × 3 = 180.00 — AIH usa SH+SP (não SA+SP).
        self.assertEqual(sec.valor, Decimal("180.00"))

    def test_numero_aih_unique(self):
        from django.db import IntegrityError, transaction

        comp = self._competencia()
        self._aih(comp, numero="9999999999999")
        with transaction.atomic(), self.assertRaises(IntegrityError):
            self._aih(comp, numero="9999999999999")

    def test_one_aih_per_admission(self):
        from django.db import IntegrityError, transaction

        comp = self._competencia()
        adm = self._admission()
        self._aih(comp, numero="1111111111111", admission=adm)
        with transaction.atomic(), self.assertRaises(IntegrityError):
            self._aih(comp, numero="2222222222222", admission=adm)

    def test_multiple_aih_with_null_admission_allowed(self):
        # A UniqueConstraint é parcial (admission__isnull=False), então várias
        # AIHs sem internação âncora coexistem.
        comp = self._competencia()
        self._aih(comp, numero="1111111111111", admission=None)
        self._aih(comp, numero="2222222222222", admission=None)
        self.assertEqual(AihAutorizacao.objects.filter(admission__isnull=True).count(), 2)


# ─── AIH cross-schema SIGTAP delete-protection ────────────────────────────────


class TestAihSigtapProtection(AihTestBase):
    def test_principal_sigtap_cannot_be_deleted(self):
        comp = self._competencia()
        self._aih(comp)
        with self.assertRaises(ProtectedError):
            self.sigtap_aih.delete()

    def test_secondary_sigtap_cannot_be_deleted(self):
        comp = self._competencia()
        aih = self._aih(comp)
        AihProcedimentoSecundario.objects.create(aih=aih, sigtap=self.sigtap_sec, quantidade=1)
        with self.assertRaises(ProtectedError):
            self.sigtap_sec.delete()


# ─── AIH endpoints ────────────────────────────────────────────────────────────


class TestAihEndpoints(AihTestBase):
    def test_writer_creates_aih(self):
        comp = self._competencia()
        adm = self._admission()
        resp = self._client(self.writer).post(
            f"{BASE}/aih-autorizacoes/",
            {
                "competencia": comp.id,
                "numero_aih": "1111111111111",
                "admission": str(adm.id),
                "procedimento_principal": self.sigtap_aih.id,
                "cid_principal": "J189",
                "patient": self.patient.id,
                "data_internacao": "2026-07-01",
                "data_saida": "2026-07-05",
                "carater_internacao": "02",
                "motivo_saida": "alta_melhorado",
                "valor": "420.00",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        aih = AihAutorizacao.objects.get(numero_aih="1111111111111")
        self.assertEqual(aih.created_by_id, self.writer.id)
        self.assertEqual(aih.admission_id, adm.id)
        # cns snapshotted from patient when omitted
        self.assertEqual(aih.cns, "700000000000009")

    def test_reader_cannot_create_aih(self):
        comp = self._competencia()
        resp = self._client(self.reader).post(
            f"{BASE}/aih-autorizacoes/",
            {
                "competencia": comp.id,
                "numero_aih": "2222222222222",
                "procedimento_principal": self.sigtap_aih.id,
                "patient": self.patient.id,
                "data_internacao": "2026-07-01",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_list_filters_by_competencia(self):
        comp = self._competencia("2026-07")
        comp2 = self._competencia("2026-08")
        self._aih(comp, numero="3333333333333")
        self._aih(comp2, numero="4444444444444")
        resp = self._client(self.reader).get(f"{BASE}/aih-autorizacoes/?competencia={comp.id}")
        self.assertEqual(resp.status_code, 200)
        rows = self._rows(resp)
        self.assertEqual([r["numero_aih"] for r in rows], ["3333333333333"])

    def test_secundario_create_computes_valor_and_filters_by_aih(self):
        comp = self._competencia()
        aih = self._aih(comp)
        resp = self._client(self.writer).post(
            f"{BASE}/aih-secundarios/",
            {"aih": aih.id, "sigtap": self.sigtap_sec.id, "quantidade": 2},
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        sec = AihProcedimentoSecundario.objects.get(aih=aih)
        # (50.00 + 10.00) × 2 = 120.00
        self.assertEqual(sec.valor, Decimal("120.00"))
        resp = self._client(self.reader).get(f"{BASE}/aih-secundarios/?aih={aih.id}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(self._rows(resp)), 1)
