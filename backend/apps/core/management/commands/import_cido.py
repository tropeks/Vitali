"""
Management command: import_cido  (core — CID-O morphology)
=========================================================
Imports a DATASUS CID-O morphology table into ``core.CIDOMorphology``, keyed on
the CID-O morphology code. Uses the E1-T1
:class:`~apps.core.terminology_base.CatalogImporter` engine — idempotent upsert,
per-row isolation, ``--dry-run`` (all writes rolled back), and a
:class:`~apps.core.terminology_base.TerminologyImportLog` provenance row
(provenance = DATASUS).

Usage:
    python manage.py import_cido --source /path/to/cido.csv
    python manage.py import_cido --source cido.csv --cido-version 2008 --dry-run

Expected CSV (semicolon-delimited, UTF-8; lines starting with '#' are comments):
    CODIGO;TITULO;COMPORTAMENTO;CID10_REF

Only CODIGO and TITULO are required; COMPORTAMENTO / CID10_REF are optional and
left at their inert default when absent. No value is fabricated here.
"""

import csv
import logging
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.core.cido_models import CIDOMorphology
from apps.core.terminology_base import CatalogImporter, TerminologyImportLog

logger = logging.getLogger(__name__)

_COLUMN_ALIASES = {
    "code": ("CODIGO", "codigo", "Código", "COD", "CAT", "code"),
    "display": ("TITULO", "titulo", "Título", "DESCRICAO", "descricao", "display"),
    "behaviour": ("COMPORTAMENTO", "comportamento", "BEHAVIOUR", "behaviour"),
    "cid10_ref": ("CID10_REF", "cid10_ref", "REFER", "refer"),
}


class CIDOImporter(CatalogImporter):
    """CatalogImporter bound to CIDOMorphology, keyed on (system, code, version)."""

    model = CIDOMorphology
    system = "cid_o"

    def build_defaults(self, row: dict) -> dict:
        return {
            "display": row["display"],
            "behaviour": row.get("behaviour", ""),
            "cid10_ref": row.get("cid10_ref", ""),
            "version": self.version,
            "active": True,
        }


class Command(BaseCommand):
    help = "Import a DATASUS CID-O morphology table into core.CIDOMorphology"

    def add_arguments(self, parser):
        parser.add_argument(
            "--source", required=True, help="Path to the CID-O CSV (semicolon-delimited, UTF-8)"
        )
        parser.add_argument("--delimiter", default=";", help="CSV column delimiter (default: ;)")
        parser.add_argument(
            "--cido-version",
            default="",
            help='Optional data-version label stored on rows, e.g. "2008".',
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Validate + preview without persisting (all writes rolled back).",
        )

    def _parse(self, source_path: Path, delimiter: str) -> list[dict]:
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
            kept = data_idx + 1
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
                errors.append(f"  Line {line}: CODIGO is empty or blank")
                continue
            display = pick(raw, "display") or ""
            if not display:
                errors.append(f"  Line {line}: TITULO is empty or blank")
                continue

            # Behaviour: use the source column, else derive from the code suffix
            # (e.g. "8500/3" → "3"). Never fabricated beyond what the code encodes.
            behaviour = pick(raw, "behaviour") or ""
            if not behaviour and "/" in code:
                behaviour = code.rsplit("/", 1)[-1][:1]

            rows.append(
                {
                    "code": code,
                    "display": display,
                    "behaviour": behaviour,
                    "cid10_ref": pick(raw, "cid10_ref") or "",
                }
            )

        if errors:
            raise CommandError(
                f"Import aborted — {len(errors)} error(s) found. No rows were committed.\n"
                + "\n".join(errors)
            )
        return rows

    def handle(self, *args, **options):
        source_path = Path(options["source"])
        if not source_path.exists():
            raise CommandError(f"File not found: {source_path}")

        delimiter = options["delimiter"]
        version = options["cido_version"]
        dry_run = options["dry_run"]

        self.stdout.write(f"Importing CID-O morphology from {source_path} (dry_run={dry_run}) …")
        rows = self._parse(source_path, delimiter)

        importer = CIDOImporter(
            version=version,
            source=TerminologyImportLog.Source.MANAGEMENT_COMMAND,
            provenance="DATASUS",
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
