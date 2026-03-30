"""
Billing tests — TISS guide and batch lifecycle.

Run: python manage.py test apps.billing.tests.test_billing
"""
import datetime

from django.core.cache import cache
from django.utils import timezone
from django_tenants.test.cases import TenantTestCase
from rest_framework.test import APIClient

from apps.billing.models import InsuranceProvider, TISSBatch, TISSGuide
from apps.core.models import Role, User
from apps.emr.models import Encounter, Patient, Professional


class BillingTestCase(TenantTestCase):
    """Billing lifecycle tests — run inside a tenant schema."""

    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain

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
