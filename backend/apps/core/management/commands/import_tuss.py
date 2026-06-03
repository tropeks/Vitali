"""
Management command: import_tuss
================================
Imports the ANS TUSS procedure/material/fee code table into `core.TUSSCode`.

Usage:
    python manage.py import_tuss --file tuss_procedimentos_2024_01.csv --tuss-version 2024-01
    python manage.py import_tuss --file tuss.csv --tuss-version 2024-01 --deactivate-old

The data-version label option is ``--tuss-version`` and is REQUIRED — an
invocation without it errors loudly rather than importing under a silent
default.  ``--version`` is NOT the data-version flag: it is Django's BaseCommand
built-in (prints the framework version and exits 0).  The custom option was
renamed precisely because a second ``--version`` collided with that built-in and
raised argparse ArgumentError at parser construction, making the command
un-runnable.

The command is idempotent: existing codes are updated in-place, new codes are
created. Codes absent from the import file are left untouched unless
--deactivate-old is passed.

Expected CSV format (ANS standard export, semicolon-delimited, UTF-8):
    CODIGO;DESCRICAO;GRUPO;SUBGRUPO

Optional clinical-compatibility columns (glosa wedge PR G3b)
-----------------------------------------------------------
If — and ONLY if — the ANS source export carries them, four additional
columns are imported into the clinical-compatibility metadata fields on
``core.TUSSCode``:
    IDADE_MIN_DIAS / IDADE_MAX_DIAS  → age_min_days / age_max_days
    SEXO                             → sex_allowed   (M / F / B)
    CID10_WHITELIST                  → cid10_whitelist (CSV/JSON list of CIDs)

These values are ANS-STANDARD TRUTH and are NEVER fabricated here: the
importer only copies what the source row provides. When the source row lacks
a column (the common case for the legacy CODIGO;DESCRICAO;GRUPO;SUBGRUPO
export), the field is LEFT AT ITS INERT DEFAULT (null age window / sex "B" /
empty whitelist) so the downstream ``clinical_incompat`` glosa check fires
nothing. No drug/procedure rule is ever hardcoded in this command.

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

from apps.core.models import TUSSCode, TUSSSyncLog

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Import ANS TUSS code table from a CSV file into core.TUSSCode"

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            required=True,
            help="Path to the TUSS CSV file (semicolon-delimited, UTF-8)",
        )
        # NOTE: the option is "--tuss-version", NOT "--version": Django's
        # BaseCommand already registers a built-in "--version" on every command,
        # so a second "--version" here raises argparse ArgumentError at parser
        # construction (the command was previously un-runnable for this reason).
        # It is REQUIRED: a caller who passes the wrong "--version" hits Django's
        # built-in version action (prints version, sys.exit(0)) → a SILENT no-op
        # import. Making "--tuss-version" required means such an invocation errors
        # loudly ("the following arguments are required") instead of succeeding
        # silently. dest is left at the auto "tuss_version" (NOT "version"): a
        # dest="version" would collide with the built-in --version's dest and
        # break call_command(tuss_version=...) once the arg is required.
        parser.add_argument(
            "--tuss-version",
            required=True,
            help='REQUIRED data-version label stored on imported rows, e.g. "2024-01". '
            "NOT the same as Django's built-in --version flag.",
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

        # Required arg → always present and non-empty; no csv_path.stem fallback.
        version = options["tuss_version"]
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

        # ── OPTIONAL clinical-compatibility columns (glosa wedge G3b) ──────────
        # Defensive readers: these columns are ANS-sourced and OPTIONAL. When the
        # source row does not carry them we return None / "B" / [] so the field
        # keeps its INERT default and the clinical_incompat check fires nothing.
        # Values are NEVER fabricated — only what the source provides is stored.
        def _opt_col(row: dict, *candidates: str) -> str | None:
            for key in candidates:
                if key in row and row[key] is not None:
                    return row[key].strip()
            return None  # column absent in this ANS export

        def _opt_int(row: dict, *candidates: str) -> int | None:
            raw = _opt_col(row, *candidates)
            if not raw:
                return None
            try:
                return int(raw)
            except (ValueError, TypeError):
                return None  # malformed source value → leave unbounded, do not guess

        def _opt_sex(row: dict) -> str:
            raw = (_opt_col(row, "SEXO", "sexo", "Sexo", "sex_allowed") or "").upper()
            return raw if raw in ("M", "F", "B") else "B"  # default = no constraint

        def _opt_cid_list(row: dict) -> list:
            raw = _opt_col(row, "CID10_WHITELIST", "cid10_whitelist", "CIDS", "cids")
            if not raw:
                return []  # empty list = no CID constraint
            # Accept either a JSON array or a delimiter-separated list of codes.
            try:
                import json

                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    # Normalise to uppercase + stripped so the stored whitelist
                    # compares case-insensitively against guide CIDs (CID-10 is
                    # case-insensitive; "a00" must match whitelist "A00").
                    return [str(c).strip().upper() for c in parsed if str(c).strip()]
            except (ValueError, TypeError):
                pass
            return [c.strip().upper() for c in raw.replace(";", ",").split(",") if c.strip()]

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

                defaults = {
                    "description": description,
                    "group": group,
                    "subgroup": subgroup,
                    "version": version,
                    "active": True,
                }
                # Clinical-compatibility metadata (G3b): ONLY write a field when
                # the ANS source row actually carries that column — otherwise
                # leave it untouched (do NOT clobber previously-imported ANS data
                # or the inert default with a fabricated value). The age columns
                # write through even when blank (→ None = unbounded), which is a
                # legitimate ANS "no limit" value.
                if any(k in row for k in ("IDADE_MIN_DIAS", "idade_min_dias", "age_min_days")):
                    defaults["age_min_days"] = _opt_int(
                        row, "IDADE_MIN_DIAS", "idade_min_dias", "age_min_days"
                    )
                if any(k in row for k in ("IDADE_MAX_DIAS", "idade_max_dias", "age_max_days")):
                    defaults["age_max_days"] = _opt_int(
                        row, "IDADE_MAX_DIAS", "idade_max_dias", "age_max_days"
                    )
                if any(k in row for k in ("SEXO", "sexo", "Sexo", "sex_allowed")):
                    defaults["sex_allowed"] = _opt_sex(row)
                if any(k in row for k in ("CID10_WHITELIST", "cid10_whitelist", "CIDS", "cids")):
                    defaults["cid10_whitelist"] = _opt_cid_list(row)

                obj, was_created = TUSSCode.objects.update_or_create(
                    code=code,
                    defaults=defaults,
                )
                if was_created:
                    created += 1
                else:
                    updated += 1

            if deactivate_old:
                deactivated = TUSSCode.objects.exclude(code__in=codes_in_file).update(active=False)
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
            self.style.SUCCESS(f"Done. Created: {created}  Updated: {updated}  Skipped: {skipped}")
        )
