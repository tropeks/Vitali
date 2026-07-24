"""
Management command: import_cid10  (core — E1-T3, hierarchical rewrite)
=====================================================================
Imports a DATASUS-style CID-10 table into ``core.CID10Code``, building the
chapter/group/category labels and the self-referential ``parent`` hierarchy,
plus governed clinical metadata (sex/age window/notifiable). Uses the E1-T1
:class:`CatalogImporter` engine — idempotent upsert (keyed on ``code``), per-row
isolation, ``--dry-run``, and a :class:`TerminologyImportLog` provenance row
(provenance=DATASUS).

Usage:
    python manage.py import_cid10 --source /path/to/cid10.csv
    python manage.py import_cid10 --source cid10.csv --cid-version 2024 --dry-run

Expected CSV (semicolon-delimited, UTF-8; lines starting with '#' are comments):
    CODIGO;DESCRICAO;CAPITULO;GRUPO;CATEGORIA;PARENT;SEXO;IDADE_MIN;IDADE_MAX;NOTIFICACAO

Only CODIGO and DESCRICAO are required; every other column is optional and left
at its inert default when absent. No clinical value is fabricated here — the
importer copies only what the source row provides.

NOTE (command-name collision): ``apps.ai`` also ships an ``import_cid10``
command and, being later in INSTALLED_APPS, wins ``manage.py import_cid10``. This
richer core importer supersedes it; retiring the ai command (out of E1 scope) is
tracked separately so the hierarchical importer becomes the default.
"""

import csv
import logging
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.core.models import CID10Code
from apps.core.terminology_base import CatalogImporter, TerminologyImportLog

logger = logging.getLogger(__name__)

_SEX_VALID = {"M", "F", "B"}
_TRUE_TOKENS = {"S", "SIM", "1", "TRUE", "Y", "YES"}

# Header aliases (DATASUS exports vary) → canonical row keys.
_COLUMN_ALIASES = {
    "code": ("CODIGO", "codigo", "Código", "SUBCAT", "code"),
    "description": ("DESCRICAO", "descricao", "Descrição", "DESCRABREV", "description"),
    "chapter": ("CAPITULO", "capitulo", "Capítulo", "chapter"),
    "group": ("GRUPO", "grupo", "Grupo", "group"),
    "category": ("CATEGORIA", "categoria", "Categoria", "category"),
    "parent": ("PARENT", "parent", "PAI", "pai"),
    "sex_allowed": ("SEXO", "sexo", "Sexo", "sex_allowed"),
    "age_min": ("IDADE_MIN", "idade_min", "age_min"),
    "age_max": ("IDADE_MAX", "idade_max", "age_max"),
    "is_notifiable": ("NOTIFICACAO", "notificacao", "Notificação", "is_notifiable"),
}


class CID10Importer(CatalogImporter):
    """CatalogImporter bound to CID10Code, keyed on the (globally unique) code."""

    model = CID10Code
    system = "cid10"

    def natural_key(self, row: dict) -> dict:
        # CID10Code.code is globally unique — idempotency keys on code alone.
        return {"code": self.get_code(row)}

    def build_defaults(self, row: dict) -> dict:
        # Parent is resolved in a second pass (after all rows exist), so it is
        # NOT set here. Only copy what the source provides.
        return {
            "description": row["description"],
            "chapter": row.get("chapter", ""),
            "group": row.get("group", ""),
            "category": row.get("category", ""),
            "sex_allowed": row.get("sex_allowed", "B"),
            "age_min": row.get("age_min"),
            "age_max": row.get("age_max"),
            "is_notifiable": row.get("is_notifiable", False),
            "version": self.version,
            "active": True,
        }


