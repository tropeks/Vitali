"""
Ordem 036: lista de espera para quem não tem schedule.read.

Esse ramo fazia ``Patient.objects.get(user=...)``, e ``Patient`` não tem campo
``user``: 500 na listagem e no POST, inclusive para o paciente do portal, a quem
o ramo se destina. O paciente agora é identificado pelo mesmo guard de
``/portal/me/*`` (``IsPortalSelfAccess``): ``PatientPortalAccess`` ativo e papel
com ``portal.self_access``. Sem isso, a lista volta vazia e o POST sem
``patient_id`` responde 400.
"""

import datetime
from datetime import date, timedelta

from apps.test_utils import TenantTestCase


class TestWaitlistSemScheduleRead(TenantTestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model

        from apps.core.models import Role

        self.User = get_user_model()
        self.portal_role = Role.objects.create(
            name="paciente-portal-waitlist-test", permissions=["portal.self_access"]
        )
        self._cria_profissional()
        self.ana, self.ana_user = self._cria_paciente_do_portal("Ana", "01")
        self.bruno, self.bruno_user = self._cria_paciente_do_portal("Bruno", "02")
        # Conta sem schedule.read e sem vínculo de portal.
        self.sem_vinculo = self.User.objects.create_user(
            email="semvinculo036@clinic.test", password="TestPass123!"
        )
        self.entrada_ana = self._cria_entrada(self.ana)
        self.entrada_bruno = self._cria_entrada(self.bruno)

    # ── fixtures ─────────────────────────────────────────────────────────────

    def _cria_profissional(self):
        from apps.emr.models import Professional

        doc = self.User.objects.create_user(
            email="waitlist036_doc@clinic.test", password="TestPass123!", full_name="Doc"
        )
        self.professional = Professional.objects.create(
            user=doc, council_type="CRM", council_number="360360", council_state="SP"
        )

    def _cria_paciente_do_portal(self, nome, sufixo):
        from apps.emr.models import Patient
        from apps.patient_portal.models import PatientPortalAccess

        patient = Patient.objects.create(
            full_name=f"{nome} Portal",
            cpf=f"360.000.000-{sufixo}",
            birth_date=datetime.date(1985, 3, 3),
            gender="F",
            phone=f"55119999903{sufixo}",
        )
        user = self.User.objects.create_user(
            email=f"{nome.lower()}036@portal.test",
            password="TestPass123!",
            role=self.portal_role,
        )
        access = PatientPortalAccess.objects.create(user=user, patient=patient)
        access.status = PatientPortalAccess.STATUS_ACTIVE
        access.save(update_fields=["status"])
        return patient, user

    def _cria_entrada(self, patient):
        from apps.emr.models import WaitlistEntry

        today = date.today()
        return WaitlistEntry.objects.create(
            patient=patient,
            professional=self.professional,
            preferred_date_from=today,
            preferred_date_to=today + timedelta(days=30),
        )

    def _client(self, user):
        from rest_framework.test import APIClient
        from rest_framework_simplejwt.tokens import RefreshToken

        client = APIClient()
        client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        # Deixa o 500 aparecer como resposta, não como exceção no teste.
        client.raise_request_exception = False
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
        return client

    def _corpo_post(self, **extra):
        today = date.today()
        return {
            "professional_id": str(self.professional.id),
            "preferred_date_from": today.isoformat(),
            "preferred_date_to": (today + timedelta(days=14)).isoformat(),
            **extra,
        }

    def _muda_status_do_acesso_da_ana(self, status):
        access = self.ana_user.patient_portal_access
        access.status = status
        access.save(update_fields=["status"])

    # ── listagem ─────────────────────────────────────────────────────────────

    def test_paciente_do_portal_lista_so_a_propria_entrada(self):
        resp = self._client(self.ana_user).get("/api/v1/waitlist/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([e["id"] for e in resp.data], [str(self.entrada_ana.id)])

    def test_paciente_nao_ve_a_lista_de_espera_de_outro(self):
        resp = self._client(self.bruno_user).get("/api/v1/waitlist/")
        self.assertEqual(resp.status_code, 200)
        ids = {e["id"] for e in resp.data}
        self.assertNotIn(str(self.entrada_ana.id), ids)
        self.assertEqual(ids, {str(self.entrada_bruno.id)})

    def test_sem_vinculo_lista_vazia(self):
        resp = self._client(self.sem_vinculo).get("/api/v1/waitlist/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data, [])

    def test_vinculo_convidado_ou_revogado_nao_identifica_paciente(self):
        from apps.patient_portal.models import PatientPortalAccess

        for status_ in (PatientPortalAccess.STATUS_INVITED, PatientPortalAccess.STATUS_REVOKED):
            with self.subTest(status=status_):
                self._muda_status_do_acesso_da_ana(status_)
                resp = self._client(self.ana_user).get("/api/v1/waitlist/")
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.data, [])

    def test_papel_sem_portal_self_access_nao_identifica_paciente(self):
        """Mesmo critério de `IsPortalSelfAccess`: vínculo ativo não basta."""
        from apps.core.models import Role

        self.ana_user.role = Role.objects.create(name="sem-portal-036", permissions=[])
        self.ana_user.save(update_fields=["role"])

        client = self._client(self.ana_user)
        resp = client.get("/api/v1/waitlist/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data, [])
        self.assertEqual(client.post("/api/v1/waitlist/", self._corpo_post()).status_code, 400)

    # ── criação ──────────────────────────────────────────────────────────────

    def test_paciente_do_portal_cria_entrada_para_si(self):
        from apps.emr.models import WaitlistEntry

        self.entrada_ana.status = "cancelled"
        self.entrada_ana.save(update_fields=["status"])

        resp = self._client(self.ana_user).post("/api/v1/waitlist/", self._corpo_post())
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(str(resp.data["patient"]), str(self.ana.id))
        self.assertTrue(
            WaitlistEntry.objects.filter(
                pk=resp.data["id"], patient=self.ana, status="waiting"
            ).exists()
        )

    def test_sem_vinculo_post_sem_patient_id_responde_400(self):
        resp = self._client(self.sem_vinculo).post("/api/v1/waitlist/", self._corpo_post())
        self.assertEqual(resp.status_code, 400)

    def test_vinculo_revogado_post_sem_patient_id_responde_400(self):
        from apps.patient_portal.models import PatientPortalAccess

        self._muda_status_do_acesso_da_ana(PatientPortalAccess.STATUS_REVOKED)
        resp = self._client(self.ana_user).post("/api/v1/waitlist/", self._corpo_post())
        self.assertEqual(resp.status_code, 400)

    def test_paciente_nao_cria_entrada_em_nome_de_outro(self):
        from apps.emr.models import WaitlistEntry

        antes = WaitlistEntry.objects.filter(patient=self.bruno).count()
        resp = self._client(self.ana_user).post(
            "/api/v1/waitlist/", self._corpo_post(patient_id=str(self.bruno.id))
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(WaitlistEntry.objects.filter(patient=self.bruno).count(), antes)
