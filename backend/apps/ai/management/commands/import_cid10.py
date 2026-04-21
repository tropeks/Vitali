"""
Management command: import_cid10
=================================
Imports the DATASUS CID-10 code table into `core.CID10Code`.

Usage:
    python manage.py import_cid10 --source /path/to/CID10CM_tabela.csv

CSV format (DATASUS export, UTF-8, possibly with BOM):
    SUBCAT;DESCRICAO

The command is idempotent: existing codes are updated in-place, new codes
are created (update_or_create). Codes absent from the CSV are marked
active=False (deactivated).

After import, updates the PostgreSQL full-text search vector on all
imported rows so the CID10Suggester works immediately.
"""
import csv
import logging
import time
from pathlib import Path

from django.contrib.postgres.search import SearchVector
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.core.models import CID10Code

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Import DATASUS CID-10 code table from a CSV file into core.CID10Code"

    def add_arguments(self, parser):
        parser.add_argument(
            "--source",
            required=True,
            help="Path to the CID-10 CSV file (SUBCAT;DESCRICAO, UTF-8/UTF-8-BOM)",
        )
        parser.add_argument(
            "--delimiter",
            default=";",
            help="CSV column delimiter (default: ;)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Parse and validate CSV without writing to the database",
        )

    def handle(self, *args, **options):
        source_path = Path(options["source"])
        delimiter = options["delimiter"]
        dry_run = options["dry_run"]

        if not source_path.exists():
            raise CommandError(f"File not found: {source_path}")

        self.stdout.write(f"Importing CID-10 codes from {source_path} ...")
        start = time.time()

        # Read CSV — handle UTF-8 with BOM
        rows = []
        try:
            with open(source_path, newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f, delimiter=delimiter)
                for row in reader:
                    code = (row.get("SUBCAT") or "").strip()
                    description = (row.get("DESCRICAO") or "").strip()
                    if code and description:
                        rows.append((code, description))
        except Exception as exc:
            raise CommandError(f"Failed to read CSV: {exc}") from exc

        if not rows:
            raise CommandError("No valid rows found in CSV. Check delimiter and column names.")

        self.stdout.write(f"  Parsed {len(rows):,} rows from CSV.")

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run — no database writes."))
            return

        # Track codes seen in this import for deactivation step
        imported_codes = set()
        added = 0
        updated = 0

        with transaction.atomic():
            for code, description in rows:
                _, created = CID10Code.objects.update_or_create(
                    code=code,
                    defaults={
                        "description": description,
                        "active": True,
                    },
                )
                imported_codes.add(code)
                if created:
                    added += 1
                else:
                    updated += 1

            # Deactivate codes not present in this import
            deactivated = (
                CID10Code.objects.filter(active=True)
                .exclude(code__in=imported_codes)
                .update(active=False)
            )

            # Update search_vector for all active codes
            self.stdout.write("  Updating search vectors ...")
            CID10Code.objects.filter(active=True).update(
                search_vector=SearchVector("description", config="portuguese")
            )

        elapsed = time.time() - start
        self.stdout.write(
            self.style.SUCCESS(
                f"\nCID-10 import complete in {elapsed:.1f}s:\n"
                f"  Added:       {added:,}\n"
                f"  Updated:     {updated:,}\n"
                f"  Deactivated: {deactivated:,}\n"
                f"  Total active: {added + updated:,}"
            )
        )
