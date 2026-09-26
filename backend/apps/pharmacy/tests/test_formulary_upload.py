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
            "dose_unit,min_per_dose,max_per_dose,absolute_max_dose,dose_role,enforcement,"
            "fonte_tipo,fonte_ref,fonte_trecho\n"
            "FAKE-Blocker,fake_blocker,10.000,mg,IV,fixed,mg,5,15,15,maintenance,block,literatura,DOI:10.0000/fake,Trecho ficticio de teste\n"
            "FAKE-Adviser,fake_adviser,10.000,mg,IV,fixed,mg,5,15,15,maintenance,advise,literatura,DOI:10.0000/fake,Trecho ficticio de teste\n"
            "FAKE-Default,fake_default,10.000,mg,IV,fixed,mg,5,15,15,maintenance,,literatura,DOI:10.0000/fake,Trecho ficticio de teste\n"
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
            "dose_unit,min_per_dose,max_per_dose,absolute_max_dose,dose_role,enforcement,"
            "fonte_tipo,fonte_ref,fonte_trecho\n"
            "FAKE-Bad,fake_bad,10.000,mg,IV,fixed,mg,5,15,15,maintenance,kaboom,literatura,DOI:10.0000/fake,Trecho ficticio de teste\n"
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

    def test_reimport_changed_clinical_values_resets_validation(self):
        """SAFETY GATE: re-importing changed clinical values de-arms a validated rule.

        The new numbers were never signed off — they must NOT enter the
        DoseChecker armed, and validated_by/at must not keep pointing at the
        pharmacist who approved the OLD values. The summary must surface the
        count so the UI can warn before commit.
        """
        from django.utils import timezone

        header = (
            "drug_name,drug_generic,strength_value,strength_unit,route,basis,"
            "dose_unit,min_per_dose,max_per_dose,absolute_max_dose,dose_role,enforcement,"
            "fonte_tipo,fonte_ref,fonte_trecho\n"
        )
        csv_v1 = (
            header
            + "FAKE-Reval,fake_reval,10.000,mg,IV,fixed,mg,5,15,15,maintenance,block,literatura,DOI:10.0000/fake,Trecho ficticio de teste\n"
        )
        csv_v2 = (
            header
            + "FAKE-Reval,fake_reval,10.000,mg,IV,fixed,mg,5,20,20,maintenance,block,literatura,DOI:10.0000/fake,Trecho ficticio de teste\n"
        )

        client = self._client(self.farmaceutico)
        resp = client.post(
            _COMMIT_URL,
            {"file": SimpleUploadedFile("v1.csv", csv_v1.encode(), content_type="text/csv")},
            format="multipart",
        )
        self.assertEqual(resp.status_code, 201, resp.content)

        # Pharmacist signs off the imported rule (simulating the curation UI).
        rule = DoseRule.objects.get()
        rule.validated = True
        rule.validated_by = self.farmaceutico
        rule.validated_at = timezone.now()
        rule.save(update_fields=["status_validacao", "validated_by", "validated_at"])

        # Preview of the changed CSV surfaces the warning count — and persists nothing.
        preview = client.post(
            _PREVIEW_URL,
            {"file": SimpleUploadedFile("v2.csv", csv_v2.encode(), content_type="text/csv")},
            format="multipart",
        )
        self.assertEqual(preview.status_code, 200, preview.content)
        self.assertEqual(preview.json()["summary"]["revalidation_required"], 1)
        rule.refresh_from_db()
        self.assertTrue(rule.validated)  # dry-run must not de-arm anything

        # Commit of the changed CSV resets the sign-off entirely.
        resp = client.post(
            _COMMIT_URL,
            {"file": SimpleUploadedFile("v2.csv", csv_v2.encode(), content_type="text/csv")},
            format="multipart",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.json()["summary"]["revalidation_required"], 1)

        rule.refresh_from_db()
        self.assertFalse(rule.validated)
        self.assertIsNone(rule.validated_by_id)
        self.assertIsNone(rule.validated_at)
        self.assertEqual(str(rule.max_per_dose), "20.0000")

        # Audit log carries before/after per changed rule (forensics).
        log = AuditLog.objects.filter(action="formulary_imported").latest("created_at")
        changed = log.new_data["changed_rules"]
        self.assertEqual(len(changed), 1)
        self.assertEqual(changed[0]["drug"], "FAKE-Reval")
        self.assertTrue(changed[0]["was_validated"])
        self.assertEqual(changed[0]["changes"]["max_per_dose"]["after"], "20")

    def test_reimport_identical_csv_keeps_validation(self):
        """Idempotent re-import of IDENTICAL values must NOT reset the sign-off."""
        from django.utils import timezone

        client = self._client(self.farmaceutico)
        client.post(_COMMIT_URL, {"file": _csv_upload(_SAMPLE_CSV)}, format="multipart")

        rule = DoseRule.objects.first()
        rule.validated = True
        rule.validated_by = self.farmaceutico
        rule.validated_at = timezone.now()
        rule.save(update_fields=["status_validacao", "validated_by", "validated_at"])

        resp = client.post(_COMMIT_URL, {"file": _csv_upload(_SAMPLE_CSV)}, format="multipart")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.json()["summary"]["revalidation_required"], 0)

        rule.refresh_from_db()
        self.assertTrue(rule.validated)
        self.assertEqual(rule.validated_by_id, self.farmaceutico.id)

    def test_out_of_range_strength_is_line_error_not_500(self):
        """strength_value beyond max_digits / strength_unit beyond max_length →
        per-line 400 errors (fail-loud contract), never a DB-level exception."""
        header = (
            "drug_name,drug_generic,strength_value,strength_unit,route,basis,"
            "dose_unit,min_per_dose,max_per_dose,absolute_max_dose,dose_role,enforcement,"
            "fonte_tipo,fonte_ref,fonte_trecho\n"
        )
        csv = (
            header
            # strength_value: 11 integer digits > max_digits=10 (with 3 decimal places)
            + "FAKE-BigVal,fake_big,12345678901,mg,IV,fixed,mg,5,15,15,maintenance,block,literatura,DOI:10.0000/fake,Trecho ficticio de teste\n"
            # strength_unit: 11 chars > max_length=10 (also not a valid choice)
            + "FAKE-BigUnit,fake_unit,10.000,miligramas!,IV,fixed,mg,5,15,15,maintenance,block,literatura,DOI:10.0000/fake,Trecho ficticio de teste\n"
        )
        upload = SimpleUploadedFile("range.csv", csv.encode(), content_type="text/csv")
        resp = self._client(self.farmaceutico).post(
            _COMMIT_URL, {"file": upload}, format="multipart"
        )
        self.assertEqual(resp.status_code, 400, resp.content)
        body = resp.json()
        self.assertTrue(any("Line 2" in e and "strength_value" in e for e in body["errors"]))
        self.assertTrue(any("Line 3" in e and "strength_unit" in e for e in body["errors"]))
        self.assertEqual(MedicationFormulary.objects.count(), 0)
        self.assertEqual(DoseRule.objects.count(), 0)

    def test_upload_accepts_cp1252_encoded_csv(self):
        """Excel Windows PT-BR exports cp1252 — the upload must decode it."""
        header = (
            "drug_name,drug_generic,strength_value,strength_unit,route,basis,"
            "dose_unit,min_per_dose,max_per_dose,absolute_max_dose,dose_role,enforcement,"
            "fonte_tipo,fonte_ref,fonte_trecho\n"
        )
        csv = (
            header
            + "FAKE-Acentuação,fake_acentuação,10.000,mg,IV,fixed,mg,5,15,15,maintenance,block,literatura,DOI:10.0000/fake,Trecho ficticio de teste\n"
        )
        upload = SimpleUploadedFile("cp1252.csv", csv.encode("cp1252"), content_type="text/csv")
        resp = self._client(self.farmaceutico).post(
            _PREVIEW_URL, {"file": upload}, format="multipart"
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["rows"][0]["drug_name"], "FAKE-Acentuação")

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

    # ── ordem 028: procedência obrigatória ────────────────────────────────────

    def test_missing_fonte_tipo_rejects_whole_import(self):
        """A row without fonte_tipo/fonte_ref/fonte_trecho fails the WHOLE
        import — no number may claim to come from nowhere."""
        header = (
            "drug_name,drug_generic,strength_value,strength_unit,route,basis,"
            "dose_unit,min_per_dose,max_per_dose,absolute_max_dose,dose_role,enforcement\n"
        )
        csv = header + "FAKE-NoProv,fake_noprov,10.000,mg,IV,fixed,mg,5,15,15,maintenance,block\n"
        upload = SimpleUploadedFile("noprov.csv", csv.encode(), content_type="text/csv")
        resp = self._client(self.farmaceutico).post(
            _COMMIT_URL, {"file": upload}, format="multipart"
        )
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(
            any("fonte_tipo" in e for e in resp.json()["errors"]),
            resp.json()["errors"],
        )
        self.assertEqual(DoseRule.objects.count(), 0)

    def test_invalid_fonte_tipo_value_rejected(self):
        header = (
            "drug_name,drug_generic,strength_value,strength_unit,route,basis,"
            "dose_unit,min_per_dose,max_per_dose,absolute_max_dose,dose_role,enforcement,"
            "fonte_tipo,fonte_ref,fonte_trecho\n"
        )
        csv = (
            header + "FAKE-BadProv,fake_badprov,10.000,mg,IV,fixed,mg,5,15,15,maintenance,block,"
            "boato,ref,trecho\n"
        )
        upload = SimpleUploadedFile("badprov.csv", csv.encode(), content_type="text/csv")
        resp = self._client(self.farmaceutico).post(
            _COMMIT_URL, {"file": upload}, format="multipart"
        )
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(any("fonte_tipo" in e for e in resp.json()["errors"]))

    def test_commit_stores_procedencia_fields(self):
        resp = self._client(self.farmaceutico).post(
            _COMMIT_URL, {"file": _csv_upload(_SAMPLE_CSV)}, format="multipart"
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        rule = DoseRule.objects.get(formulary__drug__name="FAKE-ImportDrugA")
        self.assertEqual(rule.fonte_tipo, "literatura")
        self.assertEqual(rule.fonte_ref, "DOI:10.0000/fake-import-a")
        self.assertIn("Trecho ficticio", rule.fonte_trecho)

    # ── ordem 028: fonte sintética recusada fora de teste ─────────────────────

    def test_synthetic_header_is_refused_by_default(self):
        from apps.pharmacy.services.formulary_import import (
            FormularyImportError,
            parse_and_validate,
        )

        csv = (
            "# sintetico: true\n"
            "drug_name,drug_generic,strength_value,strength_unit,route,basis,"
            "dose_unit,min_per_dose,max_per_dose,absolute_max_dose,dose_role,enforcement,"
            "fonte_tipo,fonte_ref,fonte_trecho\n"
            "FAKE-Synthetic,fake_syn,10.000,mg,IV,fixed,mg,1,2,2,maintenance,block,"
            "literatura,DOI:x,trecho\n"
        )
        with self.assertRaises(FormularyImportError) as ctx:
            parse_and_validate(csv)
        self.assertTrue(any("sintética" in e for e in ctx.exception.errors))

    def test_synthetic_header_allowed_with_explicit_flag(self):
        from apps.pharmacy.services.formulary_import import parse_and_validate

        csv = (
            "# sintetico: true\n"
            "drug_name,drug_generic,strength_value,strength_unit,route,basis,"
            "dose_unit,min_per_dose,max_per_dose,absolute_max_dose,dose_role,enforcement,"
            "fonte_tipo,fonte_ref,fonte_trecho\n"
            "FAKE-Synthetic,fake_syn,10.000,mg,IV,fixed,mg,1,2,2,maintenance,block,"
            "literatura,DOI:x,trecho\n"
        )
        rows = parse_and_validate(csv, allow_synthetic=True)
        self.assertEqual(len(rows), 1)

    def test_upload_ui_never_allows_synthetic(self):
        """The upload endpoints call parse_and_validate WITHOUT allow_synthetic
        — a synthetic-marked file is refused even by an authorized pharmacist."""
        csv = (
            "# sintetico: true\n"
            "drug_name,drug_generic,strength_value,strength_unit,route,basis,"
            "dose_unit,min_per_dose,max_per_dose,absolute_max_dose,dose_role,enforcement,"
            "fonte_tipo,fonte_ref,fonte_trecho\n"
            "FAKE-Synthetic,fake_syn,10.000,mg,IV,fixed,mg,1,2,2,maintenance,block,"
            "literatura,DOI:x,trecho\n"
        )
        upload = SimpleUploadedFile("syn.csv", csv.encode(), content_type="text/csv")
        resp = self._client(self.farmaceutico).post(
            _COMMIT_URL, {"file": upload}, format="multipart"
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(DoseRule.objects.count(), 0)

    # ── ordem 028: reimportação que desvalida ─────────────────────────────────

    def test_reimport_changed_values_writes_dedicated_invalidation_audit(self):
        """On top of the existing formulary_imported summary audit, a validated
        rule whose numbers changed gets its OWN dose_rule_invalidated_by_import
        AuditLog row, and its CRF portrait is cleared."""
        from django.utils import timezone

        header = (
            "drug_name,drug_generic,strength_value,strength_unit,route,basis,"
            "dose_unit,min_per_dose,max_per_dose,absolute_max_dose,dose_role,enforcement,"
            "fonte_tipo,fonte_ref,fonte_trecho\n"
        )
        csv_v1 = (
            header + "FAKE-Reval2,fake_reval2,10.000,mg,IV,fixed,mg,5,15,15,maintenance,block,"
            "literatura,DOI:x,trecho\n"
        )
        csv_v2 = (
            header + "FAKE-Reval2,fake_reval2,10.000,mg,IV,fixed,mg,5,20,20,maintenance,block,"
            "literatura,DOI:x,trecho\n"
        )

        client = self._client(self.farmaceutico)
        client.post(
            _COMMIT_URL,
            {"file": SimpleUploadedFile("v1.csv", csv_v1.encode(), content_type="text/csv")},
            format="multipart",
        )
        rule = DoseRule.objects.get(formulary__drug__name="FAKE-Reval2")
        rule.validated = True
        rule.validated_by = self.farmaceutico
        rule.validated_at = timezone.now()
        rule.validado_crf_numero = "555555"
        rule.validado_crf_uf = "SP"
        rule.save(
            update_fields=[
                "status_validacao",
                "validated_by",
                "validated_at",
                "validado_crf_numero",
                "validado_crf_uf",
            ]
        )

        resp = client.post(
            _COMMIT_URL,
            {"file": SimpleUploadedFile("v2.csv", csv_v2.encode(), content_type="text/csv")},
            format="multipart",
        )
        self.assertEqual(resp.status_code, 201, resp.content)

        rule.refresh_from_db()
        self.assertFalse(rule.validated)
        self.assertEqual(rule.validado_crf_numero, "")
        self.assertEqual(rule.validado_crf_uf, "")

        log = AuditLog.objects.get(
            action="dose_rule_invalidated_by_import", resource_id=str(rule.id)
        )
        self.assertEqual(log.old_data["status_validacao"], "validado")
        self.assertEqual(log.new_data["status_validacao"], "nao_validado")
        self.assertEqual(log.new_data["changes"]["max_per_dose"]["before"], "15.0000")
        self.assertEqual(log.new_data["changes"]["max_per_dose"]["after"], "20")

    def test_reimport_unchanged_values_writes_no_invalidation_audit(self):
        """Idempotent re-import of identical values: no
        dose_rule_invalidated_by_import row at all."""
        from django.utils import timezone

        client = self._client(self.farmaceutico)
        client.post(_COMMIT_URL, {"file": _csv_upload(_SAMPLE_CSV)}, format="multipart")
        rule = DoseRule.objects.first()
        rule.validated = True
        rule.validated_by = self.farmaceutico
        rule.validated_at = timezone.now()
        rule.save(update_fields=["status_validacao", "validated_by", "validated_at"])

        client.post(_COMMIT_URL, {"file": _csv_upload(_SAMPLE_CSV)}, format="multipart")

        self.assertFalse(AuditLog.objects.filter(action="dose_rule_invalidated_by_import").exists())
        rule.refresh_from_db()
        self.assertTrue(rule.validated)
