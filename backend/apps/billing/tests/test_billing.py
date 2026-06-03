"""
Billing tests — TISS guide and batch lifecycle.

Run: python manage.py test apps.billing.tests.test_billing
"""

import datetime
from decimal import Decimal

from django.core.cache import cache
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework.test import APIClient

from apps.ai.models import GlosaPrediction
from apps.billing.models import (
    Glosa,
    GlosaSafetyAlert,
    InsuranceProvider,
    TISSBatch,
    TISSGuide,
    TISSGuideItem,
)
from apps.billing.services.retorno_parser import parse_retorno
from apps.core.models import FeatureFlag, Role, TUSSCode, User
from apps.emr.models import Encounter, Patient, Professional
from apps.test_utils import TenantTestCase

TISS_NS = "http://www.ans.gov.br/padroes/tiss/schemas"


def _make_retorno_xml(
    batch_number: str, guide_number: str, situacao: str = "1", glosas: str = ""
) -> bytes:
    """Build a minimal valid TISS retorno XML for testing."""
    glosas_block = (
        f"""
        <ans:glosas>
          {glosas}
        </ans:glosas>
    """
        if glosas
        else ""
    )
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


def _proc_glosa_block(sequencial: int, tuss: str, codigo: str, descricao: str, valor: str) -> str:
    """A single <procedimentoExecutado> with an item-level glosa (TISS structure)."""
    return f"""
        <ans:procedimentoExecutado>
          <ans:sequencialItem>{sequencial}</ans:sequencialItem>
          <ans:procedimento>
            <ans:codigoTabela>22</ans:codigoTabela>
            <ans:codigoProcedimento>{tuss}</ans:codigoProcedimento>
          </ans:procedimento>
          <ans:glosasProcedimento>
            <ans:glosa>
              <ans:codigoGlosa>{codigo}</ans:codigoGlosa>
              <ans:descricaoGlosa>{descricao}</ans:descricaoGlosa>
              <ans:valorGlosa>{valor}</ans:valorGlosa>
            </ans:glosa>
          </ans:glosasProcedimento>
        </ans:procedimentoExecutado>"""


