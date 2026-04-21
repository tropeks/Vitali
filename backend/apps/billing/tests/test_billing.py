"""
Billing tests — TISS guide and batch lifecycle.

Run: python manage.py test apps.billing.tests.test_billing
"""
import datetime

from django.core.cache import cache
from django.utils import timezone
from apps.test_utils import TenantTestCase
from rest_framework.test import APIClient

from apps.billing.models import Glosa, InsuranceProvider, TISSBatch, TISSGuide
from apps.billing.services.retorno_parser import parse_retorno
from apps.core.models import FeatureFlag, Role, User
from apps.emr.models import Encounter, Patient, Professional

TISS_NS = "http://www.ans.gov.br/padroes/tiss/schemas"

def _make_retorno_xml(batch_number: str, guide_number: str, situacao: str = "1", glosas: str = "") -> bytes:
    """Build a minimal valid TISS retorno XML for testing."""
    glosas_block = f"""
        <ans:glosas>
          {glosas}
        </ans:glosas>
    """ if glosas else ""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<ans:mensagemTISS xmlns:ans="{TISS_NS}">
  <ans:operadoraParaPrestador>
    <ans:retornoLote>
      <ans:numeroLote>{batch_number}</ans:numeroLote>
      <ans:retornoGuias>
        <ans:guiaSP_SADT>
          <ans:numeroGuiaPrestador>{guide_number}</ans:numeroGuiaPrestador>
          <ans:situacaoGuia>{situacao}</ans:situacaoGuia>
          {glosas_block}
        </ans:guiaSP_SADT>
      </ans:retornoGuias>
    </ans:retornoLote>
  </ans:operadoraParaPrestador>
