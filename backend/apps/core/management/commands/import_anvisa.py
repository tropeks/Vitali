"""
Management command: import_anvisa  (core — E3-T1)
=================================================
Imports an ANVISA drug-catalog table (open data) into ``core.AnvisaProduct``,
keyed on the ANVISA registration number. Uses the E1-T1
:class:`~apps.core.terminology_base.CatalogImporter` engine — idempotent upsert,
per-row isolation, ``--dry-run`` (all writes rolled back), and a
:class:`~apps.core.terminology_base.TerminologyImportLog` provenance row
(provenance = ANVISA).

Usage:
    python manage.py import_anvisa --source /path/to/anvisa.csv
    python manage.py import_anvisa --source anvisa.csv --anvisa-version 2024 --dry-run

Expected CSV (semicolon-delimited, UTF-8; lines starting with '#' are comments):
    REGISTRO;PRODUTO;DCB;APRESENTACAO;EAN;CLASSE_TERAPEUTICA;TARJA

Only REGISTRO and PRODUTO are required; every other column is optional and left
at its inert default when absent. No value is fabricated here — the importer
copies only what the ANVISA source row provides.
"""

import csv
import logging
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.core.catalog_models import AnvisaProduct
from apps.core.terminology_base import CatalogImporter, TerminologyImportLog

logger = logging.getLogger(__name__)

# Portaria 344 controlled-list tokens accepted in the TARJA column.
_VALID_TARJA = {c for c, _ in AnvisaProduct.CONTROLLED_CHOICES}

# Header aliases (ANVISA exports vary) → canonical row keys.
_COLUMN_ALIASES = {
    "code": ("REGISTRO", "registro", "Registro", "NUMERO_REGISTRO", "code"),
    "display": ("PRODUTO", "produto", "Produto", "NOME_PRODUTO", "display"),
    "dcb": ("DCB", "dcb", "PRINCIPIO_ATIVO", "principio_ativo"),
    "presentation": ("APRESENTACAO", "apresentacao", "Apresentação", "presentation"),
    "ean": ("EAN", "ean", "EAN13", "GTIN", "gtin", "codigo_barras"),
    "therapeutic_class": (
        "CLASSE_TERAPEUTICA",
        "classe_terapeutica",
        "Classe Terapêutica",
        "therapeutic_class",
    ),
    "controlled_class": ("TARJA", "tarja", "LISTA", "lista", "controlled_class"),
}


class AnvisaImporter(CatalogImporter):
    """CatalogImporter bound to AnvisaProduct, keyed on (system, registro, version)."""

    model = AnvisaProduct
    system = "anvisa"

    def build_defaults(self, row: dict) -> dict:
        return {
            "display": row["display"],
            "dcb": row.get("dcb", ""),
            "presentation": row.get("presentation", ""),
            "ean": row.get("ean", ""),
            "therapeutic_class": row.get("therapeutic_class", ""),
            "controlled_class": row.get("controlled_class", "none"),
            "active": True,
        }


class Command(BaseCommand):
    help = "Import an ANVISA drug catalog (open data) into core.AnvisaProduct"

    def add_arguments(self, parser):
        parser.add_argument(
            "--source", required=True, help="Path to the ANVISA CSV (semicolon-delimited, UTF-8)"
        )
        parser.add_argument("--delimiter", default=";", help="CSV column delimiter (default: ;)")
        # dest is 'anvisa_version' — NOT 'version' (would collide with BaseCommand's
        # built-in --version). Optional metadata label stored on imported rows.
        parser.add_argument(
            "--anvisa-version",
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
                errors.append(f"  Line {line}: REGISTRO is empty or blank")
                continue
            display = pick(raw, "display") or ""
            if not display:
                errors.append(f"  Line {line}: PRODUTO is empty or blank")
                continue

            tarja = (pick(raw, "controlled_class") or "none").strip()
            if tarja not in _VALID_TARJA:
                tarja = "none"  # unknown/blank → no tarja (never fabricate)

            rows.append(
                {
                    "code": code,
                    "display": display,
                    "dcb": pick(raw, "dcb") or "",
                    "presentation": pick(raw, "presentation") or "",
                    "ean": pick(raw, "ean") or "",
                    "therapeutic_class": pick(raw, "therapeutic_class") or "",
                    "controlled_class": tarja,
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
        version = options["anvisa_version"]
        dry_run = options["dry_run"]

        self.stdout.write(f"Importing ANVISA catalog from {source_path} (dry_run={dry_run}) …")
        rows = self._parse(source_path, delimiter)

        importer = AnvisaImporter(
            version=version,
            source=TerminologyImportLog.Source.MANAGEMENT_COMMAND,
            provenance="ANVISA",
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
