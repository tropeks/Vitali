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

Behaviour:
  - Idempotent: MedicationFormulary update_or_create by drug name; DoseRule
    update_or_create by natural key (formulary + basis + dose_role + route +
    freq_min_per_day + freq_max_per_day + age_min_days + age_max_days +
    weight_min_kg + weight_max_kg).
  - Fail-loud: per-line validation via instance.full_clean(); ALL errors are
    collected, then a single CommandError is raised BEFORE any commit. No
    silent partial imports.
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
    dose_role          — DoseRule.dose_role     (maintenance/loading; default maintenance)
    freq_min_per_day   — DoseRule.freq_min_per_day (optional integer)
    freq_max_per_day   — DoseRule.freq_max_per_day (optional integer)
    age_min_days       — DoseRule.age_min_days  (optional integer; blank → None = unbounded)
    age_max_days       — DoseRule.age_max_days  (optional integer; blank → None = unbounded)
    weight_min_kg      — DoseRule.weight_min_kg (optional decimal; blank → None = unbounded)
    weight_max_kg      — DoseRule.weight_max_kg (optional decimal; blank → None = unbounded)
"""

import csv
import logging
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django_tenants.utils import get_public_schema_name

from apps.pharmacy.models import DoseRule, Drug, MedicationFormulary

logger = logging.getLogger(__name__)

# Natural-key fields for DoseRule update_or_create lookup (matches the
# doserule_natural_key UniqueConstraint in DoseRule.Meta; includes all four
# age/weight band fields so rules differing only by patient band are not
# collapsed on re-import).
_DOSERULE_NATURAL_KEY = (
    "basis",
    "dose_role",
    "route",
    "freq_min_per_day",
    "freq_max_per_day",
    "age_min_days",
    "age_max_days",
    "weight_min_kg",
    "weight_max_kg",
)


def _opt_decimal(row: dict, col: str) -> Decimal | None:
    """Return a Decimal from a CSV cell, or None if the column is missing/empty."""
    raw = row.get(col, "").strip()
    if not raw:
        return None
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"column '{col}' is not a valid decimal: {raw!r}") from exc


def _opt_int(row: dict, col: str) -> int | None:
    """Return an int from a CSV cell, or None if the column is missing/empty."""
    raw = row.get(col, "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"column '{col}' is not a valid integer: {raw!r}") from exc


def _required_str(row: dict, col: str) -> str:
    """Return a stripped string from a CSV cell; raise ValueError if empty/missing."""
    raw = row.get(col, "").strip()
    if not raw:
        raise ValueError(f"required column '{col}' is missing or empty")
    return raw


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

        # Read all lines, keeping track of each line's 1-based physical index.
        # Comment lines (starting with '#') and blank lines are filtered out for
        # DictReader, but their physical line numbers are preserved so error
        # messages reference the TRUE position in the file.
        with open(csv_path, encoding="utf-8-sig", newline="") as fh:
            all_lines = list(fh)

        # physical_lines: list of (physical_line_number, line_text) for non-comment rows
        physical_lines = [
            (phys_idx + 1, ln)
            for phys_idx, ln in enumerate(all_lines)
            if not ln.lstrip().startswith("#")
        ]

        if not physical_lines:
            raise CommandError("CSV file is empty or contains only comments.")

        # Feed only the text to DictReader (first kept line is the header).
        kept_texts = [ln for _, ln in physical_lines]
        reader = csv.DictReader(kept_texts, delimiter=delimiter)
        rows = list(reader)

        if not rows:
            raise CommandError("CSV file has a header but no data rows.")

        # Map each data row (0-based index into rows) to its physical line number.
        # physical_lines[0] is the header; physical_lines[i+1] is data row i.
        def _physical_line(data_row_index: int) -> int:
            kept_idx = data_row_index + 1  # +1 to skip the header kept line
            if kept_idx < len(physical_lines):
                return physical_lines[kept_idx][0]
            return data_row_index + 2  # fallback (should not happen)

        # ── Per-line validation pass (collect ALL errors before committing) ──────
        line_errors: list[str] = []
        parsed_rows: list[dict] = []

        for data_idx, row in enumerate(rows):
            phys_line = _physical_line(data_idx)
            try:
                parsed = _parse_row(row, line_number=phys_line)
                parsed_rows.append(parsed)
            except (ValueError, KeyError) as exc:
                line_errors.append(f"  Line {phys_line}: {exc}")

        if line_errors:
            error_report = "\n".join(line_errors)
            raise CommandError(
                f"Import aborted — {len(line_errors)} error(s) found. "
                f"No rows were committed.\n{error_report}"
            )

        # ── Model-layer validation (full_clean) — still pre-commit ───────────────
        # Build ORM objects in-memory, call full_clean(), collect all errors.
        # We do NOT save yet — this is a dry validation pass.
        validation_errors: list[str] = []
        for entry in parsed_rows:
            rule_instance = DoseRule(
                # formulary FK intentionally left unset for this in-memory pass;
                # full_clean() will not raise on a missing FK in Django — the DB
                # constraint fires on save. We still catch field-level errors here.
                basis=entry["basis"],
                dose_role=entry["dose_role"],
                dose_unit=entry["dose_unit"],
                route=entry["route"],
                min_per_dose=entry.get("min_per_dose"),
                max_per_dose=entry.get("max_per_dose"),
                min_per_kg=entry.get("min_per_kg"),
                max_per_kg=entry.get("max_per_kg"),
                absolute_max_dose=entry["absolute_max_dose"],
                freq_min_per_day=entry.get("freq_min_per_day"),
                freq_max_per_day=entry.get("freq_max_per_day"),
                age_min_days=entry.get("age_min_days"),
                age_max_days=entry.get("age_max_days"),
                weight_min_kg=entry.get("weight_min_kg"),
                weight_max_kg=entry.get("weight_max_kg"),
                active=True,
                validated=False,  # NEVER self-validate; human sign-off required
            )
            try:
                rule_instance.full_clean(exclude=["formulary"])
            except ValidationError as exc:
                line_num = entry["_line_number"]
                validation_errors.append(f"  Line {line_num}: {exc.message_dict}")

        if validation_errors:
            error_report = "\n".join(validation_errors)
            raise CommandError(
                f"Import aborted — {len(validation_errors)} validation error(s). "
                f"No rows were committed.\n{error_report}"
            )

        # ── Database write pass (wrapped in a transaction) ────────────────────────
        formularies_created = formularies_updated = rules_created = rules_updated = 0

        with transaction.atomic():
            for entry in parsed_rows:
                # 1. Ensure the Drug exists (get_or_create by name).
                drug, _ = Drug.objects.get_or_create(
                    name=entry["drug_name"],
                    defaults={"generic_name": entry.get("drug_generic", "")},
                )

                # 2. Upsert the MedicationFormulary entry (one per drug).
                formulary, f_created = MedicationFormulary.objects.update_or_create(
                    drug=drug,
                    defaults={
                        "strength_value": entry["strength_value"],
                        "strength_unit": entry["strength_unit"],
                        "route": entry["route"],
                        "active": True,
                    },
                )
                if f_created:
                    formularies_created += 1
                else:
                    formularies_updated += 1

                # 3. Upsert the DoseRule by natural key.
                # The key includes all four band fields (age_min_days, age_max_days,
                # weight_min_kg, weight_max_kg) so rules differing only by patient
                # band are not collapsed — each band gets its own row. Django's
                # update_or_create handles None lookups as IS NULL, which combined
                # with nulls_distinct=False on the UniqueConstraint means NULL-band
                # rules also upsert correctly instead of accumulating duplicates.
                natural_key = {
                    "formulary": formulary,
                    "basis": entry["basis"],
                    "dose_role": entry["dose_role"],
                    "route": entry.get("route", ""),
                    "freq_min_per_day": entry.get("freq_min_per_day"),
                    "freq_max_per_day": entry.get("freq_max_per_day"),
                    "age_min_days": entry.get("age_min_days"),
                    "age_max_days": entry.get("age_max_days"),
                    "weight_min_kg": entry.get("weight_min_kg"),
                    "weight_max_kg": entry.get("weight_max_kg"),
                }
                rule_defaults = {
                    "dose_unit": entry["dose_unit"],
                    "min_per_dose": entry.get("min_per_dose"),
                    "max_per_dose": entry.get("max_per_dose"),
                    "min_per_kg": entry.get("min_per_kg"),
                    "max_per_kg": entry.get("max_per_kg"),
                    "absolute_max_dose": entry["absolute_max_dose"],
                    "active": True,
                    # validated stays False — human sign-off only, NEVER set by importer
                }
                _rule, r_created = DoseRule.objects.update_or_create(
                    **natural_key,
                    defaults=rule_defaults,
                )
                if r_created:
                    rules_created += 1
                else:
                    rules_updated += 1

            if dry_run:
                # Roll back everything — nothing persisted.
                transaction.set_rollback(True)

        action = "Would import" if dry_run else "Done"
        self.stdout.write(
            self.style.SUCCESS(
                f"{action}. "
                f"Formularies: {formularies_created} created, {formularies_updated} updated. "
                f"DoseRules: {rules_created} created, {rules_updated} updated."
            )
        )


def _parse_row(row: dict, *, line_number: int) -> dict:
    """Parse and validate one CSV row into a dict of typed values.

    Raises ValueError with a human-readable message on any parse failure.
    No clinical defaults are invented — every value comes from the CSV.
    """
    entry: dict = {"_line_number": line_number}

    entry["drug_name"] = _required_str(row, "drug_name")
    entry["drug_generic"] = row.get("drug_generic", "").strip()
    entry["strength_value"] = _opt_decimal(row, "strength_value")
    if entry["strength_value"] is None:
        raise ValueError("required column 'strength_value' is missing or empty")
    entry["strength_unit"] = _required_str(row, "strength_unit")
    entry["route"] = _required_str(row, "route")
    entry["basis"] = _required_str(row, "basis")
    if entry["basis"] not in ("per_kg", "fixed"):
        raise ValueError(f"column 'basis' must be 'per_kg' or 'fixed', got {entry['basis']!r}")
    entry["dose_unit"] = _required_str(row, "dose_unit")
    entry["dose_role"] = row.get("dose_role", "maintenance").strip() or "maintenance"

    entry["absolute_max_dose"] = _opt_decimal(row, "absolute_max_dose")
    if entry["absolute_max_dose"] is None:
        raise ValueError("required column 'absolute_max_dose' is missing or empty")

    entry["min_per_dose"] = _opt_decimal(row, "min_per_dose")
    entry["max_per_dose"] = _opt_decimal(row, "max_per_dose")
    entry["min_per_kg"] = _opt_decimal(row, "min_per_kg")
    entry["max_per_kg"] = _opt_decimal(row, "max_per_kg")
    entry["freq_min_per_day"] = _opt_int(row, "freq_min_per_day")
    entry["freq_max_per_day"] = _opt_int(row, "freq_max_per_day")

    # Age/weight band columns (all optional; blank → None = unbounded).
    # These are part of the natural key so that rules differing only by
    # patient band (e.g. neonate vs child vs adult) can coexist for the
    # same drug/route/basis without collapsing each other on re-import.
    entry["age_min_days"] = _opt_int(row, "age_min_days")
    entry["age_max_days"] = _opt_int(row, "age_max_days")
    entry["weight_min_kg"] = _opt_decimal(row, "weight_min_kg")
    entry["weight_max_kg"] = _opt_decimal(row, "weight_max_kg")

    return entry
