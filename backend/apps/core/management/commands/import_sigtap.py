"""
Management command: import_sigtap  (core — S1)
==============================================
Imports the SIGTAP procedure table (SUS) into ``core.SIGTAPProcedure``, keyed on
the SIGTAP code. Uses the E1-T1
:class:`~apps.core.terminology_base.CatalogImporter` engine — idempotent upsert,
**per-row error isolation** (one bad row never aborts the rest), ``--dry-run``
(all writes rolled back), and a
:class:`~apps.core.terminology_base.TerminologyImportLog` provenance row
(provenance = DATASUS/SIGTAP).

Usage:
    python manage.py import_sigtap --source /path/to/sigtap.csv
    python manage.py import_sigtap --source sigtap.csv --sigtap-version 2024-01 --dry-run

Expected CSV (semicolon-delimited, UTF-8; lines starting with '#' are comments):
    CODIGO;PROCEDIMENTO;VALOR_SA;VALOR_SH;VALOR_SP;COMPETENCIA;INSTRUMENTO;COMPLEXIDADE;FINANCIAMENTO;SEXO;IDADE_MIN_DIAS;IDADE_MAX_DIAS

Only CODIGO and PROCEDIMENTO are required (blank → fail-loud abort, reporting the
physical line number). Numeric/choice columns are optional and left at their
inert default when absent; an unparseable numeric cell is isolated per-row
(skipped + reported), not aborting the batch. No value is fabricated here — the
importer copies only what the DATASUS source row provides. SIGTAP is public-domain
DATASUS data; ship infra + a representative sample only.
"""

import csv
import logging
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.core.sigtap_catalog_models import (
    Complexidade,
    InstrumentoRegistro,
    SexoPermitido,
    SIGTAPProcedure,
)
from apps.core.terminology_base import CatalogImporter, TerminologyImportLog

logger = logging.getLogger(__name__)

# Header aliases (DATASUS/SIGTAP exports vary) → canonical row keys.
_COLUMN_ALIASES = {
    "code": ("CODIGO", "codigo", "Código", "CO_PROCEDIMENTO", "COD", "code"),
    "display": (
        "PROCEDIMENTO",
        "procedimento",
        "DESCRICAO",
        "descricao",
        "NO_PROCEDIMENTO",
        "display",
    ),
    "valor_sa": ("VALOR_SA", "valor_sa", "VL_SA", "SA"),
    "valor_sh": ("VALOR_SH", "valor_sh", "VL_SH", "SH"),
    "valor_sp": ("VALOR_SP", "valor_sp", "VL_SP", "SP"),
    "competencia_vigencia": (
        "COMPETENCIA",
        "competencia",
        "Competência",
        "VIGENCIA",
        "COMPETENCIA_VIGENCIA",
    ),
    "instrumento_registro": (
        "INSTRUMENTO",
        "instrumento",
        "INSTRUMENTO_REGISTRO",
        "TP_COMPLEXIDADE_INSTR",
    ),
    "complexidade": ("COMPLEXIDADE", "complexidade", "Complexidade", "TP_COMPLEXIDADE"),
    "financiamento": ("FINANCIAMENTO", "financiamento", "Financiamento", "FONTE"),
    "sexo_permitido": ("SEXO", "sexo", "Sexo", "SEXO_PERMITIDO", "TP_SEXO"),
    "idade_min_dias": ("IDADE_MIN_DIAS", "idade_min_dias", "VL_IDADE_MINIMA", "IDADE_MIN"),
    "idade_max_dias": ("IDADE_MAX_DIAS", "idade_max_dias", "VL_IDADE_MAXIMA", "IDADE_MAX"),
}

_VALID_INSTRUMENTO = set(InstrumentoRegistro.values)
_VALID_COMPLEXIDADE = set(Complexidade.values)
_VALID_SEXO = set(SexoPermitido.values)


def _to_decimal(value: str | None) -> Decimal:
    """Parse a CSV cell to Decimal (no float). Blank → 0; garbage → raises.

    Accepts Brazilian decimal comma ("12,50") as well as "12.50". Raising on
    garbage lets :class:`CatalogImporter` isolate the offending row rather than
    silently fabricating a value.
    """
    raw = (value or "").strip()
    if not raw:
        return Decimal("0")
    raw = raw.replace(".", "").replace(",", ".") if "," in raw else raw
    try:
        return Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError(f"invalid decimal value {value!r}") from exc


