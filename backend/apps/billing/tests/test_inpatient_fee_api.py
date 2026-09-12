"""Onda2 2.1/2.2 — API de lançamento de taxas e gases medicinais de internação.

Fecha o gap descrito na tarefa: ``record_inpatient_fee`` (B6) existia sem
serializer/viewset/rota — a enfermagem não tinha como lançar uma taxa e a
receita não saía do papel. Este arquivo cobre a camada HTTP nova (POST/GET
`/api/v1/billing/inpatient-fees/`); a regra de negócio em si (tabela TUSS,
quantidade, internação ativa) já é coberta em profundidade por
``test_inpatient_fees.py`` e não é reduplicada aqui — só o suficiente para
confirmar que os erros do serviço atravessam a view como 400, não 500.
"""

import datetime
from decimal import Decimal

from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from apps.billing.inpatient_models import InpatientFee
from apps.billing.models import InsuranceProvider, PriceTable, PriceTableItem
from apps.billing.services.inpatient_billing import generate_internacao_guide_for_admission
from apps.core.models import BedType, FeatureFlag, Role, TUSSCode, User
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


class InpatientFeeApiTestCase(TenantTestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain

        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant, module_key="billing", defaults={"is_enabled": True}
        )

        self.faturista_role = Role.objects.create(
            name="faturista_fee_api",
            permissions=["billing.read", "billing.write"],
            is_system=True,
        )
        self.enfermeiro_role = Role.objects.create(
            name="enfermeiro_fee_api",
            permissions=["emr.read", "emr.write"],
            is_system=True,
        )
        # Só-leitura em ambos os domínios: não pode lançar taxa. Prova que o
        # gate exige WRITE, não mera visibilidade da conta ou do prontuário.
        self.leitor_role = Role.objects.create(
            name="leitor_fee_api",
            permissions=["billing.read", "emr.read"],
            is_system=True,
        )
        self.faturista = User.objects.create_user(
            email="fat.fee@test.com",
            full_name="Faturista Fee",
            password="Str0ng!Pass#2024",
            role=self.faturista_role,
        )
        self.enfermeiro = User.objects.create_user(
            email="enf.fee@test.com",
            full_name="Enfermeiro Fee",
            password="Str0ng!Pass#2024",
            role=self.enfermeiro_role,
        )
        self.leitor = User.objects.create_user(
            email="leitor.fee@test.com",
            full_name="Leitor Fee",
            password="Str0ng!Pass#2024",
            role=self.leitor_role,
        )
        prof_user = User.objects.create_user(
            email="medico.fee@test.com",
            full_name="Dr. Fee API",
            password="Str0ng!Pass#2024",
            role=self.faturista_role,
        )
        self.prof = Professional.objects.create(
            user=prof_user, council_type="CRM", council_number="FA-1", council_state="SP"
        )
        self.patient = Patient.objects.create(
            full_name="Fee API Paciente", birth_date="1980-01-01", gender="M", cpf="52998224725"
        )
        legal = LegalEntity.objects.create(code="LEA1", name="Hospital Fee API")
        facility = Facility.objects.create(
            code="FACA1", name="Hospital Fee API", legal_entity=legal
        )
        bed_type = BedType.objects.create(
            code="75", display="UTI adulto API", category="Complementar"
        )
        unit = InpatientUnit.objects.create(facility=facility, name="Ala API", code="ALA-API")
        room = Room.objects.create(unit=unit, name="901")
        self.bed = Bed.objects.create(room=room, unit=unit, identifier="901-A", bed_type=bed_type)

        self.tuss_taxa = TUSSCode.objects.create(
            code="60027200",
            description="TAXA DE BOMBA DE INFUSAO, POR DIA",
            group="Diárias, taxas e gases medicinais",
            table_number="18",
            version="202607",
        )
        self.tuss_procedimento = TUSSCode.objects.create(
            code="10101099",
            description="Consulta em consultório (API)",
            group="Procedimentos e eventos em saúde",
            table_number="22",
            version="202607",
        )

        self.admission = Admission.objects.create(
            patient=self.patient,
            admitting_professional=self.prof,
            attending_professional=self.prof,
            current_bed=self.bed,
            admission_datetime=timezone.now() - datetime.timedelta(days=1),
            status=Admission.Status.ADMITTED,
        )

        self.fat_token = self._get_token("fat.fee@test.com")
        self.enf_token = self._get_token("enf.fee@test.com")
        self.leitor_token = self._get_token("leitor.fee@test.com")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _get_token(self, email):
        resp = self.client.post(
            "/api/v1/auth/login",
            {"email": email, "password": "Str0ng!Pass#2024"},
            format="json",
        )
        return resp.json().get("access")

    def _auth(self, token):
        c = APIClient()
        c.defaults["SERVER_NAME"] = self.__class__.domain.domain
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        return c

    def _payload(self, **overrides):
        payload = {
            "admission": str(self.admission.pk),
            "tuss_code": self.tuss_taxa.pk,
            "quantity": "1",
            "unit": "dia",
        }
        payload.update(overrides)
        return payload

    # ── criação → aparece na conta ──────────────────────────────────────────────

    def test_create_fee_via_api_and_it_reaches_the_account(self):
        """POST cria InpatientFee, e a taxa lançada entra como item quando a
        guia de internação é montada — é o que "aparecer na conta" significa."""
        client = self._auth(self.fat_token)
        resp = client.post("/api/v1/billing/inpatient-fees/", self._payload(), format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()
        self.assertEqual(InpatientFee.objects.count(), 1)
        fee = InpatientFee.objects.get()
        self.assertEqual(body["id"], str(fee.pk))
        self.assertEqual(Decimal(str(body["quantity"])), Decimal("1"))
        self.assertIn(self.tuss_taxa.code, body["tuss_code_display"])
        self.assertEqual(body["unit"], "dia")

        encounter = Encounter.objects.create(
            patient=self.patient, professional=self.prof, encounter_type="inpatient"
        )
        self.admission.encounter = encounter
        self.admission.save()
        provider = InsuranceProvider.objects.create(name="Operadora API", ans_code="99200")
        PatientInsurance.objects.create(
            patient=self.patient,
            provider_ans_code="99200",
            provider_name="Operadora API",
            card_number="C-API",
            is_active=True,
        )
        table = PriceTable.objects.create(
            provider=provider, name="Tab API", valid_from=timezone.now().date()
        )
        PriceTableItem.objects.create(
            table=table, tuss_code=self.tuss_taxa, negotiated_value=Decimal("42.00")
        )

        guide = generate_internacao_guide_for_admission(self.admission)
        item = guide.items.get(tuss_code=self.tuss_taxa)
        self.assertEqual(item.quantity, Decimal("1"))
        self.assertEqual(item.total_value, Decimal("42.00"))

    def test_categoria_gas_medicinal_atravessa_ate_o_item_faturado(self):
        """A distinção taxa × gás medicinal é capturada por quem LANÇA, e chega
        até a categoria do item na guia.

        Existe porque nenhuma inferência resolveria: ct_guiaValorTotal tem
        valorTaxasAlugueis e valorGasesMedicinais como campos separados, mas as
        duas coisas moram na tabela 18 do TUSS (~1.590 taxas e ~890 gases). Nem
        table_number nem TUSSCode.group separam — classificar por eles erraria
        em ~25% do volume, e é dinheiro.
        """
        client = self._auth(self.fat_token)

        resp = client.post(
            "/api/v1/billing/inpatient-fees/",
            self._payload(category=InpatientFee.Category.GAS_MEDICINAL),
            format="json",
        )

        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.json()["category"], "gas_medicinal")

        encounter = Encounter.objects.create(
            patient=self.patient, professional=self.prof, encounter_type="inpatient"
        )
        self.admission.encounter = encounter
        self.admission.save()
        provider = InsuranceProvider.objects.create(name="Operadora Gás", ans_code="99201")
        PatientInsurance.objects.create(
            patient=self.patient,
            provider_ans_code="99201",
            provider_name="Operadora Gás",
            card_number="C-GAS",
            is_active=True,
        )
        table = PriceTable.objects.create(
            provider=provider, name="Tab Gás", valid_from=timezone.now().date()
        )
        PriceTableItem.objects.create(
            table=table, tuss_code=self.tuss_taxa, negotiated_value=Decimal("42.00")
        )

        guide = generate_internacao_guide_for_admission(self.admission)
        item = guide.items.get(tuss_code=self.tuss_taxa)

        self.assertEqual(item.billing_category, "gases_medicinais")

    def test_taxa_sem_categoria_fica_sem_categoria_no_item(self):
        """Omitir é legítimo e NÃO vira um palpite: o item nasce sem categoria e
        a guia sai só com valorTotalGeral — nunca um breakdown que não fecha."""
        client = self._auth(self.fat_token)

        resp = client.post("/api/v1/billing/inpatient-fees/", self._payload(), format="json")

        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.json()["category"], "")

    def test_launching_same_fee_twice_does_not_duplicate(self):
        """A prova de 2.2: dois POSTs idênticos não geram duas linhas."""
        client = self._auth(self.fat_token)
        payload = self._payload(service_date=str(timezone.now().date()))
        r1 = client.post("/api/v1/billing/inpatient-fees/", payload, format="json")
        r2 = client.post("/api/v1/billing/inpatient-fees/", payload, format="json")
        self.assertEqual(r1.status_code, 201, r1.content)
        self.assertEqual(r2.status_code, 200, r2.content)  # idempotente: reaproveita
        self.assertEqual(r1.json()["id"], r2.json()["id"])
        self.assertEqual(InpatientFee.objects.count(), 1)

    def test_fee_with_different_quantity_same_day_is_not_treated_as_duplicate(self):
        """Duas administrações reais e distintas (durações diferentes) no mesmo
        dia continuam sendo dois lançamentos — a idempotência não pode comer
        receita legítima."""
        client = self._auth(self.fat_token)
        hoje = str(timezone.now().date())
        r1 = client.post(
            "/api/v1/billing/inpatient-fees/",
            self._payload(service_date=hoje, quantity="1"),
            format="json",
        )
        r2 = client.post(
            "/api/v1/billing/inpatient-fees/",
            self._payload(service_date=hoje, quantity="2"),
            format="json",
        )
        self.assertEqual(r1.status_code, 201, r1.content)
        self.assertEqual(r2.status_code, 201, r2.content)
        self.assertEqual(InpatientFee.objects.count(), 2)

    # ── validação → 400, nunca 500 ───────────────────────────────────────────

    def test_fee_on_inactive_admission_returns_400_not_500(self):
        self.admission.status = Admission.Status.DISCHARGED
        self.admission.actual_discharge_datetime = timezone.now()
        self.admission.save()
        client = self._auth(self.fat_token)
        resp = client.post("/api/v1/billing/inpatient-fees/", self._payload(), format="json")
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn("ativa", str(resp.json()))
        self.assertEqual(InpatientFee.objects.count(), 0)

    def test_fee_with_tuss_outside_table_18_returns_400_not_500(self):
        client = self._auth(self.fat_token)
        resp = client.post(
            "/api/v1/billing/inpatient-fees/",
            self._payload(tuss_code=self.tuss_procedimento.pk),
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn("18", str(resp.json()))
        self.assertEqual(InpatientFee.objects.count(), 0)

    def test_missing_required_field_returns_400_with_field_errors(self):
        """Corpo malformado (sem tuss_code) é 400 de validação de campo — um
        dict {"tuss_code": [...]}, formato diferente do erro de regra de
        negócio (lista simples) — ver CONTRATO DA API no relatório."""
        client = self._auth(self.fat_token)
        payload = self._payload()
        del payload["tuss_code"]
        resp = client.post("/api/v1/billing/inpatient-fees/", payload, format="json")
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn("tuss_code", resp.json())

    # ── permissão ────────────────────────────────────────────────────────────

    def test_enfermeiro_can_record_fee_with_emr_write(self):
        """Enfermagem lança taxa/gás com ``emr.write``, sem permissão de billing.

        Quem registra oxigênio ou incubadora está à beira do leito. Exigir
        ``billing.write`` manteria a receita trancada por autorização, agora que
        ela deixou de estar trancada por ausência de rota (Onda 2 / 2.1).
        """
        client = self._auth(self.enf_token)
        resp = client.post("/api/v1/billing/inpatient-fees/", self._payload(), format="json")
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(InpatientFee.objects.count(), 1)
        self.assertEqual(InpatientFee.objects.get().created_by_id, self.enfermeiro.id)

    def test_read_only_role_cannot_record_fee(self):
        """``billing.read`` + ``emr.read`` não bastam: o gate exige WRITE."""
        client = self._auth(self.leitor_token)
        resp = client.post("/api/v1/billing/inpatient-fees/", self._payload(), format="json")
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(InpatientFee.objects.count(), 0)

    def test_unauthenticated_returns_401(self):
        resp = self.client.post("/api/v1/billing/inpatient-fees/", self._payload(), format="json")
        self.assertEqual(resp.status_code, 401)
