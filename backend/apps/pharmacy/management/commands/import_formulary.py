"""
Management command: import_formulary
=====================================
Imports a dose-formulary CSV into pharmacy.MedicationFormulary + pharmacy.DoseRule.

Usage:
    python manage.py import_formulary --file formulary.csv
    python manage.py import_formulary --file formulary.csv --dry-run
    python manage.py import_formulary --file formulary.csv --delimiter ,

INVIOLABLE PRINCIPLE: no clinical number is invented here. The importer only
reads what the CSV provides. Imported DoseRules are NEVER self-validated —
validated=False is the default and must remain so until a human pharmacist
reviews and validates each rule via the UI.

This command is a thin CLI wrapper around
``apps.pharmacy.services.formulary_import`` — the SAME parse/validate/upsert
service used by the pharmacist-facing upload UI (D-T1), so both paths share one
implementation and one set of invariants.

Behaviour:
  - Idempotent: MedicationFormulary update_or_create by drug name; DoseRule
    update_or_create by natural key (formulary + basis + dose_role + route +
    freq_min_per_day + freq_max_per_day + age_min_days + age_max_days +
    weight_min_kg + weight_max_kg).
  - Fail-loud: per-line validation; ALL errors are collected, then a single
    CommandError is raised BEFORE any commit. No silent partial imports.
  - --dry-run: performs validation + ORM work inside a transaction that is
    always rolled back; prints a summary and exits cleanly.
  - Lines starting with '#' are treated as comments and skipped.
  - Physical line numbers (1-based, counting comment lines) are reported in
    error messages so operators can find the bad row in any editor.

Expected CSV columns (comma-delimited by default):
    drug_name          — maps to Drug.name (get_or_create by name)
    drug_generic       — Drug.generic_name (optional, blank if missing)
    strength_value     — MedicationFormulary.strength_value (Decimal)
    strength_unit      — MedicationFormulary.strength_unit
    route              — MedicationFormulary.route (IV/IM/SC/PO)
    basis              — DoseRule.basis (per_kg / fixed)
    dose_unit          — DoseRule.dose_unit
    min_per_dose       — DoseRule.min_per_dose  (required when basis=fixed)
    max_per_dose       — DoseRule.max_per_dose  (required when basis=fixed)
    absolute_max_dose  — DoseRule.absolute_max_dose (always required)
    min_per_kg         — DoseRule.min_per_kg    (required when basis=per_kg)
    max_per_kg         — DoseRule.max_per_kg    (required when basis=per_kg)
    max_per_day        — DoseRule.max_per_day   (optional decimal)
    dose_role          — DoseRule.dose_role     (maintenance/loading; default maintenance)
    enforcement        — DoseRule.enforcement   (block/advise; optional, default block)
    freq_min_per_day   — DoseRule.freq_min_per_day (optional integer)
    freq_max_per_day   — DoseRule.freq_max_per_day (optional integer)
    age_min_days       — DoseRule.age_min_days  (optional integer; blank → None = unbounded)
    age_max_days       — DoseRule.age_max_days  (optional integer; blank → None = unbounded)
    weight_min_kg      — DoseRule.weight_min_kg (optional decimal; blank → None = unbounded)
    weight_max_kg      — DoseRule.weight_max_kg (optional decimal; blank → None = unbounded)
"""

import logging
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django_tenants.utils import get_public_schema_name

from apps.pharmacy.services.formulary_import import (
    FormularyImportError,
    parse_and_validate,
    write_rows,
)

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Import dose formulary from a CSV file into MedicationFormulary + DoseRule"

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            required=True,
            help="Path to the formulary CSV file",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Validate and show what would be imported without writing to the database",
        )
        parser.add_argument(
            "--delimiter",
            default=",",
            help="CSV column delimiter (default: ,)",
        )

    def handle(self, *args, **options):
        # ── Tenant-schema guard ───────────────────────────────────────────────────
        # Pharmacy models are TENANT_APPS — they live in per-tenant schemas. Running
        # this command without a tenant context would silently write to the public
        # schema. Refuse loudly instead.
        if connection.schema_name == get_public_schema_name():
            raise CommandError(
                "import_formulary must run inside a tenant schema "
                "(use --schema=<tenant> or tenant_context); "
                "refusing to write pharmacy data to the public schema."
            )

        csv_path = Path(options["file"])
        if not csv_path.exists():
            raise CommandError(f"File not found: {csv_path}")

        dry_run = options["dry_run"]
        delimiter = options["delimiter"]

        self.stdout.write(f"Importing formulary from {csv_path} (dry_run={dry_run}) …")

        # utf-8-sig strips a leading BOM (common from spreadsheet exports).
        content = csv_path.read_text(encoding="utf-8-sig")

        try:
            parsed_rows = parse_and_validate(content, delimiter=delimiter)
        except FormularyImportError as exc:
            error_report = "\n".join(f"  {err}" for err in exc.errors)
            raise CommandError(
                f"Import aborted — {len(exc.errors)} error(s) found. "
                f"No rows were committed.\n{error_report}"
            ) from exc

        summary = write_rows(parsed_rows, dry_run=dry_run)

        action = "Would import" if dry_run else "Done"
        self.stdout.write(
            self.style.SUCCESS(
                f"{action}. "
                f"Formularies: {summary.formularies_created} created, "
                f"{summary.formularies_updated} updated. "
                f"DoseRules: {summary.rules_created} created, {summary.rules_updated} updated."
            )
        )