def _to_opt_int(value: str | None) -> int | None:
    """Parse an optional positive-int cell. Blank → None; garbage → raises."""
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid integer value {value!r}") from exc


class SIGTAPImporter(CatalogImporter):
    """CatalogImporter bound to SIGTAPProcedure, keyed on (system, codigo, version).

    ``build_defaults`` performs the Decimal/int coercion and choice validation;
    an unparseable numeric cell or invalid choice raises here and is isolated
    per-row by the engine's savepoint.
    """

    model = SIGTAPProcedure
    system = "sigtap"

    def build_defaults(self, row: dict) -> dict:
        display = (row.get("display") or "").strip()
        if not display:
            raise ValueError("row is missing a non-empty 'display' (PROCEDIMENTO)")

        instrumento = (row.get("instrumento_registro") or "").strip().lower()
        if instrumento and instrumento not in _VALID_INSTRUMENTO:
            raise ValueError(f"invalid instrumento {instrumento!r}")
        complexidade = (row.get("complexidade") or "").strip().lower()
        if complexidade and complexidade not in _VALID_COMPLEXIDADE:
            raise ValueError(f"invalid complexidade {complexidade!r}")
        sexo = (row.get("sexo_permitido") or "").strip()
        if sexo and sexo not in _VALID_SEXO:
            raise ValueError(f"invalid sexo {sexo!r}")

        return {
            "display": display,
            "valor_sa": _to_decimal(row.get("valor_sa")),
            "valor_sh": _to_decimal(row.get("valor_sh")),
            "valor_sp": _to_decimal(row.get("valor_sp")),
            "competencia_vigencia": (row.get("competencia_vigencia") or "").strip(),
            "instrumento_registro": instrumento or InstrumentoRegistro.OUTROS,
            "complexidade": complexidade or Complexidade.NAO_SE_APLICA,
            "financiamento": (row.get("financiamento") or "").strip(),
            "sexo_permitido": sexo or SexoPermitido.AMBOS,
            "idade_min_dias": _to_opt_int(row.get("idade_min_dias")),
            "idade_max_dias": _to_opt_int(row.get("idade_max_dias")),
            "active": True,
        }


class Command(BaseCommand):
    help = "Import a SIGTAP (SUS) procedure catalog into core.SIGTAPProcedure"

    def add_arguments(self, parser):
        parser.add_argument(
            "--source", required=True, help="Path to the SIGTAP CSV (semicolon-delimited, UTF-8)"
        )
        parser.add_argument("--delimiter", default=";", help="CSV column delimiter (default: ;)")
        # dest is 'sigtap_version' — NOT 'version' (would collide with
        # BaseCommand's built-in --version). Optional data-version label, e.g.
        # the competência "2024-01".
        parser.add_argument(
            "--sigtap-version",
            default="",
            help='Optional data-version label stored on rows, e.g. "2024-01".',
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Validate + preview without persisting (all writes rolled back).",
        )

    # ── Parsing ───────────────────────────────────────────────────────────────

    def _parse(self, source_path: Path, delimiter: str) -> list[dict]:
        """Parse + per-line validate the CSV. Structural problems (empty file /
        header-only) and blank required fields (code / display) fail loud,
        reporting TRUE physical line numbers. Per-row numeric/choice data
        problems are left for the importer to isolate. Parsing never writes."""
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

        def pick(raw: dict, key: str) -> str:
            for alias in _COLUMN_ALIASES[key]:
                if alias in raw and raw[alias] is not None:
                    return raw[alias].strip()
            return ""

        rows: list[dict] = []
        errors: list[str] = []
        for data_idx, raw in enumerate(raw_rows):
            line = phys(data_idx)
            code = pick(raw, "code")
            if not code:
                errors.append(f"  Line {line}: CODIGO is empty or blank")
                continue
            display = pick(raw, "display")
            if not display:
                errors.append(f"  Line {line}: PROCEDIMENTO is empty or blank")
                continue
            rows.append({key: pick(raw, key) for key in _COLUMN_ALIASES})

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
        version = options["sigtap_version"]
        dry_run = options["dry_run"]

        self.stdout.write(f"Importing SIGTAP catalog from {source_path} (dry_run={dry_run}) …")
        rows = self._parse(source_path, delimiter)

        importer = SIGTAPImporter(
            version=version,
            source=TerminologyImportLog.Source.MANAGEMENT_COMMAND,
            provenance="DATASUS/SIGTAP",
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
