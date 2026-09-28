"""Ordem 033 — o banco guarda só o hash do ``invite_token``.

A 031 tirou o token das respostas de leitura, mas ele continuava em texto claro
na tabela ``patient_portal_patientportalaccess``: quem lê o banco, um dump ou um
backup, tinha o link de ativação de todo convite em aberto. Agora convite novo
grava só o SHA-256 (o token tem 256 bits aleatórios, então um hash rápido basta:
não há dicionário a atacar). O token em claro existe só na instância que o
cunhou — é ela que a entrega e o 201 usam — e nunca volta do banco.

Fase 1 de 2 (docs/TENANT_MIGRATIONS.md): a coluna em claro fica, anulável, para
a release anterior continuar rodando contra o schema novo; a ordem 034 a derruba.
Os convites já enviados continuam valendo: a migration grava o hash de cada um.
"""

from __future__ import annotations

import hashlib
import importlib
import logging
from datetime import date
from unittest.mock import MagicMock, patch

from django.contrib.admin.sites import AdminSite
from django.db import connection
from django.test import RequestFactory, SimpleTestCase
from rest_framework.test import APIClient

from apps.core.models import FeatureFlag, Role, User
from apps.emr.models import Patient
from apps.patient_portal.admin import PatientPortalAccessAdmin
from apps.patient_portal.models import PatientPortalAccess
from apps.patient_portal.services.invite_delivery import (
    build_activation_url,
    deliver_portal_invite,
)
from apps.test_utils import TenantTestCase

ACCESS_URL = "/api/v1/portal/access/"
ACTIVATE_URL = "/api/v1/portal/access/activate/"
TABELA = PatientPortalAccess._meta.db_table
MIGRATION = "apps.patient_portal.migrations.0004_invite_token_hash"


def _sha256(texto: str) -> str:
    return hashlib.sha256(texto.encode()).hexdigest()


def _usuario(email: str, perms: list[str]) -> User:
    role, _ = Role.objects.get_or_create(name=f"r_{email}", defaults={"permissions": perms})
    return User.objects.create_user(email=email, password="pw", role=role, full_name=email)


class _Base(TenantTestCase):
    def setUp(self):
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key="patient_portal",
            defaults={"is_enabled": True},
        )
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        self.patient = Patient.objects.create(
            full_name="Ana Hash", cpf="12345678909", birth_date=date(1985, 7, 14), gender="F"
        )
        self.portal_user = _usuario("ana_hash@test.com", ["portal.self_access"])
        self.admin = _usuario("admin_hash@test.com", ["users.read", "users.write"])

    def _convite(self) -> PatientPortalAccess:
        return PatientPortalAccess.objects.create(user=self.portal_user, patient=self.patient)


class BancoGuardaSoOHashTests(_Base):
    def test_convite_novo_grava_null_na_coluna_em_claro(self):
        access = self._convite()
        with connection.cursor() as cur:
            cur.execute(
                f'SELECT invite_token, invite_token_hash FROM "{TABELA}" WHERE id = %s',
                [access.pk],
            )
            em_claro, digest = cur.fetchone()
        self.assertIsNone(em_claro)
        self.assertEqual(digest, _sha256(access.invite_token))

    def test_nenhuma_coluna_guarda_o_token_em_claro(self):
        access = self._convite()
        token = access.invite_token
        self.assertTrue(token)
        with connection.cursor() as cur:
            cur.execute(f'SELECT * FROM "{TABELA}" WHERE id = %s', [access.pk])
            linha = cur.fetchone()
        self.assertNotIn(token, [str(v) for v in linha])
        self.assertIn(_sha256(token), [str(v) for v in linha])

    def test_instancia_lida_do_banco_nao_tem_o_token(self):
        access = self._convite()
        relida = PatientPortalAccess.objects.get(pk=access.pk)
        self.assertIsNone(relida.invite_token)
        self.assertEqual(relida.invite_token_hash, _sha256(access.invite_token))

    def test_salvar_de_novo_nao_troca_o_hash(self):
        access = self._convite()
        antes = access.invite_token_hash
        access.activate()
        access.touch()
        self.assertEqual(PatientPortalAccess.objects.get(pk=access.pk).invite_token_hash, antes)


