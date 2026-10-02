"""Ordem 039 — reenvio de convite: token novo sobre o mesmo registro.

Convite vencido (ou perdido) não tinha saída: a clínica criava outro acesso ou
mexia no banco. Agora ``POST /portal/access/<id>/resend/`` cunha um token novo
sobre o MESMO ``PatientPortalAccess``: o hash antigo deixa de valer, a validade
renova, e a trilha (id, ``invited_at``, ``created_by`` e um ``AuditLog``) fica.
Só o hash vai ao banco (ordem 033), o que mantém o reenvio compatível com a
fase 2 (ordem 034).
"""

from __future__ import annotations

import hashlib
from datetime import timedelta
from unittest.mock import patch

from django.utils import timezone

from apps.core.models import AuditLog
from apps.patient_portal.models import PatientPortalAccess
from apps.patient_portal.tests.test_invite_token_hash import ACTIVATE_URL, _Base, _usuario

ACCESS_URL = "/api/v1/portal/access/"


def _resend_url(access) -> str:
    return f"{ACCESS_URL}{access.pk}/resend/"


def _sha256(texto: str) -> str:
    return hashlib.sha256(texto.encode()).hexdigest()


class ReenvioTests(_Base):
    def _convite_vencido(self) -> PatientPortalAccess:
        access = self._convite()
        PatientPortalAccess.objects.filter(pk=access.pk).update(
            invite_expires_at=timezone.now() - timedelta(days=1)
        )
        return access

    def test_reenvio_cunha_token_novo_sobre_o_mesmo_registro(self):
        access = self._convite()
        antigo = access.invite_token
        self.client.force_authenticate(user=self.admin)
        with patch("apps.patient_portal.views.deliver_portal_invite"):
            resp = self.client.post(_resend_url(access), format="json")
        self.assertEqual(resp.status_code, 200, getattr(resp, "data", None))
        self.assertEqual(resp.data["id"], str(access.pk))
        novo = resp.data["invite_token"]
        self.assertTrue(novo)
        self.assertNotEqual(novo, antigo)
        self.assertEqual(PatientPortalAccess.objects.count(), 1)
        self.assertEqual(PatientPortalAccess.objects.get(pk=access.pk).invite_token_hash, _sha256(novo))

    def test_token_antigo_deixa_de_ativar_e_o_novo_ativa(self):
        access = self._convite()
        antigo = access.invite_token
        self.client.force_authenticate(user=self.admin)
        with patch("apps.patient_portal.views.deliver_portal_invite"):
            novo = self.client.post(_resend_url(access), format="json").data["invite_token"]
        self.client.force_authenticate(user=self.portal_user)
        recusado = self.client.post(ACTIVATE_URL, {"invite_token": antigo}, format="json")
        self.assertEqual(recusado.status_code, 400)
        ativado = self.client.post(ACTIVATE_URL, {"invite_token": novo}, format="json")
        self.assertEqual(ativado.status_code, 200, ativado.data)
        self.assertEqual(ativado.data["status"], "active")

    def test_convite_vencido_volta_a_valer(self):
        access = self._convite_vencido()
        self.assertFalse(PatientPortalAccess.objects.get(pk=access.pk).is_invite_valid())
        self.client.force_authenticate(user=self.admin)
        with patch("apps.patient_portal.views.deliver_portal_invite"):
            resp = self.client.post(_resend_url(access), format="json")
        self.assertEqual(resp.status_code, 200)
        recarregado = PatientPortalAccess.objects.get(pk=access.pk)
        self.assertTrue(recarregado.is_invite_valid())
        self.assertGreater(recarregado.invite_expires_at, timezone.now() + timedelta(days=6))

    def test_a_trilha_do_registro_fica(self):
        access = self._convite()
        antes = PatientPortalAccess.objects.get(pk=access.pk)
        self.client.force_authenticate(user=self.admin)
        with patch("apps.patient_portal.views.deliver_portal_invite"):
            self.client.post(_resend_url(access), format="json")
        depois = PatientPortalAccess.objects.get(pk=access.pk)
        self.assertEqual(depois.invited_at, antes.invited_at)
        self.assertEqual(depois.created_by_id, antes.created_by_id)
        self.assertEqual(depois.user_id, antes.user_id)
        self.assertEqual(depois.patient_id, antes.patient_id)

    def test_o_reenvio_deixa_auditlog_de_quem_reenviou(self):
        access = self._convite()
        self.client.force_authenticate(user=self.admin)
        with patch("apps.patient_portal.views.deliver_portal_invite"):
            self.client.post(_resend_url(access), format="json")
        log = AuditLog.objects.get(action="portal_invite_resent")
        self.assertEqual(log.user_id, self.admin.pk)
        self.assertEqual(log.resource_id, str(access.pk))
        self.assertNotIn("invite_token", str(log.new_data))

    def test_o_reenvio_entrega_o_token_novo(self):
        access = self._convite()
        self.client.force_authenticate(user=self.admin)
        with patch("apps.patient_portal.views.deliver_portal_invite") as entrega:
            resp = self.client.post(_resend_url(access), format="json")
        entrega.assert_called_once()
        (entregue,) = entrega.call_args.args
        self.assertEqual(entregue.invite_token, resp.data["invite_token"])

    def test_falha_na_entrega_nao_derruba_o_reenvio(self):
        access = self._convite()
        self.client.force_authenticate(user=self.admin)
        with patch(
            "apps.patient_portal.views.deliver_portal_invite", side_effect=RuntimeError("canal")
        ):
            resp = self.client.post(_resend_url(access), format="json")
        self.assertEqual(resp.status_code, 200)

    def test_acesso_ativo_recusa(self):
        access = self._convite()
        access.activate()
        self.client.force_authenticate(user=self.admin)
        resp = self.client.post(_resend_url(access), format="json")
        self.assertEqual(resp.status_code, 409)

    def test_acesso_revogado_nao_e_reaberto(self):
        access = self._convite()
        access.revoke()
        self.client.force_authenticate(user=self.admin)
        resp = self.client.post(_resend_url(access), format="json")
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(PatientPortalAccess.objects.get(pk=access.pk).status, "revoked")

    def test_sem_users_write_e_403(self):
        access = self._convite()
        leitor = _usuario("leitor_resend@test.com", ["users.read"])
        self.client.force_authenticate(user=leitor)
        resp = self.client.post(_resend_url(access), format="json")
        self.assertEqual(resp.status_code, 403)

    def test_anonimo_e_recusado(self):
        access = self._convite()
        resp = self.client.post(_resend_url(access), format="json")
        self.assertIn(resp.status_code, (401, 403))

    def test_acesso_inexistente_e_404(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.post(
            f"{ACCESS_URL}00000000-0000-0000-0000-000000000000/resend/", format="json"
        )
        self.assertEqual(resp.status_code, 404)

    def test_get_nao_existe(self):
        access = self._convite()
        self.client.force_authenticate(user=self.admin)
        self.assertEqual(self.client.get(_resend_url(access)).status_code, 405)