def _make_retorno_xml_itemlevel(
    batch_number: str,
    guide_number: str,
    *,
    situacao: str = "3",
    procedimentos: str = "",
    glosas_guia: str = "",
) -> bytes:
    """Build a TISS retorno XML with item-level (procedimentoExecutado) glosas.

    ``procedimentos`` is a concatenation of _proc_glosa_block(...) fragments.
    ``glosas_guia`` is raw <ans:glosa>... markup for a true guide-level denial.
    """
    proc_section = (
        f"""
          <ans:procedimentosExecutados>
            {procedimentos}
          </ans:procedimentosExecutados>"""
        if procedimentos
        else ""
    )
    guia_section = (
        f"""
          <ans:glosasGuia>
            {glosas_guia}
          </ans:glosasGuia>"""
        if glosas_guia
        else ""
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<ans:mensagemTISS xmlns:ans="{TISS_NS}">
  <ans:operadoraParaPrestador>
    <ans:retornoLote>
      <ans:numeroLote>{batch_number}</ans:numeroLote>
      <ans:retornoGuias>
        <ans:guiaSP_SADT>
          <ans:numeroGuiaPrestador>{guide_number}</ans:numeroGuiaPrestador>
          <ans:situacaoGuia>{situacao}</ans:situacaoGuia>
          {proc_section}
          {guia_section}
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
            tenant=self.__class__.tenant, module_key="billing", defaults={"is_enabled": True}
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

    def test_guides_can_filter_by_patient_for_command_center(self):
        """Patient command center can request only the selected patient's guides."""
        other_patient = Patient.objects.create(
            full_name="Outro Paciente",
            cpf="111.111.111-11",
            birth_date=datetime.date(1991, 2, 2),
            gender="M",
        )
        other_encounter = Encounter.objects.create(
            patient=other_patient,
            professional=self.professional,
        )
        guide_resp = self._create_guide()
        self.assertEqual(guide_resp.status_code, 201)
        other_guide = TISSGuide.objects.create(
            guide_type="consultation",
            encounter=other_encounter,
            patient=other_patient,
            provider=self.provider,
            competency="2026-03",
        )

        client = self._auth(self.fat_token)
        resp = client.get(f"/api/v1/billing/guides/?patient={self.patient.id}")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        items = body["results"] if isinstance(body, dict) else body
        ids = {item["id"] for item in items}
        self.assertIn(guide_resp.json()["id"], ids)
        self.assertNotIn(str(other_guide.id), ids)

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

    def test_closing_second_open_batch_with_same_guide_fails(self):
        """
        Core gap: a guide can sit in two OPEN batches (add-time check used to pass
        for both). Closing the first must succeed; closing the second must fail at
        close time, otherwise the guide is exported in two XMLs → billed twice.

        We attach the guide to both batches at the model layer (bypassing the now
        tightened add-time check) to reproduce the pre-existing data shape, then
        verify the close endpoint catches it.
        """
        guide_resp = self._create_guide()
        guide_id = guide_resp.json()["id"]
        guide = TISSGuide.objects.get(id=guide_id)
        client = self._auth(self.fat_token)

        b1 = client.post(
            "/api/v1/billing/batches/",
            {"provider": self.provider.id},
            format="json",
        ).json()["id"]
        b2 = client.post(
            "/api/v1/billing/batches/",
            {"provider": self.provider.id},
            format="json",
        ).json()["id"]

        # Force both open batches to hold the same guide (simulates the window
        # before the add-time tightening, using the through table directly so the
        # pre_add signal does not block us setting up the scenario).
        TISSBatch.guides.through.objects.create(tissbatch_id=b1, tissguide_id=guide.pk)
        TISSBatch.guides.through.objects.create(tissbatch_id=b2, tissguide_id=guide.pk)

        # First close wins.
        close1 = client.post(f"/api/v1/billing/batches/{b1}/close/")
        self.assertEqual(close1.status_code, 200)
        self.assertEqual(close1.json()["status"], "closed")

        # Second close must be rejected — guide already in a closed batch.
        close2 = client.post(f"/api/v1/billing/batches/{b2}/close/")
        self.assertEqual(close2.status_code, 400)
        self.assertEqual(TISSBatch.objects.get(id=b2).status, "open")

    def test_guide_cannot_be_added_to_second_open_batch(self):
        """Add-time tightening: a guide already in an open batch cannot be added
        to a different open batch."""
        guide_resp = self._create_guide()
        guide_id = guide_resp.json()["id"]
        client = self._auth(self.fat_token)

        b1 = client.post(
            "/api/v1/billing/batches/",
            {"provider": self.provider.id},
            format="json",
        ).json()["id"]
        add1 = client.patch(
            f"/api/v1/billing/batches/{b1}/",
            {"guide_ids": [guide_id]},
            format="json",
        )
        self.assertEqual(add1.status_code, 200)

        b2 = client.post(
            "/api/v1/billing/batches/",
            {"provider": self.provider.id},
            format="json",
        ).json()["id"]
        add2 = client.patch(
            f"/api/v1/billing/batches/{b2}/",
            {"guide_ids": [guide_id]},
            format="json",
        )
        self.assertEqual(add2.status_code, 400)

    def test_reverse_m2m_add_enforces_double_submit(self):
        """
        Reverse-M2M path (guide.batches.add(batch)) must not crash and must
        enforce the double-submit rule. Previously the signal treated batch pks as
        guide pks and broke.
        """
        guide_resp = self._create_guide()
        guide = TISSGuide.objects.get(id=guide_resp.json()["id"])

        b1 = TISSBatch.objects.create(provider=self.provider, status="closed")
        b1.guides.add(guide)  # guide now in a closed batch

        b2 = TISSBatch.objects.create(provider=self.provider, status="open")
        # Reverse add — must raise (not crash with a wrong-model lookup).
        # Wrap in a savepoint: the signal raises mid-`.add()`, which marks the
        # transaction for rollback; without an inner atomic() the outer test
        # transaction would be poisoned and the assertion query below would fail
        # with TransactionManagementError.
        with self.assertRaises(DjangoValidationError), transaction.atomic():
            guide.batches.add(b2)
        self.assertNotIn(b2, guide.batches.all())

    def test_reverse_m2m_add_succeeds_when_no_conflict(self):
        """Reverse-M2M add of a guide with no other batch works (regression)."""
        guide_resp = self._create_guide()
        guide = TISSGuide.objects.get(id=guide_resp.json()["id"])
        batch = TISSBatch.objects.create(provider=self.provider, status="open")
        guide.batches.add(batch)
        self.assertIn(batch, guide.batches.all())

    def test_guide_in_cancelled_batch_can_be_rebatched_and_closed(self):
        """No false positive: a guide whose only other batch is cancelled can be
        added to a new batch and that batch can be closed."""
        guide_resp = self._create_guide()
        guide_id = guide_resp.json()["id"]
        guide = TISSGuide.objects.get(id=guide_id)
        client = self._auth(self.fat_token)

        # A cancelled batch holding the guide must not block re-batching.
        cancelled = TISSBatch.objects.create(provider=self.provider, status="cancelled")
        TISSBatch.guides.through.objects.create(tissbatch_id=cancelled.pk, tissguide_id=guide.pk)

        b2 = client.post(
            "/api/v1/billing/batches/",
            {"provider": self.provider.id},
            format="json",
        ).json()["id"]
        add = client.patch(
            f"/api/v1/billing/batches/{b2}/",
            {"guide_ids": [guide_id]},
            format="json",
        )
        self.assertEqual(add.status_code, 200)

        close = client.post(f"/api/v1/billing/batches/{b2}/close/")
        self.assertEqual(close.status_code, 200)
        self.assertEqual(close.json()["status"], "closed")

    def test_single_batch_close_still_works(self):
        """Regression guard: a guide in exactly one batch closes normally."""
        guide_resp = self._create_guide()
        guide_id = guide_resp.json()["id"]
        client = self._auth(self.fat_token)

        b = client.post(
            "/api/v1/billing/batches/",
            {"provider": self.provider.id},
            format="json",
        ).json()["id"]
        add = client.patch(
            f"/api/v1/billing/batches/{b}/",
            {"guide_ids": [guide_id]},
            format="json",
        )
        self.assertEqual(add.status_code, 200)
        close = client.post(f"/api/v1/billing/batches/{b}/close/")
        self.assertEqual(close.status_code, 200)
        self.assertEqual(close.json()["status"], "closed")


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
            self.batch.batch_number, self.guide.guide_number, situacao="1", glosas=glosas_xml
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


class RetornoItemLevelTestCase(TenantTestCase):
    """Item-level glosa mapping + was_denied backfill (G3a, decision A-5).

    Kills the data-poisoning trap: a guide with N items where only ONE is
    glosado must mark ONLY that item denied, never the whole guide.
    """

    def setUp(self):
        cache.clear()
        faturista_role = Role.objects.create(
            name="faturista_il",
            permissions=["billing.read", "billing.write"],
            is_system=True,
        )
        prof_user = User.objects.create_user(
            email="medico_il@test.com",
            full_name="Dr. ItemLevel",
            password="Str0ng!Pass#2024",
            role=faturista_role,
        )
        patient = Patient.objects.create(
            full_name="Ana ItemLevel",
            cpf="222.222.222-22",
            birth_date=datetime.date(1990, 3, 10),
            gender="F",
        )
        professional = Professional.objects.create(
            user=prof_user,
            council_type="CRM",
            council_number="22222",
            council_state="SP",
        )
        encounter = Encounter.objects.create(patient=patient, professional=professional)
        self.provider = InsuranceProvider.objects.create(name="Amil Test", ans_code="777777")
        self.batch = TISSBatch.objects.create(provider=self.provider, status="closed")
        self.guide = TISSGuide.objects.create(
            guide_type="sadt",
            encounter=encounter,
            patient=patient,
            provider=self.provider,
            status="submitted",
            insured_card_number="1234567890000002",
            competency="2026-03",
        )
        TISSGuide.objects.filter(pk=self.guide.pk).update(guide_number="202603000200")
        self.guide.refresh_from_db()
        self.batch.guides.add(self.guide)

        # 3 TUSS codes, 3 distinct guide items.
        self.tuss_a = TUSSCode.objects.create(
            code="10101012", description="Consulta", group="procedimento", version="2024-01"
        )
        self.tuss_b = TUSSCode.objects.create(
            code="40304361", description="Hemograma", group="procedimento", version="2024-01"
        )
        self.tuss_c = TUSSCode.objects.create(
            code="40302024", description="Glicose", group="procedimento", version="2024-01"
        )
        self.item_a = TISSGuideItem.objects.create(
            guide=self.guide,
            tuss_code=self.tuss_a,
            description="Consulta",
            quantity=Decimal("1"),
            unit_value=Decimal("100.00"),
        )
        self.item_b = TISSGuideItem.objects.create(
            guide=self.guide,
            tuss_code=self.tuss_b,
            description="Hemograma",
            quantity=Decimal("1"),
            unit_value=Decimal("50.00"),
        )
        self.item_c = TISSGuideItem.objects.create(
            guide=self.guide,
            tuss_code=self.tuss_c,
            description="Glicose",
            quantity=Decimal("1"),
            unit_value=Decimal("30.00"),
        )

        # Flywheel rows: one engine alert per item + one prediction per TUSS.
        for item in (self.item_a, self.item_b, self.item_c):
            GlosaSafetyAlert.objects.create(
                guide=self.guide,
                guide_item=item,
                check_code=GlosaSafetyAlert.CheckCode.NOT_IN_TABLE,
                severity=GlosaSafetyAlert.Severity.ADVISE,
                message="x",
            )
            GlosaPrediction.objects.create(
                guide=self.guide,
                tuss_code=item.tuss_code.code,
                insurer_ans_code=self.provider.ans_code,
                guide_type="sadt",
                risk_level="low",
                risk_reason="x",
            )

    def test_only_glosado_item_is_denied(self):
        """Multi-item guide, ONE procedure glosado → exactly one item-level Glosa;
        was_denied True only for that item's flywheel rows, others untouched."""
        procs = _proc_glosa_block(
            sequencial=2,
            tuss=self.tuss_b.code,
            codigo="01",
            descricao="Procedimento não coberto",
            valor="50.00",
        )
        xml = _make_retorno_xml_itemlevel(
            self.batch.batch_number, self.guide.guide_number, situacao="3", procedimentos=procs
        )
        result = parse_retorno(xml)

        self.assertEqual(result["glosas_created"], 1)
        glosa = Glosa.objects.get(guide=self.guide)
        self.assertEqual(glosa.guide_item_id, self.item_b.pk)
        self.assertEqual(glosa.reason_code, "01")

        # Only item_b's flywheel rows flipped.
        alerts = {a.guide_item_id: a.was_denied for a in GlosaSafetyAlert.objects.all()}
        self.assertTrue(alerts[self.item_b.pk])
        self.assertIsNone(alerts[self.item_a.pk])
        self.assertIsNone(alerts[self.item_c.pk])

        preds = {p.tuss_code: p.was_denied for p in GlosaPrediction.objects.all()}
        self.assertTrue(preds[self.tuss_b.code])
        self.assertIsNone(preds[self.tuss_a.code])
        self.assertIsNone(preds[self.tuss_c.code])

    def test_guide_level_glosa_does_not_mark_items(self):
        """A guide-level glosa (no procedure context, e.g. missing signature) →
        Glosa.guide_item is None and NO item gets was_denied=True."""
        glosas_guia = f"""<ans:glosa xmlns:ans="{TISS_NS}">
          <ans:codigoGlosa>17</ans:codigoGlosa>
          <ans:descricaoGlosa>Falta assinatura do beneficiário</ans:descricaoGlosa>
          <ans:valorGlosa>0.00</ans:valorGlosa>
        </ans:glosa>"""
        xml = _make_retorno_xml_itemlevel(
            self.batch.batch_number,
            self.guide.guide_number,
            situacao="2",
            glosas_guia=glosas_guia,
        )
        result = parse_retorno(xml)

        self.assertEqual(result["glosas_created"], 1)
        glosa = Glosa.objects.get(guide=self.guide)
        self.assertIsNone(glosa.guide_item_id)

        # No item-level was_denied flips.
        self.assertEqual(GlosaSafetyAlert.objects.filter(was_denied=True).count(), 0)
        self.assertEqual(GlosaPrediction.objects.filter(was_denied=True).count(), 0)

    def test_idempotent_reparse(self):
        """Parsing the same item-level retorno twice → no duplicate Glosa, labels stable."""
        procs = _proc_glosa_block(
            sequencial=2,
            tuss=self.tuss_b.code,
            codigo="01",
            descricao="Procedimento não coberto",
            valor="50.00",
        )
        xml = _make_retorno_xml_itemlevel(
            self.batch.batch_number, self.guide.guide_number, situacao="3", procedimentos=procs
        )
        parse_retorno(xml)
        parse_retorno(xml)

        self.assertEqual(Glosa.objects.filter(guide=self.guide).count(), 1)
        self.assertEqual(
            GlosaSafetyAlert.objects.filter(guide_item=self.item_b, was_denied=True).count(),
            1,
        )
        # Other items still untouched after re-parse.
        self.assertEqual(
            GlosaSafetyAlert.objects.filter(was_denied=True)
            .exclude(guide_item=self.item_b)
            .count(),
            0,
        )

    def test_ambiguous_duplicate_tuss_no_sequence_falls_back_guidelevel(self):
        """Duplicate TUSS lines with no sequencialItem → cannot disambiguate →
        guide-level Glosa (guide_item None), never guess-attached to an item."""
        # Add a SECOND item with the same TUSS as item_b → ambiguous.
        TISSGuideItem.objects.create(
            guide=self.guide,
            tuss_code=self.tuss_b,
            description="Hemograma 2",
            quantity=Decimal("1"),
            unit_value=Decimal("50.00"),
        )
        # Procedure glosa with NO sequencialItem (sequencial=0 → omitted-ish).
        proc = f"""
        <ans:procedimentoExecutado>
          <ans:procedimento>
            <ans:codigoTabela>22</ans:codigoTabela>
            <ans:codigoProcedimento>{self.tuss_b.code}</ans:codigoProcedimento>
          </ans:procedimento>
          <ans:glosasProcedimento>
            <ans:glosa>
              <ans:codigoGlosa>01</ans:codigoGlosa>
              <ans:descricaoGlosa>Ambíguo</ans:descricaoGlosa>
              <ans:valorGlosa>50.00</ans:valorGlosa>
            </ans:glosa>
          </ans:glosasProcedimento>
        </ans:procedimentoExecutado>"""
        xml = _make_retorno_xml_itemlevel(
            self.batch.batch_number, self.guide.guide_number, situacao="3", procedimentos=proc
        )
        result = parse_retorno(xml)

        glosa = Glosa.objects.get(guide=self.guide)
        self.assertIsNone(glosa.guide_item_id)
        self.assertTrue(any("ambiguous" in e.lower() for e in result["errors"]))
        # No item flipped denied.
        self.assertEqual(GlosaSafetyAlert.objects.filter(was_denied=True).count(), 0)


class GlosaAppealTestCase(TenantTestCase):
    """Tests for the glosa appeal endpoint."""

    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain

        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant, module_key="billing", defaults={"is_enabled": True}
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
            tenant=self.__class__.tenant, module_key="billing", defaults={"is_enabled": True}
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
