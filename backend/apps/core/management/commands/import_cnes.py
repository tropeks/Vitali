"""
Management command: import_cnes  (core — M2-S1-T2)
==================================================
Imports a CNES (Cadastro Nacional de Estabelecimentos de Saúde) establishment
table (DATASUS open data) into ``core.CNESEstablishment``, keyed on the CNES
number. Uses the E1-T1 :class:`~apps.core.terminology_base.CatalogImporter`
engine — idempotent upsert, per-row isolation, ``--dry-run`` (all writes rolled
back), and a :class:`~apps.core.terminology_base.TerminologyImportLog`
provenance row (provenance = CNES/DATASUS).

Usage:
    python manage.py import_cnes --source /path/to/cnes.csv
    python manage.py import_cnes --source cnes.csv --cnes-version 2024 --dry-run

Expected CSV (semicolon-delimited, UTF-8; lines starting with '#' are comments):
    CNES;NOME;TIPO;MUNICIPIO_IBGE;ATIVO

Only CNES and NOME are required; the remaining columns are optional and left at
their inert defaults when absent. ATIVO is parsed loosely ('0'/'nao'/'false'/
'inativo' → inactive, anything else → active). No value is fabricated here — the
importer copies only what the CNES source row provides. Rows with a blank code /
name are reported by physical line number and abort the run (fail-loud).
"""

import csv
import logging
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.core.cbo_cnes_models import CNESEstablishment
from apps.core.terminology_base import CatalogImporter, TerminologyImportLog

logger = logging.getLogger(__name__)

# Tokens that mark an establishment as INACTIVE in the ATIVO column.
_INACTIVE_TOKENS = {"0", "nao", "não", "n", "false", "f", "inativo", "inactive", "no"}

# Header aliases (CNES exports vary) → canonical row keys.
_COLUMN_ALIASES = {
    "code": ("CNES", "cnes", "CO_CNES", "co_cnes", "code"),
    "display": ("NOME", "nome", "Nome", "NOME_FANTASIA", "NO_FANTASIA", "display"),
    "establishment_type": ("TIPO", "tipo", "TP_UNIDADE", "TIPO_UNIDADE", "establishment_type"),
    "municipality_ibge": (
        "MUNICIPIO_IBGE",
        "municipio_ibge",
        "CO_IBGE",
        "co_ibge",
        "IBGE",
        "municipality_ibge",
    ),
    "active": ("ATIVO", "ativo", "ST_ATIVO", "status", "active"),
}


class CNESImporter(CatalogImporter):
    """CatalogImporter bound to CNESEstablishment, keyed on (system, cnes, version)."""

    model = CNESEstablishment
    system = "cnes"

    def build_defaults(self, row: dict) -> dict:
        return {
            "display": row["display"],
            "establishment_type": row.get("establishment_type", ""),
            "municipality_ibge": row.get("municipality_ibge", ""),
            "active": row.get("active", True),
        }


class Command(BaseCommand):
    help = "Import a CNES establishment catalog (DATASUS open data) into core.CNESEstablishment"

    def add_arguments(self, parser):
        parser.add_argument(
            "--source", required=True, help="Path to the CNES CSV (semicolon-delimited, UTF-8)"
        )
        parser.add_argument("--delimiter", default=";", help="CSV column delimiter (default: ;)")
        # dest is 'cnes_version' — NOT 'version' (would collide with BaseCommand's
        # built-in --version). Optional metadata label stored on imported rows.
        parser.add_argument(
            "--cnes-version",
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
                errors.append(f"  Line {line}: CNES is empty or blank")
                continue
            display = pick(raw, "display") or ""
            if not display:
                errors.append(f"  Line {line}: NOME is empty or blank")
                continue

            raw_active = pick(raw, "active")
            active = True
            if raw_active is not None and raw_active.strip().casefold() in _INACTIVE_TOKENS:
                active = False

            rows.append(
                {
                    "code": code,
                    "display": display,
                    "establishment_type": pick(raw, "establishment_type") or "",
                    "municipality_ibge": pick(raw, "municipality_ibge") or "",
                    "active": active,
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
        version = options["cnes_version"]
        dry_run = options["dry_run"]

        self.stdout.write(f"Importing CNES catalog from {source_path} (dry_run={dry_run}) …")
        rows = self._parse(source_path, delimiter)

        importer = CNESImporter(
            version=version,
            source=TerminologyImportLog.Source.MANAGEMENT_COMMAND,
            provenance="CNES/DATASUS",
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
