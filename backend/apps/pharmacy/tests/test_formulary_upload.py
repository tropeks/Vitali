"""Tests for the pharmacist-facing formulary CSV upload API (D-T1).

Covers the two stateless endpoints behind the upload UI:
  * POST /api/v1/pharmacy/formulary/upload/preview/  (dry-run, writes nothing)
  * POST /api/v1/pharmacy/formulary/upload/commit/   (real idempotent upsert)

ILLUSTRATIVE TEST DATA — NOT CLINICAL TRUTH. All drug names / strengths / dose
values come from the fabricated fixtures and MUST NOT be copied into production.
"""

import os

from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.core.models import AuditLog, FeatureFlag
from apps.core.permissions import DEFAULT_ROLES
from apps.pharmacy.models import DoseRule, MedicationFormulary
from apps.test_utils import TenantTestCase

_FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
_SAMPLE_CSV = os.path.join(_FIXTURES_DIR, "formulary_sample.csv")
_MALFORMED_CSV = os.path.join(_FIXTURES_DIR, "formulary_malformed.csv")

_PREVIEW_URL = "/api/v1/pharmacy/formulary/upload/preview/"
_COMMIT_URL = "/api/v1/pharmacy/formulary/upload/commit/"


def _csv_upload(path: str, name: str = "formulary.csv") -> SimpleUploadedFile:
    with open(path, "rb") as fh:
        return SimpleUploadedFile(name, fh.read(), content_type="text/csv")


