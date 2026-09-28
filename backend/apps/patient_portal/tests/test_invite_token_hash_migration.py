"""Ordem 033 — a migration 0004 no caminho real: um convite enviado ANTES dela
continua ativável DEPOIS dela.

A função de dados já tem teste isolado (``test_invite_token_hash.py``). Isto
aqui roda as operações da própria migration contra a tabela de verdade, no
schema do tenant de teste: volta a tabela fisicamente ao formato anterior
(coluna ``invite_token`` em claro, hash anulável), grava um convite pelo model
histórico, aplica RunPython + AlterField + RemoveField para frente e ativa o
convite pela API com o token antigo. Tudo dentro da transação do teste (DDL é
transacional no Postgres), desfeito no fim.

Reverter a 0004 pelo ``migrate`` recusa (``IrreversibleError``), por isso o
"antes" é montado com ``database_backwards`` das duas últimas operações, que
só mexem no schema — não com a reversão da RunPython.
"""

from __future__ import annotations

from datetime import date

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


def _estados(loader: MigrationLoader):
    """Estado do projeto antes da 0004 e depois de cada operação dela."""
    estados = [loader.project_state(ANTERIOR)]
    for op in loader.get_migration(*ALVO).operations:
        seguinte = estados[-1].clone()
        op.state_forwards(APP, seguinte)
        estados.append(seguinte)
    return estados


class ConviteAnteriorSobreviveAMigrationTests(TenantTestCase):
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

    def test_convite_gravado_em_claro_ativa_depois_da_migration(self):
        loader = MigrationLoader(connection)
        ops = loader.get_migration(*ALVO).operations
        add, run_python, alter, remove = ops
        estados = _estados(loader)

        with connection.cursor() as cur:
            # FK do Django é DEFERRABLE: com gatilho pendente, o Postgres
            # recusa ALTER TABLE na mesma transação.
            cur.execute("SET CONSTRAINTS ALL IMMEDIATE")
        with connection.schema_editor(atomic=False) as editor:
            remove.database_backwards(APP, editor, estados[4], estados[3])
            alter.database_backwards(APP, editor, estados[3], estados[2])

        Historico = estados[1].apps.get_model(APP, "PatientPortalAccess")
        Historico.objects.create(
            user_id=self.user.pk,
            patient_id=self.patient.pk,
            status="invited",
            invite_token="token-enviado-antes-da-033",
            invite_expires_at=date(2099, 1, 1),
        )

        with connection.schema_editor(atomic=False) as editor:
            run_python.database_forwards(APP, editor, estados[1], estados[2])
            alter.database_forwards(APP, editor, estados[2], estados[3])
            remove.database_forwards(APP, editor, estados[3], estados[4])

        access = PatientPortalAccess.find_by_invite_token("token-enviado-antes-da-033")
        self.assertEqual(access.invite_token_hash, hash_invite_token("token-enviado-antes-da-033"))

        client = APIClient()
        client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        client.force_authenticate(user=self.user)
        resp = client.post(
            "/api/v1/portal/access/activate/",
            {"invite_token": "token-enviado-antes-da-033"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data["status"], "active")
