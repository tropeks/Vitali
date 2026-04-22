"""
Tests for S-070 DPA Signing UI.

Covers:
  - GET /settings/dpa/ returns is_signed=False before signing
  - GET /settings/dpa/ returns unsigned response when AIDPAStatus row doesn't exist
  - POST /settings/dpa/sign/ sets dpa_signed_date and signed_by_user
  - POST /settings/dpa/sign/ creates AuditLog entry
  - Non-admin POST returns 403
  - Double-sign is idempotent (does not overwrite date, no second AuditLog)
  - GET /settings/dpa/ returns signed status with date and name after signing
"""

import datetime

from rest_framework.test import APIClient

from apps.core.models import AIDPAStatus, AuditLog, Role, User
from apps.test_utils import TenantTestCase


class DPAStatusViewTest(TenantTestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        self.admin_role = Role.objects.create(
            name="admin",
            permissions=["emr.read"],
            is_system=True,
        )
        self.admin = User.objects.create_user(
            email="admin_dpa@clinic.test",
            full_name="Admin DPA",
            password="TestPass123!",
            role=self.admin_role,
        )
        self.nurse_role = Role.objects.create(
            name="nurse",
            permissions=["emr.read"],
        )
        self.nurse = User.objects.create_user(
            email="nurse_dpa@clinic.test",
            full_name="Nurse DPA",
            password="TestPass123!",
            role=self.nurse_role,
        )

    def _auth(self, user):
        self.client.force_authenticate(user=user)

    def test_get_returns_unsigned_when_no_row_exists(self):
        AIDPAStatus.objects.filter(tenant=self.__class__.tenant).delete()
        self._auth(self.admin)
        resp = self.client.get("/api/v1/settings/dpa/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data["is_signed"])
        self.assertIsNone(data["signed_at"])
        self.assertIsNone(data["signed_by_name"])

    def test_get_returns_unsigned_when_row_exists_but_not_signed(self):
        AIDPAStatus.objects.get_or_create(tenant=self.__class__.tenant)
        self._auth(self.admin)
        resp = self.client.get("/api/v1/settings/dpa/")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["is_signed"])

    def test_post_sign_sets_date_and_user(self):
        AIDPAStatus.objects.filter(tenant=self.__class__.tenant).delete()
        self._auth(self.admin)
        before = datetime.date.today()
        resp = self.client.post("/api/v1/settings/dpa/sign/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["is_signed"])
        self.assertIsNotNone(data["signed_at"])
        self.assertEqual(data["signed_by_name"], self.admin.full_name)

        dpa = AIDPAStatus.objects.get(tenant=self.__class__.tenant)
        self.assertIsNotNone(dpa.dpa_signed_date)
        self.assertGreaterEqual(dpa.dpa_signed_date, before)
        self.assertEqual(dpa.signed_by_user, self.admin)

    def test_post_sign_creates_audit_log(self):
        AIDPAStatus.objects.filter(tenant=self.__class__.tenant).delete()
        self._auth(self.admin)
        self.client.post("/api/v1/settings/dpa/sign/")
        log = AuditLog.objects.filter(
            action="dpa_sign",
            resource_type="ai_dpa_status",
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.user, self.admin)
        self.assertIn("signed_by_id", log.new_data)

    def test_non_admin_post_returns_403(self):
        self._auth(self.nurse)
        resp = self.client.post("/api/v1/settings/dpa/sign/")
        self.assertEqual(resp.status_code, 403)

    def test_double_sign_is_idempotent(self):
        AIDPAStatus.objects.filter(tenant=self.__class__.tenant).delete()
        self._auth(self.admin)
        resp1 = self.client.post("/api/v1/settings/dpa/sign/")
        self.assertEqual(resp1.status_code, 200)
        first_date = resp1.json()["signed_at"]
        audit_count_after_first = AuditLog.objects.filter(action="dpa_sign").count()

        resp2 = self.client.post("/api/v1/settings/dpa/sign/")
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp2.json()["signed_at"], first_date)
        audit_count_after_second = AuditLog.objects.filter(action="dpa_sign").count()
        self.assertEqual(audit_count_after_first, audit_count_after_second)

    def test_get_returns_signed_status_after_signing(self):
        AIDPAStatus.objects.filter(tenant=self.__class__.tenant).delete()
        self._auth(self.admin)
        self.client.post("/api/v1/settings/dpa/sign/")
        resp = self.client.get("/api/v1/settings/dpa/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["is_signed"])
        self.assertIsNotNone(data["signed_at"])
        self.assertEqual(data["signed_by_name"], self.admin.full_name)

    def test_get_requires_authentication(self):
        resp = self.client.get("/api/v1/settings/dpa/")
        self.assertEqual(resp.status_code, 401)

    def test_post_requires_authentication(self):
        resp = self.client.post("/api/v1/settings/dpa/sign/")
        self.assertEqual(resp.status_code, 401)
