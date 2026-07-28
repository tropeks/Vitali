"""
Management command: import_ucum  (core — M2-S3-T1)
=================================================
Imports a UCUM units table into ``core.UcumUnit``, keyed on the **case-sensitive**
UCUM symbol. Uses the E1-T1
:class:`~apps.core.terminology_base.CatalogImporter` engine — idempotent upsert,
per-row isolation, ``--dry-run`` (all writes rolled back), and a
:class:`~apps.core.terminology_base.TerminologyImportLog` provenance row
(provenance = UCUM).

Usage:
    python manage.py import_ucum --source /path/to/ucum.csv
    python manage.py import_ucum --source ucum.csv --ucum-version 2.1 --dry-run

Expected CSV (semicolon-delimited, UTF-8; lines starting with '#' are comments):
    UCUM_CODE;DISPLAY

Both columns are required. No value is fabricated here — the importer copies only
what the UCUM source row provides.
"""

import csv
import logging
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.core.loinc_models import UcumUnit
from apps.core.terminology_base import CatalogImporter, TerminologyImportLog

logger = logging.getLogger(__name__)

# Header aliases (UCUM exports vary) → canonical row keys.
_COLUMN_ALIASES = {
    "code": ("UCUM_CODE", "ucum_code", "CODE", "code", "Code", "cs_code"),
    "display": ("DISPLAY", "display", "NAME", "name", "Name", "description"),
}


class UcumImporter(CatalogImporter):
    """CatalogImporter bound to UcumUnit, keyed on (system, code, version)."""

    model = UcumUnit
    system = "ucum"

    def build_defaults(self, row: dict) -> dict:
        return {"display": row["display"], "active": True}


class Command(BaseCommand):
    help = "Import a UCUM units catalog into core.UcumUnit"

    def add_arguments(self, parser):
        parser.add_argument(
            "--source", required=True, help="Path to the UCUM CSV (semicolon-delimited, UTF-8)"
        )
        parser.add_argument("--delimiter", default=";", help="CSV column delimiter (default: ;)")
        # dest is 'ucum_version' — NOT 'version' (collides with BaseCommand's --version).
        parser.add_argument(
            "--ucum-version",
            default="",
            help='Optional data-version label stored on rows, e.g. "2.1".',
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Validate + preview without persisting (all writes rolled back).",
        )

    # ── Parsing ───────────────────────────────────────────────────────────────

    def _parse(self, source_path: Path, delimiter: str) -> list[dict]:
        """Parse + per-line validate the CSV. Raises CommandError (fail-loud) on
        any structural error, reporting TRUE physical line numbers. UCUM codes are
        case-sensitive, so they are NEVER folded/normalised here."""
        with open(source_path, encoding="utf-8-sig", newline="") as fh:
            all_lines = list(fh)

        physical = [
            (idx + 1, ln) for idx, ln in enumerate(all_lines) if not ln.lstrip().startswith("#")
        ]
        if not physical:
            raise CommandError("CSV file is empty or contains only comments.")

        reader = csv.DictReader([ln for _, ln in physical], delimiter=delimiter)
        raw_rows = list(reader)
        if not raw_rows:
            raise CommandError("CSV has a header but no data rows.")

        def phys(data_idx: int) -> int:
            kept = data_idx + 1  # +1 skips the header line
            return physical[kept][0] if kept < len(physical) else data_idx + 2

        def pick(raw: dict, key: str) -> str | None:
            for alias in _COLUMN_ALIASES[key]:
                if alias in raw and raw[alias] is not None:
                    # Strip only surrounding whitespace; keep UCUM internal casing.
                    return raw[alias].strip()
            return None

        rows: list[dict] = []
        errors: list[str] = []
        for data_idx, raw in enumerate(raw_rows):
            line = phys(data_idx)
            code = pick(raw, "code")
            if not code:
                errors.append(f"  Line {line}: UCUM_CODE is empty or blank")
                continue
            display = pick(raw, "display") or ""
            if not display:
                errors.append(f"  Line {line}: DISPLAY is empty or blank")
                continue
            rows.append({"code": code, "display": display})

        if errors:
            raise CommandError(
                f"Import aborted — {len(errors)} error(s) found. No rows were committed.\n"
                + "\n".join(errors)
            )
        return rows

    # ── Entry point ───────────────────────────────────────────────────────────

    def handle(self, *args, **options):
        source_path = Path(options["source"])
        if not source_path.exists():
            raise CommandError(f"File not found: {source_path}")

        delimiter = options["delimiter"]
        version = options["ucum_version"]
        dry_run = options["dry_run"]

        self.stdout.write(f"Importing UCUM catalog from {source_path} (dry_run={dry_run}) …")
        rows = self._parse(source_path, delimiter)

        importer = UcumImporter(
            version=version,
            source=TerminologyImportLog.Source.MANAGEMENT_COMMAND,
            provenance="UCUM",
            dry_run=dry_run,
        )
        result = importer.run(rows)

        if result.errors:
            for err in result.errors[:20]:
                self.stderr.write(self.style.WARNING(err))

        verb = "Would import" if dry_run else "Imported"
        self.stdout.write(
            self.style.SUCCESS(
                f"{verb}: {result.created} created, {result.updated} updated, "
                f"{result.skipped} skipped. Status={result.status}."
            )
        )
