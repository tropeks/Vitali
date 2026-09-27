"""Ordem 030 — leitura pela porta FHIR deixa trilha.

As 22 views FHIR de leitura são `APIView` pura, sem `queryset`: a guarda de
cobertura não as enumerava e o módulo não gravava auditoria nenhuma. O
prontuário saía do sistema pela porta de interoperabilidade sem rastro (Res. CFM
1.821/2007; LGPD art. 37).

Pelo caminho real — APIClient → roteador → view —, com o mesmo contrato da
trilha do resto do sistema: detalhe grava `view_record` com o id lido; busca
grava `view_record_list` com o alvo em `resource_id` (o que `/audit-trail/`
expõe) e os critérios em `new_data`.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from rest_framework.test import APIClient

from apps.core.models import AuditLog, FeatureFlag, Role, User
from apps.emr.models import Allergy, Encounter, Patient, Professional, VitalSigns
from apps.fhir.models import SmartClient
from apps.fhir.services import smart
from apps.fhir.services.patient_mapper import SYSTEM_CPF
from apps.test_utils import TenantTestCase

BASE = "/api/v1/fhir"


class TrilhaDeLeituraFHIRTests(TenantTestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant, module_key="fhir", defaults={"is_enabled": True}
        )
        role, _ = Role.objects.get_or_create(
            name="fhir_trilha", defaults={"permissions": ["fhir.read"]}
        )
        self.user = User.objects.create_user(
            email="fhir_trilha@test.com", password="pw", role=role, full_name="Leitor FHIR"
        )
        self.client.force_authenticate(user=self.user)
        self.ana = Patient.objects.create(
            full_name="Ana Trilha", cpf="12345678909", birth_date=date(1985, 7, 14), gender="F"
        )
        self.bruno = Patient.objects.create(
            full_name="Bruno Trilha", cpf="98765432100", birth_date=date(1990, 3, 1), gender="M"
        )
        Allergy.objects.create(patient=self.ana, substance="Penicilina", status="active")
        Allergy.objects.create(patient=self.bruno, substance="Dipirona", status="active")

    def _trilha(self, action: str, resource_type: str):
        return AuditLog.objects.filter(action=action, resource_type=resource_type)

    def test_ler_um_paciente_deixa_trilha(self):
        resp = self.client.get(f"{BASE}/Patient/{self.ana.pk}/")
        assert resp.status_code == 200, resp.content

        log = self._trilha("view_record", "Patient").get()
        assert log.resource_id == str(self.ana.pk)
        assert log.user == self.user

    def test_paciente_inexistente_nao_deixa_trilha(self):
        resp = self.client.get(f"{BASE}/Patient/00000000-0000-4000-8000-000000000000/")
        assert resp.status_code == 404
        assert not AuditLog.objects.filter(action__startswith="view_record").exists()

    def test_buscar_paciente_por_cpf_registra_o_criterio(self):
        resp = self.client.get(f"{BASE}/Patient/", {"identifier": f"{SYSTEM_CPF}|12345678909"})
        assert resp.status_code == 200, resp.content

        log = self._trilha("view_record_list", "Patient").get()
        assert log.new_data == {"identifier": f"{SYSTEM_CPF}|12345678909"}

    def test_buscar_alergias_de_um_paciente_aponta_o_paciente(self):
        """`?patient=Patient/<uuid>` — o alvo vai limpo para `resource_id`, para
        o `/audit-trail/?patient=<uuid>` achar a leitura."""
        resp = self.client.get(f"{BASE}/AllergyIntolerance/", {"patient": f"Patient/{self.ana.pk}"})
        assert resp.status_code == 200, resp.content

        log = self._trilha("view_record_list", "AllergyIntolerance").get()
        assert log.resource_id == str(self.ana.pk)
        assert log.new_data == {"patient": f"Patient/{self.ana.pk}"}

    def test_busca_sem_criterio_tambem_deixa_trilha(self):
        """Varrer as alergias da clínica inteira é MAIS exposição que ler as de
        um paciente, não menos."""
        resp = self.client.get(f"{BASE}/AllergyIntolerance/")
        assert resp.status_code == 200, resp.content

        log = self._trilha("view_record_list", "AllergyIntolerance").get()
        assert log.resource_id == ""
        assert log.new_data == {}

    def test_token_smart_confinado_aponta_o_paciente_do_contexto(self):
        """Com token `patient/*.read`, a busca sem `?patient=` já está confinada
        ao paciente do contexto — e é ele que a trilha registra como alvo."""
        SmartClient.objects.create(
            client_id="trilha-app",
            client_name="Trilha SPA",
            is_confidential=False,
            redirect_uris="https://app.example.org/callback",
            scopes="openid launch/patient patient/*.read",
        )
        token = smart.mint_access_token(
            self.user, scope="launch/patient patient/*.read", patient_id=str(self.ana.pk)
        )
        client = APIClient()
        client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        resp = client.get(f"{BASE}/AllergyIntolerance/")
        assert resp.status_code == 200, resp.content

        log = self._trilha("view_record_list", "AllergyIntolerance").get()
        assert log.resource_id == str(self.ana.pk)

    def test_ler_uma_observacao_deixa_trilha_com_o_id_composto(self):
        md = User.objects.create_user(email="md_trilha@test.com", password="pw")
        professional = Professional.objects.create(
            user=md, council_type="CRM", council_number="700300", council_state="SP"
        )
        encounter = Encounter.objects.create(
            patient=self.ana,
            professional=professional,
            status="signed",
            encounter_date=datetime(2026, 5, 19, 9, 0, tzinfo=UTC),
        )
        VitalSigns.objects.create(encounter=encounter, weight_kg=70, heart_rate=72)
        observation_id = f"{encounter.pk}_29463-7"

        resp = self.client.get(f"{BASE}/Observation/{observation_id}/")
        assert resp.status_code == 200, resp.content

        log = self._trilha("view_record", "Observation").get()
        assert log.resource_id == observation_id