class TestFormularyUploadAPI(TenantTestCase):
    def setUp(self):
        from apps.core.models import Role, User

        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key="pharmacy",
            defaults={"is_enabled": True},
        )
        self.role_farmaceutico = Role.objects.create(
            name="farmaceutico",
            permissions=DEFAULT_ROLES["farmaceutico"],
        )
        self.role_recepcionista = Role.objects.create(
            name="recepcionista",
            permissions=DEFAULT_ROLES["recepcionista"],
        )
        self.farmaceutico = User.objects.create_user(
            email="farm@upload.test", password="pw", role=self.role_farmaceutico
        )
        self.recepcionista = User.objects.create_user(
            email="recep@upload.test", password="pw", role=self.role_recepcionista
        )

    def _client(self, user):
        c = APIClient()
        c.defaults["SERVER_NAME"] = self.__class__.domain.domain
        c.force_authenticate(user=user)
        return c

    # ── preview ───────────────────────────────────────────────────────────────

    def test_preview_valid_csv_writes_nothing(self):
        """Preview returns parsed rows + a dry-run summary but persists no rows."""
        resp = self._client(self.farmaceutico).post(
            _PREVIEW_URL, {"file": _csv_upload(_SAMPLE_CSV)}, format="multipart"
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()

        # 3 data rows in formulary_sample.csv.
        self.assertEqual(len(body["rows"]), 3)
        self.assertEqual(body["summary"]["row_count"], 3)
        self.assertEqual(body["summary"]["rules_created"], 3)
        self.assertEqual(body["errors"], [])

        # Dry-run: absolutely nothing committed.
        self.assertEqual(MedicationFormulary.objects.count(), 0)
        self.assertEqual(DoseRule.objects.count(), 0)

    def test_preview_malformed_csv_returns_line_errors(self):
        """A malformed CSV → 400 with line-numbered errors and no partial write."""
        resp = self._client(self.farmaceutico).post(
            _PREVIEW_URL, {"file": _csv_upload(_MALFORMED_CSV)}, format="multipart"
        )
        self.assertEqual(resp.status_code, 400)
        body = resp.json()
        self.assertTrue(body["errors"], "expected a non-empty errors list")
        self.assertTrue(any("Line 4" in e for e in body["errors"]))
        self.assertEqual(MedicationFormulary.objects.count(), 0)
        self.assertEqual(DoseRule.objects.count(), 0)

    def test_preview_missing_file_400(self):
        resp = self._client(self.farmaceutico).post(_PREVIEW_URL, {}, format="multipart")
        self.assertEqual(resp.status_code, 400)

    # ── commit ──────────────────────────────────────────────────────────────

    def test_commit_creates_rows_unvalidated_and_audits(self):
        """Commit persists formularies + rules (validated=False) and writes audit."""
        resp = self._client(self.farmaceutico).post(
            _COMMIT_URL, {"file": _csv_upload(_SAMPLE_CSV)}, format="multipart"
        )
        self.assertEqual(resp.status_code, 201, resp.content)

        self.assertEqual(MedicationFormulary.objects.count(), 3)
        self.assertEqual(DoseRule.objects.count(), 3)

        # INVIOLABLE: importer never self-validates — human sign-off arms the rule.
        for rule in DoseRule.objects.all():
            self.assertFalse(rule.validated)
            self.assertIsNone(rule.validated_by_id)

        logs = AuditLog.objects.filter(action="formulary_imported")
        self.assertEqual(logs.count(), 1)

    def test_commit_honours_enforcement_column(self):
        """A per-drug enforcement (block/advise) is imported, not defaulted to block.

        Critical for dose_safety correctness: opioids/sedatives marked 'advise'
        must NOT be imported as hard-blocking. Blank/missing → 'block' (safe).
        """
        csv = (
            "drug_name,drug_generic,strength_value,strength_unit,route,basis,"
            "dose_unit,min_per_dose,max_per_dose,absolute_max_dose,dose_role,enforcement\n"
            "FAKE-Blocker,fake_blocker,10.000,mg,IV,fixed,mg,5,15,15,maintenance,block\n"
            "FAKE-Adviser,fake_adviser,10.000,mg,IV,fixed,mg,5,15,15,maintenance,advise\n"
            "FAKE-Default,fake_default,10.000,mg,IV,fixed,mg,5,15,15,maintenance,\n"
        )
        upload = SimpleUploadedFile("enf.csv", csv.encode("utf-8"), content_type="text/csv")
        resp = self._client(self.farmaceutico).post(
            _COMMIT_URL, {"file": upload}, format="multipart"
        )
        self.assertEqual(resp.status_code, 201, resp.content)

        by_drug = {r.formulary.drug.name: r.enforcement for r in DoseRule.objects.all()}
        self.assertEqual(by_drug["FAKE-Blocker"], "block")
        self.assertEqual(by_drug["FAKE-Adviser"], "advise")
        self.assertEqual(by_drug["FAKE-Default"], "block")  # blank → safe default

    def test_commit_rejects_invalid_enforcement(self):
        """An unknown enforcement value is a 400 with no partial import."""
        csv = (
            "drug_name,drug_generic,strength_value,strength_unit,route,basis,"
            "dose_unit,min_per_dose,max_per_dose,absolute_max_dose,dose_role,enforcement\n"
            "FAKE-Bad,fake_bad,10.000,mg,IV,fixed,mg,5,15,15,maintenance,kaboom\n"
        )
        upload = SimpleUploadedFile("bad.csv", csv.encode("utf-8"), content_type="text/csv")
        resp = self._client(self.farmaceutico).post(
            _COMMIT_URL, {"file": upload}, format="multipart"
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(DoseRule.objects.count(), 0)

    def test_commit_is_idempotent(self):
        """Committing the same CSV twice must not duplicate rows."""
        client = self._client(self.farmaceutico)
        client.post(_COMMIT_URL, {"file": _csv_upload(_SAMPLE_CSV)}, format="multipart")
        client.post(_COMMIT_URL, {"file": _csv_upload(_SAMPLE_CSV)}, format="multipart")

        self.assertEqual(MedicationFormulary.objects.count(), 3)
        self.assertEqual(DoseRule.objects.count(), 3)

    def test_commit_malformed_csv_no_partial_import(self):
        resp = self._client(self.farmaceutico).post(
            _COMMIT_URL, {"file": _csv_upload(_MALFORMED_CSV)}, format="multipart"
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(MedicationFormulary.objects.count(), 0)
        self.assertEqual(DoseRule.objects.count(), 0)

    # ── permissions ──────────────────────────────────────────────────────────

    def test_recepcionista_cannot_preview_or_commit(self):
        """Lacking pharmacy.catalog_manage → 403 on both endpoints."""
        client = self._client(self.recepcionista)
        prev = client.post(_PREVIEW_URL, {"file": _csv_upload(_SAMPLE_CSV)}, format="multipart")
        self.assertEqual(prev.status_code, 403)
        commit = client.post(_COMMIT_URL, {"file": _csv_upload(_SAMPLE_CSV)}, format="multipart")
        self.assertEqual(commit.status_code, 403)
        self.assertEqual(DoseRule.objects.count(), 0)