</ans:mensagemTISS>""".encode()


class BillingTestCase(TenantTestCase):
    """Billing lifecycle tests — run inside a tenant schema."""

    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain

        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant, module_key='billing', defaults={'is_enabled': True}
        )

        # Roles
        self.faturista_role = Role.objects.create(
            name="faturista",
            permissions=["billing.read", "billing.write"],
            is_system=True,
        )
        self.enfermeiro_role = Role.objects.create(
            name="enfermeiro",
            permissions=["emr.read"],
            is_system=True,
        )

        # Users
        self.faturista = User.objects.create_user(
            email="faturista@test.com",
            full_name="Faturista Test",
            password="Str0ng!Pass#2024",
            role=self.faturista_role,
        )
        self.enfermeiro = User.objects.create_user(
            email="enfermeiro@test.com",
            full_name="Enfermeiro Test",
            password="Str0ng!Pass#2024",
            role=self.enfermeiro_role,
        )
        prof_user = User.objects.create_user(
            email="medico@test.com",
            full_name="Dr. Test",
            password="Str0ng!Pass#2024",
            role=self.faturista_role,
        )

        # Clinical records
        self.patient = Patient.objects.create(
            full_name="Maria Test",
            cpf="000.000.000-00",
            birth_date=datetime.date(1985, 1, 1),
            gender="F",
        )
        self.professional = Professional.objects.create(
            user=prof_user,
            council_type="CRM",
            council_number="99999",
            council_state="SP",
        )
        self.encounter = Encounter.objects.create(
            patient=self.patient,
            professional=self.professional,
        )
        self.provider = InsuranceProvider.objects.create(
            name="Unimed Test",
            ans_code="999999",
        )

        # Obtain tokens via login
        self.fat_token = self._get_token("faturista@test.com")
        self.enf_token = self._get_token("enfermeiro@test.com")

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

    def _create_guide(self, client=None):
        if client is None:
            client = self._auth(self.fat_token)
        return client.post(
            "/api/v1/billing/guides/",
            {
                "guide_type": "sadt",
                "encounter": str(self.encounter.id),
                "patient": str(self.patient.id),
                "provider": self.provider.id,
                "insured_card_number": "0001234567890001",
                "competency": "2026-03",
                "cid10_codes": [{"code": "J00"}],
            },
            format="json",
        )

    # ── Guide Number ──────────────────────────────────────────────────────────

    def test_guide_number_auto_generated(self):
        """New guides get a sequential YYYYMM + 6-digit number."""
        resp = self._create_guide()
        self.assertEqual(resp.status_code, 201)
        guide_number = resp.json()["guide_number"]
        prefix = timezone.now().strftime("%Y%m")
        self.assertTrue(guide_number.startswith(prefix))
        self.assertEqual(len(guide_number), 12)  # 6 date + 6 seq

    def test_guide_number_sequential(self):
        """Second guide gets a number 1 higher than the first."""
        r1 = self._create_guide()
        r2 = self._create_guide()
        self.assertEqual(r1.status_code, 201)
        self.assertEqual(r2.status_code, 201)
        n1 = int(r1.json()["guide_number"][6:])
        n2 = int(r2.json()["guide_number"][6:])
        self.assertEqual(n2, n1 + 1)

    # ── Guide Status ──────────────────────────────────────────────────────────

    def test_guide_status_patch_ignored(self):
        """Direct PATCH with status=paid must not change the guide status."""
        resp = self._create_guide()
        guide_id = resp.json()["id"]
        client = self._auth(self.fat_token)
        patch_resp = client.patch(
            f"/api/v1/billing/guides/{guide_id}/",
            {"status": "paid"},
            format="json",
        )
        self.assertEqual(patch_resp.status_code, 200)
        self.assertEqual(patch_resp.json()["status"], "draft")

    def test_guide_submit_transitions_to_submitted(self):
        """POST /guides/{id}/submit/ changes status to submitted."""
        resp = self._create_guide()
        guide_id = resp.json()["id"]
        client = self._auth(self.fat_token)
        submit_resp = client.post(f"/api/v1/billing/guides/{guide_id}/submit/")
        self.assertEqual(submit_resp.status_code, 200)
        self.assertEqual(submit_resp.json()["status"], "submitted")

    # ── Role Guard ────────────────────────────────────────────────────────────

    def test_enfermeiro_cannot_create_guide(self):
        """Users without billing.write get 403 on guide creation."""
        client = self._auth(self.enf_token)
        resp = self._create_guide(client=client)
        self.assertEqual(resp.status_code, 403)

    def test_enfermeiro_cannot_list_guides(self):
        """Users without billing.read get 403 on guide list."""
        client = self._auth(self.enf_token)
        resp = client.get("/api/v1/billing/guides/")
        self.assertEqual(resp.status_code, 403)

    def test_unauthenticated_returns_401(self):
        """Unauthenticated requests to billing endpoints return 401."""
        resp = self.client.get("/api/v1/billing/guides/")
        self.assertEqual(resp.status_code, 401)

    # ── Batch Operations ──────────────────────────────────────────────────────

    def test_batch_created_with_open_status(self):
        """New batches start with status=open."""
        client = self._auth(self.fat_token)
        resp = client.post(
            "/api/v1/billing/batches/",
            {"provider": self.provider.id},
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["status"], "open")

    def test_batch_close_promotes_pending_guides_to_submitted(self):
        """Closing a batch moves all pending guides to submitted."""
        guide_resp = self._create_guide()
        guide_id = guide_resp.json()["id"]
        client = self._auth(self.fat_token)

        # Mark guide pending (signals it's ready for batch submission)
        TISSGuide.objects.filter(id=guide_id).update(status="pending")

        # Create batch and add guide
        batch_resp = client.post(
            "/api/v1/billing/batches/",
            {"provider": self.provider.id},
            format="json",
        )
        batch_id = batch_resp.json()["id"]
        client.patch(
            f"/api/v1/billing/batches/{batch_id}/",
            {"guide_ids": [guide_id]},
            format="json",
        )

        # Close the batch
        close_resp = client.post(f"/api/v1/billing/batches/{batch_id}/close/")
        self.assertEqual(close_resp.status_code, 200)
        self.assertEqual(close_resp.json()["status"], "closed")

        # Guide should now be submitted
        guide = TISSGuide.objects.get(id=guide_id)
        self.assertEqual(guide.status, "submitted")

    def test_empty_batch_export_returns_400(self):
        """Exporting a batch with no guides returns 400."""
        client = self._auth(self.fat_token)
        batch_resp = client.post(
            "/api/v1/billing/batches/",
            {"provider": self.provider.id},
            format="json",
        )
        batch_id = batch_resp.json()["id"]
        export_resp = client.post(f"/api/v1/billing/batches/{batch_id}/export/")
        self.assertEqual(export_resp.status_code, 400)

    # ── Double Submit Protection ──────────────────────────────────────────────

    def test_guide_cannot_be_in_two_submitted_batches(self):
        """Adding a submitted guide to a second batch should fail."""
        guide_resp = self._create_guide()
        guide_id = guide_resp.json()["id"]
        client = self._auth(self.fat_token)

        # Batch 1 — add guide and close it
        b1 = client.post(
            "/api/v1/billing/batches/",
            {"provider": self.provider.id},
            format="json",
        ).json()["id"]
        client.patch(
            f"/api/v1/billing/batches/{b1}/",
            {"guide_ids": [guide_id]},
            format="json",
        )
        client.post(f"/api/v1/billing/batches/{b1}/close/")

        # Batch 2 — trying to add the same guide should fail
        b2 = client.post(
            "/api/v1/billing/batches/",
            {"provider": self.provider.id},
            format="json",
        ).json()["id"]
        add_resp = client.patch(
            f"/api/v1/billing/batches/{b2}/",
            {"guide_ids": [guide_id]},
            format="json",
        )
        self.assertEqual(add_resp.status_code, 400)


class RetornoParserTestCase(TenantTestCase):
    """Unit tests for the TISS retorno XML parser (parse_retorno)."""

    def setUp(self):
        cache.clear()
        faturista_role = Role.objects.create(
            name="faturista_rp",
            permissions=["billing.read", "billing.write"],
            is_system=True,
        )
        prof_user = User.objects.create_user(
            email="medico_rp@test.com",
            full_name="Dr. Retorno",
            password="Str0ng!Pass#2024",
            role=faturista_role,
        )
        patient = Patient.objects.create(
            full_name="João Retorno",
            cpf="111.111.111-11",
            birth_date=datetime.date(1980, 6, 15),
            gender="M",
        )
        professional = Professional.objects.create(
            user=prof_user,
            council_type="CRM",
            council_number="11111",
            council_state="RJ",
        )
        encounter = Encounter.objects.create(patient=patient, professional=professional)
        self.provider = InsuranceProvider.objects.create(name="Bradesco Test", ans_code="888888")
        self.batch = TISSBatch.objects.create(
            provider=self.provider,
            status="closed",
        )
        self.guide = TISSGuide.objects.create(
            guide_type="sadt",
            encounter=encounter,
            patient=patient,
            provider=self.provider,
            status="submitted",
            insured_card_number="1234567890000001",
            competency="2026-03",
        )
        # Force a known guide_number for predictable XML
        TISSGuide.objects.filter(pk=self.guide.pk).update(guide_number="202603000099")
        self.guide.refresh_from_db()
        self.batch.guides.add(self.guide)

    def test_parse_retorno_marks_guide_paid(self):
        """situacaoGuia=1 (pago) sets guide status to paid."""
        xml = _make_retorno_xml(self.batch.batch_number, self.guide.guide_number, situacao="1")
        result = parse_retorno(xml)
        self.assertEqual(result["guides_updated"], 1)
        self.assertEqual(result["glosas_created"], 0)
        self.guide.refresh_from_db()
        self.assertEqual(self.guide.status, "paid")

    def test_parse_retorno_marks_guide_denied(self):
        """situacaoGuia=2 (glosado) sets guide status to denied."""
        xml = _make_retorno_xml(self.batch.batch_number, self.guide.guide_number, situacao="2")
        result = parse_retorno(xml)
        self.assertEqual(result["guides_updated"], 1)
        self.guide.refresh_from_db()
        self.assertEqual(self.guide.status, "denied")

    def test_parse_retorno_creates_glosa_records(self):
        """Glosa elements in retorno create Glosa records."""
        glosas_xml = f"""<ans:glosa xmlns:ans="{TISS_NS}">
          <ans:codigoGlosa>01</ans:codigoGlosa>
          <ans:descricaoGlosa>Procedimento não coberto</ans:descricaoGlosa>
          <ans:valorGlosa>150.00</ans:valorGlosa>
        </ans:glosa>"""
        xml = _make_retorno_xml(
            self.batch.batch_number, self.guide.guide_number,
            situacao="1", glosas=glosas_xml
        )
        result = parse_retorno(xml)
        self.assertEqual(result["glosas_created"], 1)
        glosa = Glosa.objects.get(guide=self.guide)
        self.assertEqual(glosa.reason_code, "01")
        self.assertEqual(str(glosa.value_denied), "150.00")

    def test_parse_retorno_invalid_xml_returns_error(self):
        """Malformed XML returns an error dict without raising."""
        result = parse_retorno(b"not valid xml <<>>")
        self.assertIn("errors", result)
        self.assertTrue(len(result["errors"]) > 0)
        self.assertEqual(result["guides_updated"], 0)

    def test_parse_retorno_missing_retorno_lote_element(self):
        """XML without retornoLote element returns a descriptive error."""
        xml = b'<?xml version="1.0"?><root><nothing/></root>'
        result = parse_retorno(xml)
        self.assertTrue(any("retornoLote" in e for e in result["errors"]))

    def test_parse_retorno_updates_batch_to_processed(self):
        """Successful retorno processing marks the batch as processed."""
        xml = _make_retorno_xml(self.batch.batch_number, self.guide.guide_number, situacao="1")
        parse_retorno(xml)
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.status, "processed")


class GlosaAppealTestCase(TenantTestCase):
    """Tests for the glosa appeal endpoint."""

    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain

        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant, module_key='billing', defaults={'is_enabled': True}
        )

        faturista_role = Role.objects.create(
            name="faturista_ga",
            permissions=["billing.read", "billing.write"],
            is_system=True,
        )
        self.faturista = User.objects.create_user(
            email="faturista_ga@test.com",
            full_name="Faturista Appeal",
            password="Str0ng!Pass#2024",
            role=faturista_role,
        )
        prof_user = User.objects.create_user(
            email="medico_ga@test.com",
            full_name="Dr. Appeal",
            password="Str0ng!Pass#2024",
            role=faturista_role,
        )
        patient = Patient.objects.create(
            full_name="Ana Appeal",
            cpf="222.222.222-22",
            birth_date=datetime.date(1990, 3, 20),
            gender="F",
        )
        professional = Professional.objects.create(
            user=prof_user, council_type="CRM", council_number="22222", council_state="MG"
        )
        encounter = Encounter.objects.create(patient=patient, professional=professional)
        provider = InsuranceProvider.objects.create(name="Amil Test", ans_code="777777")
        self.guide = TISSGuide.objects.create(
            guide_type="sadt",
            encounter=encounter,
            patient=patient,
            provider=provider,
            status="denied",
            insured_card_number="9999999999999999",
            competency="2026-03",
        )
        self.glosa = Glosa.objects.create(
            guide=self.guide,
            reason_code="01",
            reason_description="Procedimento não coberto",
            value_denied="200.00",
        )
        login = self.client.post(
            "/api/v1/auth/login",
            {"email": "faturista_ga@test.com", "password": "Str0ng!Pass#2024"},
            format="json",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.json()['access']}")

    def test_glosa_appeal_filed_successfully(self):
        """POST /glosas/{id}/appeal/ with text sets appeal_status=filed and guide status=appeal."""
        resp = self.client.post(
            f"/api/v1/billing/glosas/{self.glosa.id}/appeal/",
            {"appeal_text": "Procedimento realizado com indicação clínica documentada."},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.glosa.refresh_from_db()
        self.assertEqual(self.glosa.appeal_status, "filed")
        self.guide.refresh_from_db()
        self.assertEqual(self.guide.status, "appeal")

    def test_glosa_appeal_requires_text(self):
        """POST /glosas/{id}/appeal/ with empty text returns 400."""
        resp = self.client.post(
            f"/api/v1/billing/glosas/{self.glosa.id}/appeal/",
            {"appeal_text": ""},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_glosa_appeal_cannot_refile(self):
        """Filing appeal twice returns 409 Conflict."""
        self.client.post(
            f"/api/v1/billing/glosas/{self.glosa.id}/appeal/",
            {"appeal_text": "First appeal"},
            format="json",
        )
        resp = self.client.post(
            f"/api/v1/billing/glosas/{self.glosa.id}/appeal/",
            {"appeal_text": "Second attempt"},
            format="json",
        )
        self.assertEqual(resp.status_code, 409)


class InsuranceProviderTestCase(TenantTestCase):
    """CRUD tests for InsuranceProvider."""

    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain

        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant, module_key='billing', defaults={'is_enabled': True}
        )

        faturista_role = Role.objects.create(
            name="faturista_ip",
            permissions=["billing.read", "billing.write"],
            is_system=True,
        )
        self.faturista = User.objects.create_user(
            email="faturista_ip@test.com",
            full_name="Faturista IP",
            password="Str0ng!Pass#2024",
            role=faturista_role,
        )
        login = self.client.post(
            "/api/v1/auth/login",
            {"email": "faturista_ip@test.com", "password": "Str0ng!Pass#2024"},
            format="json",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.json()['access']}")

    def test_create_insurance_provider(self):
        """POST /providers/ creates a provider and returns 201."""
        resp = self.client.post(
            "/api/v1/billing/providers/",
            {"name": "SulAmérica Test", "ans_code": "006246"},
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["name"], "SulAmérica Test")

    def test_list_insurance_providers(self):
        """GET /providers/ returns all providers."""
        InsuranceProvider.objects.create(name="Provider A", ans_code="000001")
        InsuranceProvider.objects.create(name="Provider B", ans_code="000002")
        resp = self.client.get("/api/v1/billing/providers/")
        self.assertEqual(resp.status_code, 200)
        self.assertGreaterEqual(resp.json()["count"], 2)
