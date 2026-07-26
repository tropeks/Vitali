"""
Management command: import_nic  (core — N1-T2)
==============================================
Imports a NIC (Nursing Interventions Classification) taxonomy into
``core.NicIntervention``, keyed on the NIC code. Uses the E1-T1
:class:`~apps.core.terminology_base.CatalogImporter` engine — idempotent upsert,
per-row isolation, ``--dry-run`` (all writes rolled back), and a
:class:`~apps.core.terminology_base.TerminologyImportLog` provenance row
(provenance = NIC).

Usage:
    python manage.py import_nic --source /path/to/nic.csv
    python manage.py import_nic --source nic.csv --nic-version 7 --dry-run

Expected CSV (semicolon-delimited, UTF-8; lines starting with '#' are comments):
    CODIGO;TITULO;DEFINICAO;ATIVIDADES

Only CODIGO and TITULO are required; DEFINICAO / ATIVIDADES are optional and left
at their inert defaults when absent. No value is fabricated here — the importer
copies only what the NIC source row provides. Rows with a blank code / title are
reported by physical line number and abort the run (fail-loud). The NIC taxonomy
is licensed; ship infra + a representative sample only.
"""

import csv
import logging
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.core.nursing_catalog_models import NicIntervention
from apps.core.terminology_base import CatalogImporter, TerminologyImportLog

logger = logging.getLogger(__name__)

# Header aliases (NIC exports vary) → canonical row keys.
_COLUMN_ALIASES = {
    "code": ("CODIGO", "codigo", "Código", "COD", "CODE", "code"),
    "display": ("TITULO", "titulo", "Título", "INTERVENCAO", "intervencao", "LABEL", "display"),
    "definition": ("DEFINICAO", "definicao", "Definição", "DEFINITION", "definition"),
    "activities": ("ATIVIDADES", "atividades", "Atividades", "ACTIVITIES", "activities"),
}


class NicImporter(CatalogImporter):
    """CatalogImporter bound to NicIntervention, keyed on (system, codigo, version)."""

    model = NicIntervention
    system = "nic"

    def build_defaults(self, row: dict) -> dict:
        return {
            "display": row["display"],
            "definition": row.get("definition", ""),
            "activities": row.get("activities", ""),
            "active": True,
        }


class Command(BaseCommand):
    help = "Import a NIC nursing intervention taxonomy into core.NicIntervention"

    def add_arguments(self, parser):
        parser.add_argument(
            "--source", required=True, help="Path to the NIC CSV (semicolon-delimited, UTF-8)"
        )
        parser.add_argument("--delimiter", default=";", help="CSV column delimiter (default: ;)")
        # dest is 'nic_version' — NOT 'version' (would collide with BaseCommand's
        # built-in --version). Optional metadata label stored on imported rows.
        parser.add_argument(
            "--nic-version",
            default="",
            help='Optional data-version label stored on rows, e.g. "7".',
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
                    "definition": pick(raw, "definition") or "",
                    "activities": pick(raw, "activities") or "",
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
        version = options["nic_version"]
        dry_run = options["dry_run"]

        self.stdout.write(f"Importing NIC catalog from {source_path} (dry_run={dry_run}) …")
        rows = self._parse(source_path, delimiter)

        importer = NicImporter(
            version=version,
            source=TerminologyImportLog.Source.MANAGEMENT_COMMAND,
            provenance="NIC",
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
