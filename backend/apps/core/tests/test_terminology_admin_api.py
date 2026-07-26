"""
A1-T2 / A1-T3 — terminology catalog platform-admin API.

Covers:
  * list/paginate each governed catalog (CBO/CNES/LOINC/UCUM) — platform admin;
  * import-status summary (row count + last import run);
  * trigger a catalog import from a CSV upload;
  * gating: non-superusers get 403 on every endpoint.

The catalogs + their import logs live in the PUBLIC schema, so these routes are
served from ``urls_public`` — the default APIClient host (testserver → public)
is correct here, exactly like ``test_platform_api``.
"""

from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.core.cbo_cnes_models import CBOCode, CNESEstablishment
from apps.core.loinc_models import LoincCode, UcumUnit
from apps.core.models import Role, User
from apps.core.terminology_base import TerminologyImportLog
from apps.test_utils import TenantTestCase


class TerminologyAdminAPITestCase(TenantTestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_superuser(
            email="platform@vitali.com",
            password="PlatformAdmin123!",
            full_name="Platform Admin",
        )
        role = Role.objects.create(name="admin", permissions=["users.read"])
        self.staff_user = User.objects.create_user(
            email="staff@clinic.com",
            password="Staff123!",
            full_name="Staff",
            role=role,
            is_staff=True,
        )

        CBOCode.objects.create(code="225125", display="Médico clínico", family="2251")
        CBOCode.objects.create(code="223505", display="Enfermeiro", family="2235")
        CNESEstablishment.objects.create(code="2077469", display="Hospital São Lucas")
        LoincCode.objects.create(code="718-7", display="Hemoglobin [Mass/volume] in Blood")
        UcumUnit.objects.create(code="mg/dL", display="milligram per deciliter")

    # ── A1-T2: list/paginate ──────────────────────────────────────────────────

    def test_list_cbo_returns_paginated(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.get("/api/v1/platform/terminology/cbo/")
        self.assertEqual(resp.status_code, 200)
        # StandardResultsSetPagination → {"count", "results", ...}
        self.assertIn("results", resp.data)
        codes = [r["code"] for r in resp.data["results"]]
        self.assertIn("225125", codes)
        self.assertIn("223505", codes)

    def test_list_each_catalog_ok(self):
        self.client.force_authenticate(user=self.admin)
        for system in ("cbo", "cnes", "loinc", "ucum"):
            resp = self.client.get(f"/api/v1/platform/terminology/{system}/")
            self.assertEqual(resp.status_code, 200, system)

    def test_list_gated_to_platform_admin(self):
        self.client.force_authenticate(user=self.staff_user)
        resp = self.client.get("/api/v1/platform/terminology/cbo/")
        self.assertEqual(resp.status_code, 403)

    def test_list_requires_auth(self):
        resp = self.client.get("/api/v1/platform/terminology/cbo/")
        self.assertIn(resp.status_code, (401, 403))

    # ── A1-T2: import-status summary ──────────────────────────────────────────

    def test_import_status_summary(self):
        TerminologyImportLog.objects.create(
            system="cbo",
            status=TerminologyImportLog.Status.SUCCESS,
            row_count_total=2,
            row_count_added=2,
        )
        self.client.force_authenticate(user=self.admin)
        resp = self.client.get("/api/v1/platform/terminology/import-status/")
        self.assertEqual(resp.status_code, 200)
        by_system = {r["system"]: r for r in resp.data}
        self.assertEqual(set(by_system), {"cbo", "cnes", "loinc", "ucum"})
        self.assertEqual(by_system["cbo"]["row_count"], 2)
        self.assertIsNotNone(by_system["cbo"]["last_import_at"])
        # No import log for ucum → last_import_at is null but row_count present.
        self.assertEqual(by_system["ucum"]["row_count"], 1)
        self.assertIsNone(by_system["ucum"]["last_import_at"])

    def test_import_status_gated(self):
        self.client.force_authenticate(user=self.staff_user)
        resp = self.client.get("/api/v1/platform/terminology/import-status/")
        self.assertEqual(resp.status_code, 403)

    # ── A1-T3: trigger import from CSV upload ─────────────────────────────────

    def _cbo_csv(self) -> SimpleUploadedFile:
        content = "CODIGO;TITULO;FAMILIA\n251510;Psicólogo clínico;2515\n".encode()
        return SimpleUploadedFile("cbo.csv", content, content_type="text/csv")

    def test_import_trigger_happy_path(self):
        self.client.force_authenticate(user=self.admin)
        self.assertFalse(CBOCode.objects.filter(code="251510").exists())
        resp = self.client.post(
            "/api/v1/platform/terminology/cbo/import/",
            {"file": self._cbo_csv()},
            format="multipart",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertTrue(CBOCode.objects.filter(code="251510").exists())
        self.assertEqual(resp.data["system"], "cbo")

    def test_import_trigger_gated(self):
        self.client.force_authenticate(user=self.staff_user)
        resp = self.client.post(
            "/api/v1/platform/terminology/cbo/import/",
            {"file": self._cbo_csv()},
            format="multipart",
        )
        self.assertEqual(resp.status_code, 403)

    def test_import_trigger_missing_file_400(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.post("/api/v1/platform/terminology/cbo/import/", {}, format="multipart")
        self.assertEqual(resp.status_code, 400)

    def test_import_trigger_unknown_system_404(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.post(
            "/api/v1/platform/terminology/bogus/import/",
            {"file": self._cbo_csv()},
            format="multipart",
        )
        self.assertEqual(resp.status_code, 404)
