"""Ordem 033 — a migration 0004 no caminho real, nos dois sentidos.

A função de dados já tem teste isolado (``test_invite_token_hash.py``). Aqui as
operações da própria migration rodam contra a tabela de verdade, no schema do
tenant de teste, dentro da transação do teste (DDL é transacional no Postgres,
tudo se desfaz no fim):

* **para frente:** a tabela volta ao formato anterior (só a coluna em claro,
  NOT NULL), um convite é gravado pelo model da release anterior, a 0004 roda,
  e o convite ativa pela API com o token antigo;
* **a release anterior no schema novo** (a regra de docs/TENANT_MIGRATIONS.md):
  o model de antes grava no schema da 0004, e a release nova ativa esse convite;
* **para trás:** com um convite criado nesta fase (coluna em claro NULL), a
  0004 se desfaz sem tocar em dado, e o model de antes lê a linha.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from django.db import connection
from django.db.migrations.loader import MigrationLoader
from rest_framework.test import APIClient

from apps.core.models import FeatureFlag, Role, User
from apps.emr.models import Patient
from apps.patient_portal.models import PatientPortalAccess, hash_invite_token
from apps.test_utils import TenantTestCase

APP = "patient_portal"
ANTERIOR = (APP, "0003_portalpixpayment_portalpreconsultform_and_more")
ALVO = (APP, "0004_invite_token_hash")
TABELA = PatientPortalAccess._meta.db_table


class MigrationNoCaminhoRealTests(TenantTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        loader = MigrationLoader(connection)
        cls.ops = loader.get_migration(*ALVO).operations
        # estados[i] = projeto antes da operação i da 0004; estados[-1] = depois dela.
        cls.estados = [loader.project_state(ANTERIOR)]
        for op in cls.ops:
            seguinte = cls.estados[-1].clone()
            op.state_forwards(APP, seguinte)
            cls.estados.append(seguinte)

    def setUp(self):
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant, module_key="patient_portal", defaults={"is_enabled": True}
        )
        role, _ = Role.objects.get_or_create(
            name="portal_mig033", defaults={"permissions": ["portal.self_access"]}
        )
        self.user = User.objects.create_user(
            email="mig033@test.com", password="pw", role=role, full_name="Mig"
        )
        self.patient = Patient.objects.create(
            full_name="Ana Mig", cpf="12345678909", birth_date=date(1985, 7, 14), gender="F"
        )
        with connection.cursor() as cur:
            # FK do Django é DEFERRABLE: com gatilho pendente, o Postgres recusa
            # ALTER TABLE na mesma transação.
            cur.execute("SET CONSTRAINTS ALL IMMEDIATE")

    def _modelo_anterior(self):
        return self.estados[0].apps.get_model(APP, "PatientPortalAccess")

    def _desfaz_0004(self):
        with connection.schema_editor(atomic=False) as editor:
            for i in reversed(range(len(self.ops))):
                self.ops[i].database_backwards(APP, editor, self.estados[i + 1], self.estados[i])

    def _aplica_0004(self):
        with connection.schema_editor(atomic=False) as editor:
            for i, op in enumerate(self.ops):
                op.database_forwards(APP, editor, self.estados[i], self.estados[i + 1])

    def _grava_como_antes(self, token: str):
        return self._modelo_anterior().objects.create(
            user_id=self.user.pk,
            patient_id=self.patient.pk,
            status="invited",
            invite_token=token,
            invite_expires_at=datetime(2099, 1, 1, tzinfo=UTC),
        )

    def _ativa(self, token: str):
        client = APIClient()
        client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        client.force_authenticate(user=self.user)
        return client.post(
            "/api/v1/portal/access/activate/", {"invite_token": token}, format="json"
        )

    def _colunas(self) -> set[str]:
        with connection.cursor() as cur:
            return {c.name for c in connection.introspection.get_table_description(cur, TABELA)}

    def test_convite_enviado_antes_ativa_depois_da_migration(self):
        self._desfaz_0004()
        self.assertNotIn("invite_token_hash", self._colunas())
        self._grava_como_antes("token-enviado-antes-da-033")

        self._aplica_0004()

        access = PatientPortalAccess.objects.get(user=self.user)
        self.assertEqual(access.invite_token_hash, hash_invite_token("token-enviado-antes-da-033"))
        resp = self._ativa("token-enviado-antes-da-033")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertIsNone(PatientPortalAccess.objects.get(pk=access.pk).invite_token_legado)

    def test_release_anterior_grava_no_schema_novo_e_a_nova_ativa(self):
        self._grava_como_antes("token-gravado-pela-release-anterior")

        resp = self._ativa("token-gravado-pela-release-anterior")
        self.assertEqual(resp.status_code, 200, resp.data)

    def test_desfazer_a_0004_nao_exige_tocar_em_dado(self):
        convite_desta_fase = PatientPortalAccess.objects.create(
            user=self.user, patient=self.patient
        )

        self._desfaz_0004()

        self.assertNotIn("invite_token_hash", self._colunas())
        relida = self._modelo_anterior().objects.get(pk=convite_desta_fase.pk)
        self.assertIsNone(relida.invite_token)
