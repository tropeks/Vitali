"""
Management command: import_manchester  (core — E1)
==================================================
Imports the Manchester Triage catalog — fluxogramas (``core.ManchesterFlowchart``)
and their discriminadores (``core.ManchesterDiscriminator``) — from a single
semicolon-delimited CSV. Mirrors the E1-T1 CLI pattern of ``import_bed_types``:
idempotent upsert, per-row isolation for discriminators, ``--dry-run`` (all
writes rolled back), and a :class:`~apps.core.terminology_base.TerminologyImportLog`
provenance row (system ``manchester_flowchart``, provenance = GBCR).

Each CSV row is one discriminador; its fluxograma is upserted from the
``FLUXOGRAMA_CODIGO`` / ``FLUXOGRAMA_NOME`` columns (deduplicated by code).

Usage:
    python manage.py import_manchester --source /path/to/manchester.csv
    python manage.py import_manchester --source manchester.csv --manchester-version 2024 --dry-run

Expected CSV (semicolon-delimited, UTF-8; lines starting with '#' are comments):
    FLUXOGRAMA_CODIGO;FLUXOGRAMA_NOME;DISCRIMINADOR_CODIGO;DISCRIMINADOR_NOME;ACUIDADE;GERAL;DESCRICAO

``ACUIDADE`` ∈ {vermelho, laranja, amarelo, verde, azul}. ``GERAL`` is truthy
(sim/1/true) or falsey; ``DESCRICAO`` is optional. Rows with a blank/invalid
required field are reported by physical line number and abort the run
(fail-loud). No value is fabricated — the importer copies only what the source
row provides. Manchester content is licensed (GBCR); ship infra + a
representative sample only.
"""

import csv
import logging
import time
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.core.manchester_catalog_models import (
    AcuityLevel,
    ManchesterDiscriminator,
    ManchesterFlowchart,
)
from apps.core.terminology_base import TerminologyImportLog

logger = logging.getLogger(__name__)

_SYSTEM = "manchester_flowchart"

# Header aliases → canonical row keys.
_COLUMN_ALIASES = {
    "flowchart_code": ("FLUXOGRAMA_CODIGO", "fluxograma_codigo", "FLOWCHART_CODE"),
    "flowchart_name": ("FLUXOGRAMA_NOME", "fluxograma_nome", "FLOWCHART_NAME"),
    "code": ("DISCRIMINADOR_CODIGO", "discriminador_codigo", "CODE", "CODIGO"),
    "name": ("DISCRIMINADOR_NOME", "discriminador_nome", "NAME", "NOME"),
    "acuity": ("ACUIDADE", "acuidade", "ACUITY", "NIVEL"),
    "is_general": ("GERAL", "geral", "IS_GENERAL"),
    "description": ("DESCRICAO", "descricao", "Descrição", "DESCRIPTION"),
}

_TRUTHY = {"sim", "s", "true", "t", "1", "yes", "y", "verdadeiro"}
_VALID_ACUITY = set(AcuityLevel.values)