class AtivacaoPeloHashTests(_Base):
    def test_ativar_com_o_token_em_claro_funciona(self):
        access = self._convite()
        self.client.force_authenticate(user=self.portal_user)
        resp = self.client.post(ACTIVATE_URL, {"invite_token": access.invite_token}, format="json")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data["status"], "active")

    def test_ativar_com_o_proprio_hash_nao_funciona(self):
        """Quem copiou o banco tem o hash, não o token: o hash não ativa nada."""
        access = self._convite()
        self.client.force_authenticate(user=self.portal_user)
        resp = self.client.post(
            ACTIVATE_URL, {"invite_token": access.invite_token_hash}, format="json"
        )
        self.assertEqual(resp.status_code, 400)

    def test_201_devolve_o_token_cujo_hash_esta_no_banco(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.post(
            ACCESS_URL,
            {"user": self.portal_user.pk, "patient": str(self.patient.pk)},
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        token = resp.data["invite_token"]
        self.assertTrue(token)
        self.assertEqual(
            PatientPortalAccess.objects.get(pk=resp.data["id"]).invite_token_hash, _sha256(token)
        )


class ConviteDaReleaseAnteriorTests(_Base):
    """Linha gravada pela release anterior (token em claro, hash NULL) — o que
    acontece se o código voltar durante a fase 1 e depois avançar de novo."""

    def _convite_legado(self, token: str) -> PatientPortalAccess:
        access = self._convite()
        with connection.cursor() as cur:
            cur.execute(
                f'UPDATE "{TABELA}" SET invite_token = %s, invite_token_hash = NULL WHERE id = %s',
                [token, access.pk],
            )
        return access

    def test_ativa_pelo_token_ganha_o_hash_e_perde_o_claro(self):
        access = self._convite_legado("token-da-release-anterior")
        self.client.force_authenticate(user=self.portal_user)
        resp = self.client.post(
            ACTIVATE_URL, {"invite_token": "token-da-release-anterior"}, format="json"
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        relida = PatientPortalAccess.objects.get(pk=access.pk)
        self.assertEqual(relida.invite_token_hash, _sha256("token-da-release-anterior"))
        self.assertIsNone(relida.invite_token_legado)

    def test_hash_colado_nao_casa_com_o_claro_legado(self):
        self._convite_legado("token-legado-b")
        self.client.force_authenticate(user=self.portal_user)
        resp = self.client.post(
            ACTIVATE_URL, {"invite_token": _sha256("token-legado-b")}, format="json"
        )
        self.assertEqual(resp.status_code, 400)

    def test_revogar_apaga_o_claro_legado(self):
        access = self._convite_legado("token-legado-c")
        access.refresh_from_db()
        access.revoke()
        self.assertIsNone(PatientPortalAccess.objects.get(pk=access.pk).invite_token_legado)


class EntregaSoComOTokenCunhadoTests(_Base):
    def test_link_de_instancia_relida_recusa(self):
        """Sem o token em claro, montar ``?token=None`` seria um link quebrado
        mandado ao paciente, calado. Recusa por nome."""
        relida = PatientPortalAccess.objects.get(pk=self._convite().pk)
        with self.assertRaisesRegex(ValueError, "invite_token"):
            build_activation_url(relida)

    def test_entrega_de_instancia_relida_nao_envia_e_avisa(self):
        relida = PatientPortalAccess.objects.get(pk=self._convite().pk)
        with self.assertLogs("apps.patient_portal.services.invite_delivery", logging.ERROR):
            self.assertEqual(deliver_portal_invite(relida), [])


class AdminTests(_Base):
    def _admin(self):
        return PatientPortalAccessAdmin(PatientPortalAccess, AdminSite())

    def test_admin_nao_busca_nem_mostra_o_token(self):
        admin = self._admin()
        self.assertNotIn("invite_token", admin.search_fields)
        self.assertNotIn("invite_token", admin.readonly_fields)

    def test_convite_nao_entregue_mostra_o_link_uma_vez_no_admin(self):
        """O admin não tem mais o token para mostrar depois. Se a entrega
        falhar, o link sai uma vez, na mensagem da criação — como o 201."""
        admin = self._admin()
        request = RequestFactory().post("/admin/")
        request.user = self.admin
        obj = PatientPortalAccess(user=self.portal_user, patient=self.patient)
        with (
            patch("apps.patient_portal.admin.deliver_portal_invite", return_value=[]),
            patch.object(admin, "message_user") as message_user,
        ):
            admin.save_model(request, obj, form=MagicMock(), change=False)
        texto = message_user.call_args.args[1]
        self.assertIn(obj.invite_token, texto)

    def test_convite_entregue_nao_mostra_o_link(self):
        admin = self._admin()
        request = RequestFactory().post("/admin/")
        request.user = self.admin
        obj = PatientPortalAccess(user=self.portal_user, patient=self.patient)
        with (
            patch("apps.patient_portal.admin.deliver_portal_invite", return_value=["whatsapp"]),
            patch.object(admin, "message_user") as message_user,
        ):
            admin.save_model(request, obj, form=MagicMock(), change=False)
        for call in message_user.call_args_list:
            self.assertNotIn(obj.invite_token, call.args[1])


class _Linha:
    def __init__(self, token: str | None, digest: str | None = None):
        self.invite_token_legado = token
        self.invite_token_hash = digest
        self.salvo_com = None

    def save(self, update_fields=None):
        self.salvo_com = update_fields


class _Apps:
    def __init__(self, linhas):
        manager = MagicMock()
        manager.all.return_value.iterator.return_value = iter(linhas)
        self.model = MagicMock(objects=manager)

    def get_model(self, app_label, name):
        assert (app_label, name) == ("patient_portal", "PatientPortalAccess")
        return self.model


class MigrationDeDadosTests(SimpleTestCase):
    """A função de dados da migration, isolada (o padrão da ordem 028): os
    convites já enviados passam a casar pelo hash."""

    def test_grava_o_hash_de_cada_convite_existente(self):
        modulo = importlib.import_module(MIGRATION)
        linhas = [_Linha("token-a"), _Linha("token-b")]
        modulo.hash_existing_invite_tokens(_Apps(linhas), None)
        for linha in linhas:
            self.assertEqual(linha.invite_token_hash, _sha256(linha.invite_token_legado))
            self.assertEqual(linha.salvo_com, ["invite_token_hash"])

    def test_nao_toca_linha_sem_claro_ou_ja_com_hash(self):
        modulo = importlib.import_module(MIGRATION)
        sem_claro, com_hash = _Linha(None), _Linha("token-c", digest="ja-tem")
        modulo.hash_existing_invite_tokens(_Apps([sem_claro, com_hash]), None)
        self.assertIsNone(sem_claro.salvo_com)
        self.assertIsNone(com_hash.salvo_com)
        self.assertEqual(com_hash.invite_token_hash, "ja-tem")

    def test_o_hash_da_migration_e_o_do_model(self):
        """Se divergirem, todo convite aberto morre calado na virada."""
        from apps.patient_portal.models import hash_invite_token

        modulo = importlib.import_module(MIGRATION)
        self.assertEqual(modulo.sha256_hex("abc"), hash_invite_token("abc"))
