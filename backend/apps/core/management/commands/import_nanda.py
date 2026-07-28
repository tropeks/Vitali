"""
Management command: import_nanda  (core — N1-T2)
================================================
Imports a NANDA-I nursing diagnosis taxonomy into ``core.NandaDiagnosis``, keyed
on the NANDA code. Uses the E1-T1
:class:`~apps.core.terminology_base.CatalogImporter` engine — idempotent upsert,
per-row isolation, ``--dry-run`` (all writes rolled back), and a
:class:`~apps.core.terminology_base.TerminologyImportLog` provenance row
(provenance = NANDA-I).

Usage:
    python manage.py import_nanda --source /path/to/nanda.csv
    python manage.py import_nanda --source nanda.csv --nanda-version 2021-2023 --dry-run

Expected CSV (semicolon-delimited, UTF-8; lines starting with '#' are comments):
    CODIGO;TITULO;DOMINIO;CLASSE;DEFINICAO;CARACTERISTICAS;FATORES

Only CODIGO and TITULO are required; the remaining columns are optional and left
at their inert defaults when absent. No value is fabricated here — the importer
copies only what the NANDA-I source row provides. Rows with a blank code / title
are reported by physical line number and abort the run (fail-loud), so nothing is
half-imported. The NANDA-I taxonomy is licensed; ship infra + a representative
sample only.
"""

import csv
import logging
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.core.nursing_catalog_models import NandaDiagnosis
from apps.core.terminology_base import CatalogImporter, TerminologyImportLog

logger = logging.getLogger(__name__)

# Header aliases (NANDA exports vary) → canonical row keys.
_COLUMN_ALIASES = {
    "code": ("CODIGO", "codigo", "Código", "COD", "CODE", "code"),
    "display": ("TITULO", "titulo", "Título", "ROTULO", "rotulo", "LABEL", "display"),
    "domain": ("DOMINIO", "dominio", "Domínio", "DOMAIN", "domain"),
    "nanda_class": ("CLASSE", "classe", "Classe", "CLASS", "class", "nanda_class"),
    "definition": ("DEFINICAO", "definicao", "Definição", "DEFINITION", "definition"),
    "defining_characteristics": (
        "CARACTERISTICAS",
        "caracteristicas",
        "Características",
        "DEFINING_CHARACTERISTICS",
        "defining_characteristics",
    ),
    "related_factors": (
        "FATORES",
        "fatores",
        "Fatores",
        "RELATED_FACTORS",
        "related_factors",
    ),
}


class NandaImporter(CatalogImporter):
    """CatalogImporter bound to NandaDiagnosis, keyed on (system, codigo, version)."""

    model = NandaDiagnosis
    system = "nanda"

    def build_defaults(self, row: dict) -> dict:
        return {
            "display": row["display"],
            "domain": row.get("domain", ""),
            "nanda_class": row.get("nanda_class", ""),
            "definition": row.get("definition", ""),
            "defining_characteristics": row.get("defining_characteristics", ""),
            "related_factors": row.get("related_factors", ""),
            "active": True,
        }


class Command(BaseCommand):
    help = "Import a NANDA-I nursing diagnosis taxonomy into core.NandaDiagnosis"

    def add_arguments(self, parser):
        parser.add_argument(
            "--source", required=True, help="Path to the NANDA CSV (semicolon-delimited, UTF-8)"
        )
        parser.add_argument("--delimiter", default=";", help="CSV column delimiter (default: ;)")
        # dest is 'nanda_version' — NOT 'version' (would collide with BaseCommand's
        # built-in --version). Optional metadata label stored on imported rows.
        parser.add_argument(
            "--nanda-version",
            default="",
            help='Optional data-version label stored on rows, e.g. "2021-2023".',
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

            rows.append(
                {
                    "code": code,
                    "display": display,
                    "domain": pick(raw, "domain") or "",
                    "nanda_class": pick(raw, "nanda_class") or "",
                    "definition": pick(raw, "definition") or "",
                    "defining_characteristics": pick(raw, "defining_characteristics") or "",
                    "related_factors": pick(raw, "related_factors") or "",
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
        version = options["nanda_version"]
        dry_run = options["dry_run"]

        self.stdout.write(f"Importing NANDA-I catalog from {source_path} (dry_run={dry_run}) …")
        rows = self._parse(source_path, delimiter)

        importer = NandaImporter(
            version=version,
            source=TerminologyImportLog.Source.MANAGEMENT_COMMAND,
            provenance="NANDA-I",
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