class Command(BaseCommand):
    help = "Import the Manchester triage catalog (fluxogramas + discriminadores) into core"

    def add_arguments(self, parser):
        parser.add_argument(
            "--source",
            required=True,
            help="Path to the Manchester CSV (semicolon-delimited, UTF-8)",
        )
        parser.add_argument("--delimiter", default=";", help="CSV column delimiter (default: ;)")
        # dest is 'manchester_version' — NOT 'version' (collides with BaseCommand).
        parser.add_argument(
            "--manchester-version",
            default="",
            help='Optional data-version label stored on fluxogramas, e.g. "2024".',
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Validate + preview without persisting (all writes rolled back).",
        )

    # ── Parsing ───────────────────────────────────────────────────────────────

    def _parse(self, source_path: Path, delimiter: str) -> list[dict]:
        """Parse + per-line validate the CSV. Raises CommandError (fail-loud) on any
        structural error, reporting TRUE physical line numbers. Parsing never writes."""
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
            fc_code = pick(raw, "flowchart_code")
            if not fc_code:
                errors.append(f"  Line {line}: FLUXOGRAMA_CODIGO is empty or blank")
                continue
            fc_name = pick(raw, "flowchart_name") or ""
            if not fc_name:
                errors.append(f"  Line {line}: FLUXOGRAMA_NOME is empty or blank")
                continue
            code = pick(raw, "code")
            if not code:
                errors.append(f"  Line {line}: DISCRIMINADOR_CODIGO is empty or blank")
                continue
            name = pick(raw, "name") or ""
            if not name:
                errors.append(f"  Line {line}: DISCRIMINADOR_NOME is empty or blank")
                continue
            acuity = (pick(raw, "acuity") or "").lower()
            if acuity not in _VALID_ACUITY:
                errors.append(
                    f"  Line {line}: ACUIDADE {acuity!r} invalid "
                    f"(expected one of {sorted(_VALID_ACUITY)})"
                )
                continue
            is_general = (pick(raw, "is_general") or "").lower() in _TRUTHY

            rows.append(
                {
                    "flowchart_code": fc_code,
                    "flowchart_name": fc_name,
                    "code": code,
                    "name": name,
                    "acuity": acuity,
                    "is_general": is_general,
                    "description": pick(raw, "description") or "",
                }
            )

        if errors:
            raise CommandError(
                f"Import aborted — {len(errors)} error(s) found. No rows were committed.\n"
                + "\n".join(errors)
            )
        return rows

    # ── Import engine (mirrors CatalogImporter guarantees for two models) ──────

    def _import(self, rows: list[dict], version: str, dry_run: bool) -> dict:
        start_ms = int(time.time() * 1000)
        fc_created = fc_updated = 0
        disc_created = disc_updated = disc_skipped = 0
        errors: list[str] = []

        with transaction.atomic():
            # Fluxogramas — deduplicate by code (first name wins), idempotent upsert.
            fc_names: dict[str, str] = {}
            for r in rows:
                fc_names.setdefault(r["flowchart_code"], r["flowchart_name"])

            fc_objs: dict[str, ManchesterFlowchart] = {}
            for fc_code, fc_name in fc_names.items():
                obj, created = ManchesterFlowchart.objects.update_or_create(
                    system=_SYSTEM,
                    code=fc_code,
                    version=version,
                    defaults={"display": fc_name, "active": True},
                )
                fc_objs[fc_code] = obj
                if created:
                    fc_created += 1
                else:
                    fc_updated += 1

            # Discriminadores — per-row savepoint isolation.
            for index, r in enumerate(rows):
                try:
                    with transaction.atomic():
                        _, created = ManchesterDiscriminator.objects.update_or_create(
                            flowchart=fc_objs[r["flowchart_code"]],
                            code=r["code"],
                            defaults={
                                "name": r["name"],
                                "description": r["description"],
                                "acuity_level": r["acuity"],
                                "is_general": r["is_general"],
                                "active": True,
                            },
                        )
                    if created:
                        disc_created += 1
                    else:
                        disc_updated += 1
                except Exception as exc:  # noqa: BLE001 — isolate every row
                    disc_skipped += 1
                    errors.append(f"row {index + 1}: {exc}")

            if dry_run:
                transaction.set_rollback(True)

        duration_ms = int(time.time() * 1000) - start_ms
        created = fc_created + disc_created
        updated = fc_updated + disc_updated
        if errors and (created or updated):
            status = TerminologyImportLog.Status.PARTIAL
        elif errors:
            status = TerminologyImportLog.Status.ERROR
        else:
            status = TerminologyImportLog.Status.SUCCESS

        # Provenance log written OUTSIDE the (possibly rolled-back) transaction, so
        # it persists even on a dry run — mirrors CatalogImporter._write_log.
        try:
            TerminologyImportLog.objects.create(
                system=_SYSTEM,
                version=version,
                source=TerminologyImportLog.Source.MANAGEMENT_COMMAND,
                provenance="GBCR",
                row_count_total=len(rows),
                row_count_added=created,
                row_count_updated=updated,
                row_count_errors=len(errors),
                status=status,
                dry_run=dry_run,
                error_message="\n".join(errors[:20])[:2000],
                duration_ms=duration_ms,
            )
        except Exception:  # noqa: BLE001 — logging is best-effort
            pass

        return {
            "fc_created": fc_created,
            "fc_updated": fc_updated,
            "disc_created": disc_created,
            "disc_updated": disc_updated,
            "disc_skipped": disc_skipped,
            "status": status,
            "errors": errors,
        }

    # ── Entry point ───────────────────────────────────────────────────────────

    def handle(self, *args, **options):
        source_path = Path(options["source"])
        if not source_path.exists():
            raise CommandError(f"File not found: {source_path}")

        delimiter = options["delimiter"]
        version = options["manchester_version"]
        dry_run = options["dry_run"]

        self.stdout.write(f"Importing Manchester catalog from {source_path} (dry_run={dry_run}) …")
        rows = self._parse(source_path, delimiter)
        result = self._import(rows, version, dry_run)

        for err in result["errors"][:20]:
            self.stderr.write(self.style.WARNING(err))

        verb = "Would import" if dry_run else "Imported"
        self.stdout.write(
            self.style.SUCCESS(
                f"{verb}: fluxogramas {result['fc_created']} created / "
                f"{result['fc_updated']} updated; discriminadores "
                f"{result['disc_created']} created / {result['disc_updated']} updated / "
                f"{result['disc_skipped']} skipped. Status={result['status']}."
            )
        )
