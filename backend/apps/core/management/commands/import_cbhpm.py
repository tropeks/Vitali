"""
Management command: import_cbhpm  (core — M1-S1)
================================================
Imports a CBHPM/AMB procedure table into ``core.CBHPMItem``, keyed on the CBHPM
code. Uses the E1-T1 :class:`~apps.core.terminology_base.CatalogImporter` engine
— idempotent upsert, **per-row error isolation** (one bad row never aborts the
rest), ``--dry-run`` (all writes rolled back), and a
:class:`~apps.core.terminology_base.TerminologyImportLog` provenance row
(provenance = CBHPM/AMB).

Usage:
    python manage.py import_cbhpm --source /path/to/cbhpm.csv
    python manage.py import_cbhpm --source cbhpm.csv --cbhpm-version 2024 --dry-run

Expected CSV (semicolon-delimited, UTF-8; lines starting with '#' are comments):
    CODIGO;DESCRICAO;PORTE;VALOR_CH;PORTE_ANESTESICO;NUMERO_FILME;NUMERO_AUXILIARES;VIGENCIA
    (PORTE = classe publicada: '3B', '0,01 de 1A'. PORTE_CH, opcional, e a
     quantidade de CH da tabela de valoracao CONTRATADA — nunca vem do livro.)

Only CODIGO and DESCRICAO are required; every other column is optional and left
at its inert default when absent. No value is fabricated here — the importer
copies only what the CBHPM/AMB source row provides. Rows with a blank code /
description, or an unparseable numeric field, are isolated per-row (skipped +
reported), not aborting the batch.
"""

import csv
import logging
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.core.cbhpm_models import CBHPMItem
from apps.core.terminology_base import CatalogImporter, TerminologyImportLog

logger = logging.getLogger(__name__)

# Header aliases (CBHPM/AMB exports vary) → canonical row keys.
_COLUMN_ALIASES = {
    "code": ("CODIGO", "codigo", "Código", "COD", "CBHPM", "code"),
    "display": ("DESCRICAO", "descricao", "Descrição", "PROCEDIMENTO", "display"),
    # PORTE_CH saiu daqui na ordem 013: e outra coisa. "PORTE" e a classe
    # publicada ("3B", "0,01 de 1A"); "PORTE_CH" e a quantidade de CH da tabela
    # de valoracao CONTRATADA. Misturar os dois era o que fazia o importador
    # tentar ler "3B" como decimal.
    "porte": ("PORTE", "porte"),
    "porte_ch": ("PORTE_CH", "porte_ch", "CH_PORTE"),
    "valor_ch": ("VALOR_CH", "valor_ch", "CH", "UCO", "VALOR_UCO", "valor_uco"),
    "porte_anestesico": ("PORTE_ANESTESICO", "porte_anestesico", "PORTE_ANEST", "ANESTESICO"),
    "numero_filme": ("NUMERO_FILME", "numero_filme", "FILME", "N_FILME"),
    "numero_auxiliares": ("NUMERO_AUXILIARES", "numero_auxiliares", "AUXILIARES", "N_AUX"),
    "vigencia": ("VIGENCIA", "vigencia", "Vigência", "COMPETENCIA"),
}


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


_PORTE_VALIDO = re.compile(r"^(?:\d{1,2}[ABC]?|[0-9]+,[0-9]+ de \d{1,2}[ABC]?)$")


def _porte_publicado(value: str | None) -> str:
    """Devolve a classe de porte como publicada, ou levanta.

    Aceita as duas formas que a CBHPM usa: a classe cheia ("3B", "13C") e a
    fracao de classe da Medicina Laboratorial ("0,01 de 1A"). Travessao e vazio
    viram string vazia — "nao informado" é um estado legítimo.

    Levantar em qualquer outra coisa é deliberado: o ``CatalogImporter`` isola a
    linha e a reporta, em vez de gravar um porte que ninguem publicou. Porte
    errado aqui vira honorario errado la na frente.
    """
    bruto = (value or "").strip()
    if bruto in ("", "-", "\u2013", "\u2014"):
        return ""
    if not _PORTE_VALIDO.match(bruto):
        raise ValueError(f"porte fora do vocabulario da CBHPM: {value!r}")
    return bruto


def _to_int(value: str | None) -> int:
    raw = (value or "").strip()
    if not raw:
        return 0
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid integer value {value!r}") from exc


class CBHPMImporter(CatalogImporter):
    """CatalogImporter bound to CBHPMItem, keyed on (system, codigo, version).

    ``build_defaults`` performs the Decimal/int coercion; an unparseable numeric
    cell raises here and is isolated per-row by the engine's savepoint.
    """

    model = CBHPMItem
    system = "cbhpm"

    def build_defaults(self, row: dict) -> dict:
        display = (row.get("display") or "").strip()
        if not display:
            raise ValueError("row is missing a non-empty 'display' (DESCRICAO)")
        return {
            "display": display,
            "porte": _porte_publicado(row.get("porte")),
            "porte_ch": _to_decimal(row.get("porte_ch")),
            "valor_ch": _to_decimal(row.get("valor_ch")),
            "porte_anestesico": (row.get("porte_anestesico") or "").strip(),
            "numero_filme": _to_decimal(row.get("numero_filme")),
            "numero_auxiliares": _to_int(row.get("numero_auxiliares")),
            "vigencia": (row.get("vigencia") or "").strip(),
            "active": True,
        }


class Command(BaseCommand):
    help = "Import a CBHPM/AMB procedure catalog into core.CBHPMItem"

    def add_arguments(self, parser):
        parser.add_argument(
            "--source", required=True, help="Path to the CBHPM CSV (semicolon-delimited, UTF-8)"
        )
        parser.add_argument("--delimiter", default=";", help="CSV column delimiter (default: ;)")
        # dest is 'cbhpm_version' — NOT 'version' (would collide with BaseCommand's
        # built-in --version). Optional metadata label stored on imported rows.
        parser.add_argument(
            "--cbhpm-version",
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
        """Read + map the CSV to canonical row dicts. Structural problems (empty
        file / header-only) fail loud; per-row data problems are left for the
        importer to isolate (per-line error isolation)."""
        with open(source_path, encoding="utf-8-sig", newline="") as fh:
            data_lines = [ln for ln in fh if not ln.lstrip().startswith("#")]

        if not data_lines:
            raise CommandError("CSV file is empty or contains only comments.")

        reader = csv.DictReader(data_lines, delimiter=delimiter)
        raw_rows = list(reader)
        if not raw_rows:
            raise CommandError("CSV has a header but no data rows.")

        def pick(raw: dict, key: str) -> str:
            for alias in _COLUMN_ALIASES[key]:
                if alias in raw and raw[alias] is not None:
                    return raw[alias].strip()
            return ""

        rows: list[dict] = []
        for raw in raw_rows:
            rows.append({key: pick(raw, key) for key in _COLUMN_ALIASES})
        return rows

    # ── Entry point ───────────────────────────────────────────────────────────

    def handle(self, *args, **options):
        source_path = Path(options["source"])
        if not source_path.exists():
            raise CommandError(f"File not found: {source_path}")

        delimiter = options["delimiter"]
        version = options["cbhpm_version"]
        dry_run = options["dry_run"]

        self.stdout.write(f"Importing CBHPM catalog from {source_path} (dry_run={dry_run}) …")
        rows = self._parse(source_path, delimiter)

        importer = CBHPMImporter(
            version=version,
            source=TerminologyImportLog.Source.MANAGEMENT_COMMAND,
            provenance="CBHPM/AMB",
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
