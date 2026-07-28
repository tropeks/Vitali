"""
Management command: import_blood_components  (core — H1)
=======================================================
Imports a hemocomponente taxonomy into ``core.BloodComponentCatalog``, keyed on
the hemocomponente code. Uses the E1-T1
:class:`~apps.core.terminology_base.CatalogImporter` engine — idempotent upsert,
per-row isolation, ``--dry-run`` (all writes rolled back), and a
:class:`~apps.core.terminology_base.TerminologyImportLog` provenance row
(provenance = ISBT-128/HEMOBRAS).

Usage:
    python manage.py import_blood_components --source /path/to/blood_components.csv
    python manage.py import_blood_components --source components.csv --component-version 2024 --dry-run

Expected CSV (semicolon-delimited, UTF-8; lines starting with '#' are comments):
    CODIGO;TITULO;VALIDADE_DIAS;CONTEXTO

Only CODIGO and TITULO are required; VALIDADE_DIAS and CONTEXTO are optional and
left at their inert defaults when absent. No value is fabricated here — the
importer copies only what the source row provides. Rows with a blank code / title
are reported by physical line number and abort the run (fail-loud). Ship infra +
a representative sample only.
"""

import csv
import logging
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.core.blood_catalog_models import BloodComponentCatalog
from apps.core.terminology_base import CatalogImporter, TerminologyImportLog

logger = logging.getLogger(__name__)

# Header aliases → canonical row keys.
_COLUMN_ALIASES = {
    "code": ("CODIGO", "codigo", "Código", "COD", "CODE", "code"),
    "display": ("TITULO", "titulo", "Título", "NOME", "nome", "DESCRICAO", "LABEL", "display"),
    "default_validade_dias": (
        "VALIDADE_DIAS",
        "validade_dias",
        "VALIDADE",
        "validade",
        "SHELF_LIFE_DAYS",
    ),
    "context": ("CONTEXTO", "contexto", "Contexto", "CONTEXT", "GRUPO", "grupo", "context"),
}


class BloodComponentImporter(CatalogImporter):
    """CatalogImporter bound to BloodComponentCatalog, keyed on (system, codigo, version)."""

    model = BloodComponentCatalog
    system = "blood_component"

    def build_defaults(self, row: dict) -> dict:
        validade = row.get("default_validade_dias")
        return {
            "display": row["display"],
            "default_validade_dias": validade if validade not in (None, "") else None,
            "context": row.get("context", ""),
            "active": True,
        }


class Command(BaseCommand):
    help = "Import a hemocomponente taxonomy into core.BloodComponentCatalog"

    def add_arguments(self, parser):
        parser.add_argument(
            "--source",
            required=True,
            help="Path to the hemocomponente CSV (semicolon-delimited, UTF-8)",
        )
        parser.add_argument("--delimiter", default=";", help="CSV column delimiter (default: ;)")
        # dest is 'component_version' — NOT 'version' (would collide with
        # BaseCommand's built-in --version). Optional metadata label on rows.
        parser.add_argument(
            "--component-version",
            default="",
            help='Optional data-version label stored on rows, e.g. "2024".',
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
                errors.append(f"  Line {line}: CODIGO is empty or blank")
                continue
            display = pick(raw, "display") or ""
            if not display:
                errors.append(f"  Line {line}: TITULO is empty or blank")
                continue

            validade_raw = pick(raw, "default_validade_dias") or ""
            validade: int | None = None
            if validade_raw:
                try:
                    validade = int(validade_raw)
                except ValueError:
                    errors.append(
                        f"  Line {line}: VALIDADE_DIAS '{validade_raw}' is not an integer"
                    )
                    continue

            rows.append(
                {
                    "code": code,
                    "display": display,
                    "default_validade_dias": validade,
                    "context": pick(raw, "context") or "",
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
        version = options["component_version"]
        dry_run = options["dry_run"]

        self.stdout.write(
            f"Importing hemocomponente catalog from {source_path} (dry_run={dry_run}) …"
        )
        rows = self._parse(source_path, delimiter)

        importer = BloodComponentImporter(
            version=version,
            source=TerminologyImportLog.Source.MANAGEMENT_COMMAND,
            provenance="ISBT-128/HEMOBRAS",
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
