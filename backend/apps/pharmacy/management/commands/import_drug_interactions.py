"""
Management command: import_drug_interactions
=============================================
Imports drug-drug interaction pairs from a CSV file into
pharmacy.DrugInteraction with provenance (source + version).

Usage:
    python manage.py import_drug_interactions --file drug_interactions.csv
    python manage.py import_drug_interactions --file drug_interactions.csv --dry-run
    python manage.py import_drug_interactions --file drug_interactions.csv --source RXNORM --version 2024-01

INVIOLABLE PRINCIPLE: no clinical data is invented here. The importer only
reads what the CSV provides.

Behaviour:
  - Idempotent: DrugInteraction update_or_create by (ingredient_a, ingredient_b)
    — the unique natural key.
  - Fail-loud: per-line validation via instance.full_clean(); ALL errors are
    collected, then a single CommandError is raised BEFORE any commit. No
    silent partial imports.
  - --dry-run: performs validation + ORM work inside a transaction that is
    always rolled back; prints a summary and exits cleanly.
  - Lines starting with '#' are treated as comments and skipped.

Expected CSV columns (comma-delimited by default):
    ingredient_a — DrugInteraction.ingredient_a (required)
    ingredient_b — DrugInteraction.ingredient_b (required)
    severity     — DrugInteraction.severity (advise/contraindicated; default advise)
    description  — DrugInteraction.description (optional)
"""

import csv
import logging
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django_tenants.utils import get_public_schema_name

from apps.pharmacy.models import DrugInteraction

logger = logging.getLogger(__name__)


def _required_str(row: dict, col: str) -> str:
    """Return a stripped string from a CSV cell; raise ValueError if empty/missing."""
    raw = row.get(col, "").strip()
    if not raw:
        raise ValueError(f"required column '{col}' is missing or empty")
    return raw


def _parse_row(row: dict, *, line_number: int) -> dict:
    """Parse and validate one CSV row into a dict of typed values.

    Raises ValueError with a human-readable message on any parse failure.
    No clinical defaults are invented — every value comes from the CSV.
    """
    entry: dict = {"_line_number": line_number}
    entry["ingredient_a"] = _required_str(row, "ingredient_a")
    entry["ingredient_b"] = _required_str(row, "ingredient_b")
    raw_severity = row.get("severity", "").strip()
    entry["severity"] = raw_severity if raw_severity else DrugInteraction.Severity.ADVISE
    entry["description"] = row.get("description", "").strip()
    return entry


class Command(BaseCommand):
    help = "Import drug-drug interaction pairs from a CSV file into DrugInteraction"

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            required=True,
            help="Path to the drug interactions CSV file",
        )
        parser.add_argument(
            "--source",
            default="",
            help="Provenance source label (e.g. RXNORM, FAKE-SOURCE). Stored on each row.",
        )
        parser.add_argument(
            "--data-version",
            default="",
            dest="data_version",
            help="Provenance version string (e.g. 2024-01). Stored on each row.",
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
        if connection.schema_name == get_public_schema_name():
            raise CommandError(
                "import_drug_interactions must run inside a tenant schema "
                "(use --schema=<tenant> or tenant_context); "
                "refusing to write pharmacy data to the public schema."
            )

        csv_path = Path(options["file"])
        if not csv_path.exists():
            raise CommandError(f"File not found: {csv_path}")

        dry_run = options["dry_run"]
        delimiter = options["delimiter"]
        source = options["source"]
        version = options["data_version"]

        self.stdout.write(f"Importing drug interactions from {csv_path} (dry_run={dry_run}) …")

        # Read all lines, keeping track of each line's 1-based physical index.
        with open(csv_path, encoding="utf-8-sig", newline="") as fh:
            all_lines = list(fh)

        physical_lines = [
            (phys_idx + 1, ln)
            for phys_idx, ln in enumerate(all_lines)
            if not ln.lstrip().startswith("#")
        ]

        if not physical_lines:
            raise CommandError("CSV file is empty or contains only comments.")

        kept_texts = [ln for _, ln in physical_lines]
        reader = csv.DictReader(kept_texts, delimiter=delimiter)
        rows = list(reader)

        if not rows:
            raise CommandError("CSV file has a header but no data rows.")

        def _physical_line(data_row_index: int) -> int:
            kept_idx = data_row_index + 1
            if kept_idx < len(physical_lines):
                return physical_lines[kept_idx][0]
            return data_row_index + 2

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
        validation_errors: list[str] = []
        for entry in parsed_rows:
            instance = DrugInteraction(
                ingredient_a=entry["ingredient_a"],
                ingredient_b=entry["ingredient_b"],
                severity=entry["severity"],
                description=entry["description"],
                source=source,
                version=version,
                active=True,
            )
            try:
                # Exclude unique-constraint checks: update_or_create handles idempotency,
                # so a pre-existing (ingredient_a, ingredient_b) pair would false-fire
                # as a unique violation here. validate_unique=False suppresses field-level
                # unique checks; validate_constraints=False suppresses UniqueConstraint checks.
                instance.full_clean(
                    exclude=["id", "created_at", "updated_at"],
                    validate_unique=False,
                    validate_constraints=False,
                )
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
        created_count = updated_count = 0

        with transaction.atomic():
            for entry in parsed_rows:
                _obj, obj_created = DrugInteraction.objects.update_or_create(
                    ingredient_a=entry["ingredient_a"],
                    ingredient_b=entry["ingredient_b"],
                    defaults={
                        "severity": entry["severity"],
                        "description": entry["description"],
                        "source": source,
                        "version": version,
                        "active": True,
                    },
                )
                if obj_created:
                    created_count += 1
                else:
                    updated_count += 1

            if dry_run:
                # Roll back everything — nothing persisted.
                transaction.set_rollback(True)

        action = "Would import" if dry_run else "Done"
        self.stdout.write(
            self.style.SUCCESS(
                f"{action}. "
                f"DrugInteractions: {created_count} created, {updated_count} updated."
            )
        )
