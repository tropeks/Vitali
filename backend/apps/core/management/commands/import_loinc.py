"""
Management command: import_loinc  (core — M2-S3-T1)
==================================================
Imports a LOINC observation table (a governed BR subset) into
``core.LoincCode``, keyed on the LOINC number. Uses the E1-T1
:class:`~apps.core.terminology_base.CatalogImporter` engine — idempotent upsert,
per-row isolation, ``--dry-run`` (all writes rolled back), and a
:class:`~apps.core.terminology_base.TerminologyImportLog` provenance row
(provenance = LOINC).

Usage:
    python manage.py import_loinc --source /path/to/loinc.csv
    python manage.py import_loinc --source loinc.csv --loinc-version 2.77 --dry-run

Expected CSV (semicolon-delimited, UTF-8; lines starting with '#' are comments):
    LOINC_NUM;LONG_COMMON_NAME;COMPONENT;PROPERTY;SYSTEM

Only LOINC_NUM and LONG_COMMON_NAME are required; every other column is optional
and left at its inert default when absent. No value is fabricated here — the
importer copies only what the LOINC source row provides.
"""

import csv
import logging
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.core.loinc_models import LoincCode
from apps.core.terminology_base import CatalogImporter, TerminologyImportLog

logger = logging.getLogger(__name__)

# Header aliases (LOINC exports vary) → canonical row keys.
_COLUMN_ALIASES = {
    "code": ("LOINC_NUM", "loinc_num", "LOINC", "loinc", "code"),
    "display": ("LONG_COMMON_NAME", "long_common_name", "DisplayName", "display", "NAME"),
    "component": ("COMPONENT", "component", "Component"),
    "property": ("PROPERTY", "property", "Property"),
    "loinc_system": ("SYSTEM", "system", "System"),
}


class LoincImporter(CatalogImporter):
    """CatalogImporter bound to LoincCode, keyed on (system, loinc_num, version)."""

    model = LoincCode
    system = "loinc"

    def build_defaults(self, row: dict) -> dict:
        return {
            "display": row["display"],
            "component": row.get("component", ""),
            "property": row.get("property", ""),
            "loinc_system": row.get("loinc_system", ""),
            "active": True,
        }


class Command(BaseCommand):
    help = "Import a LOINC observation catalog (BR subset) into core.LoincCode"

    def add_arguments(self, parser):
        parser.add_argument(
            "--source", required=True, help="Path to the LOINC CSV (semicolon-delimited, UTF-8)"
        )
        parser.add_argument("--delimiter", default=";", help="CSV column delimiter (default: ;)")
        # dest is 'loinc_version' — NOT 'version' (would collide with BaseCommand's
        # built-in --version). Optional metadata label stored on imported rows.
        parser.add_argument(
            "--loinc-version",
            default="",
            help='Optional data-version label stored on rows, e.g. "2.77".',
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
        any structural error, reporting TRUE physical line numbers. No partial
        state — parsing never writes to the DB."""
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
                    return raw[alias].strip()
            return None

        rows: list[dict] = []
        errors: list[str] = []
        for data_idx, raw in enumerate(raw_rows):
            line = phys(data_idx)
            code = pick(raw, "code")
            if not code:
                errors.append(f"  Line {line}: LOINC_NUM is empty or blank")
                continue
            display = pick(raw, "display") or ""
            if not display:
                errors.append(f"  Line {line}: LONG_COMMON_NAME is empty or blank")
                continue

            rows.append(
                {
                    "code": code,
                    "display": display,
                    "component": pick(raw, "component") or "",
                    "property": pick(raw, "property") or "",
                    "loinc_system": pick(raw, "loinc_system") or "",
                }
            )

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
        version = options["loinc_version"]
        dry_run = options["dry_run"]

        self.stdout.write(f"Importing LOINC catalog from {source_path} (dry_run={dry_run}) …")
        rows = self._parse(source_path, delimiter)

        importer = LoincImporter(
            version=version,
            source=TerminologyImportLog.Source.MANAGEMENT_COMMAND,
            provenance="LOINC",
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
