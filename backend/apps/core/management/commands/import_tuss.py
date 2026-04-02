"""
Management command: import_tuss
================================
Imports the ANS TUSS procedure/material/fee code table into `core.TUSSCode`.

Usage:
    python manage.py import_tuss --file tuss_procedimentos_2024_01.csv
    python manage.py import_tuss --file tuss_procedimentos_2024_01.csv --version 2024-01
    python manage.py import_tuss --file tuss_procedimentos_2024_01.csv --deactivate-old

The command is idempotent: existing codes are updated in-place, new codes are
created. Codes absent from the import file are left untouched unless
--deactivate-old is passed.

Expected CSV format (ANS standard export, semicolon-delimited, UTF-8):
    CODIGO;DESCRICAO;GRUPO;SUBGRUPO

The command also updates the PostgreSQL full-text search vector (search_vector)
for all imported rows so that the TUSS fuzzy-search API works immediately.
"""

import csv
import logging
import time
from pathlib import Path

from django.contrib.postgres.search import SearchVector
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.core.models import TUSSSyncLog, TUSSCode

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Import ANS TUSS code table from a CSV file into core.TUSSCode"

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            required=True,
            help="Path to the TUSS CSV file (semicolon-delimited, UTF-8)",
        )
        parser.add_argument(
            "--version",
            default="",
            help='Version label to store on imported rows, e.g. "2024-01"',
        )
        parser.add_argument(
            "--deactivate-old",
            action="store_true",
            default=False,
            help="Mark codes not present in the CSV as inactive (active=False)",
        )
        parser.add_argument(
            "--delimiter",
            default=";",
            help="CSV column delimiter (default: ;)",
        )

    def handle(self, *args, **options):
        csv_path = Path(options["file"])
        if not csv_path.exists():
            raise CommandError(f"File not found: {csv_path}")

        version = options["version"] or csv_path.stem
        delimiter = options["delimiter"]
        deactivate_old = options["deactivate_old"]

        self.stdout.write(f"Importing TUSS from {csv_path} (version={version!r}) …")
        _start_ms = int(time.time() * 1000)

        codes_in_file: set[str] = set()
        created = updated = skipped = 0

        with open(csv_path, encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh, delimiter=delimiter)
            # Normalise header names — ANS files vary slightly between versions
            rows = list(reader)

        if not rows:
            raise CommandError("CSV file is empty or header is missing.")

        # Accept both exact ANS header names and common variants
        def _col(row: dict, *candidates: str) -> str:
            for key in candidates:
                if key in row:
                    return row[key].strip()
            raise CommandError(
                f"Could not find any of {candidates} in CSV columns: {list(row.keys())}"
            )

        with transaction.atomic():
            for row in rows:
                code = _col(row, "CODIGO", "codigo", "Código", "code")
                description = _col(row, "DESCRICAO", "descricao", "Descrição", "description")
                group = _col(row, "GRUPO", "grupo", "Grupo", "group")
                subgroup = ""
                for sub_key in ("SUBGRUPO", "subgrupo", "Subgrupo", "subgroup"):
                    if sub_key in row:
                        subgroup = row[sub_key].strip()
                        break

                if not code:
                    skipped += 1
                    continue

                codes_in_file.add(code)

                obj, was_created = TUSSCode.objects.update_or_create(
                    code=code,
                    defaults={
                        "description": description,
                        "group": group,
                        "subgroup": subgroup,
                        "version": version,
                        "active": True,
                    },
                )
                if was_created:
                    created += 1
                else:
                    updated += 1

            if deactivate_old:
                deactivated = TUSSCode.objects.exclude(code__in=codes_in_file).update(
                    active=False
                )
                self.stdout.write(f"  Deactivated {deactivated} codes not in file.")

        # Update full-text search vectors for all imported codes
        self.stdout.write("Updating search vectors …")
        TUSSCode.objects.filter(code__in=codes_in_file).update(
            search_vector=SearchVector("code", weight="A")
            + SearchVector("description", weight="B")
            + SearchVector("group", weight="C"),
        )

        duration_ms = int(time.time() * 1000) - _start_ms
        total = TUSSCode.objects.count()
        try:
            TUSSSyncLog.objects.create(
                source=TUSSSyncLog.Source.MANAGEMENT_COMMAND,
                row_count_total=total,
                row_count_added=created,
                row_count_updated=updated,
                status=TUSSSyncLog.Status.SUCCESS,
                duration_ms=duration_ms,
            )
        except Exception as exc:
            logger.warning("Could not write TUSSSyncLog: %s", exc)

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Created: {created}  Updated: {updated}  Skipped: {skipped}"
            )
        )