class Command(BaseCommand):
    help = "Import a hierarchical DATASUS CID-10 table into core.CID10Code"

    def add_arguments(self, parser):
        parser.add_argument(
            "--source", required=True, help="Path to the CID-10 CSV (semicolon-delimited, UTF-8)"
        )
        parser.add_argument("--delimiter", default=";", help="CSV column delimiter (default: ;)")
        # dest is 'cid_version' — NOT 'version' (would collide with BaseCommand's
        # built-in --version). Optional metadata label stored on imported rows.
        parser.add_argument(
            "--cid-version",
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

        # Keep physical line numbers; drop comment lines for the DictReader.
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
            description = pick(raw, "description") or ""
            if not description:
                errors.append(f"  Line {line}: DESCRICAO is empty or blank")
                continue

            sex = (pick(raw, "sex_allowed") or "B").upper()
            if sex not in _SEX_VALID:
                sex = "B"  # unknown/blank → no constraint (never fabricate)

            ages: dict[str, int | None] = {}
            for age_field in ("age_min", "age_max"):
                raw_val = pick(raw, age_field)
                if not raw_val:
                    ages[age_field] = None
                    continue
                try:
                    ages[age_field] = int(raw_val)
                except (TypeError, ValueError):
                    errors.append(f"  Line {line}: {age_field} is not an integer ({raw_val!r})")
                    ages[age_field] = None

            notif = (pick(raw, "is_notifiable") or "").upper() in _TRUE_TOKENS

            rows.append(
                {
                    "code": code,
                    "description": description,
                    "chapter": pick(raw, "chapter") or "",
                    "group": pick(raw, "group") or "",
                    "category": pick(raw, "category") or "",
                    "parent": pick(raw, "parent") or "",
                    "sex_allowed": sex,
                    "age_min": ages["age_min"],
                    "age_max": ages["age_max"],
                    "is_notifiable": notif,
                }
            )

        if errors:
            raise CommandError(
                f"Import aborted — {len(errors)} error(s) found. No rows were committed.\n"
                + "\n".join(errors)
            )
        return rows

    # ── Parent linking ────────────────────────────────────────────────────────

    def _link_parents(self, rows: list[dict]) -> int:
        linked = 0
        with transaction.atomic():
            code_to_pk = dict(CID10Code.objects.values_list("code", "pk"))
            for row in rows:
                parent_code = row.get("parent")
                if not parent_code:
                    continue
                parent_pk = code_to_pk.get(parent_code)
                if parent_pk is None:
                    logger.warning(
                        "CID10 %s references unknown parent %s — left unlinked",
                        row["code"],
                        parent_code,
                    )
                    continue
                CID10Code.objects.filter(code=row["code"]).update(parent_id=parent_pk)
                linked += 1
        return linked

    # ── Entry point ───────────────────────────────────────────────────────────

    def handle(self, *args, **options):
        source_path = Path(options["source"])
        if not source_path.exists():
            raise CommandError(f"File not found: {source_path}")

        delimiter = options["delimiter"]
        version = options["cid_version"]
        dry_run = options["dry_run"]

        self.stdout.write(f"Importing CID-10 from {source_path} (dry_run={dry_run}) …")
        rows = self._parse(source_path, delimiter)

        # Import parents before children so inline parent resolution is stable
        # even without an explicit PARENT column (shorter codes first).
        rows.sort(key=lambda r: (len(r["code"]), r["code"]))

        importer = CID10Importer(
            version=version,
            source=TerminologyImportLog.Source.MANAGEMENT_COMMAND,
            provenance="DATASUS",
            dry_run=dry_run,
        )
        result = importer.run(rows)

        linked = 0
        if not dry_run:
            linked = self._link_parents(rows)
            self._refresh_search_vectors([r["code"] for r in rows])

        if result.errors:
            for err in result.errors[:20]:
                self.stderr.write(self.style.WARNING(err))

        verb = "Would import" if dry_run else "Imported"
        self.stdout.write(
            self.style.SUCCESS(
                f"{verb}: {result.created} created, {result.updated} updated, "
                f"{result.skipped} skipped, {linked} parent link(s). "
                f"Status={result.status}."
            )
        )

    def _refresh_search_vectors(self, codes: list[str]) -> None:
        """Best-effort Postgres full-text vector refresh (non-fatal)."""
        try:
            from django.contrib.postgres.search import SearchVector

            CID10Code.objects.filter(code__in=codes).update(
                search_vector=SearchVector("code", weight="A")
                + SearchVector("description", weight="B")
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not refresh CID10 search vectors: %s", exc)
