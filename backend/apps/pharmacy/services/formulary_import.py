"""
Formulary CSV import service (D-T1).
====================================
Single source of truth for parsing, validating and upserting a dose-formulary
CSV into ``pharmacy.MedicationFormulary`` + ``pharmacy.DoseRule``.

This module is shared by BOTH consumers of the import:
  * the ``import_formulary`` management command (CLI / ops), and
  * the pharmacist-facing upload UI API (``FormularyUploadPreviewView`` /
    ``FormularyUploadCommitView``).

INVIOLABLE PRINCIPLE (carried over from the original command): no clinical
number is ever invented here. The importer only reads what the CSV provides.
Imported DoseRules are NEVER self-validated — ``validated=False`` is the default
and MUST remain so until a human pharmacist signs off each rule via the curation
UI (``DoseRuleViewSet.validate``). A rule that is ``active=True`` but
``validated=False`` is inert in the DoseChecker; only the explicit pharmacist
sign-off arms it. That sign-off gate is what makes it safe to turn the
``dose_safety`` feature flag ON after an upload.

Behaviour preserved from the command:
  - Idempotent: MedicationFormulary upsert by drug name; DoseRule upsert by
    natural key (basis + dose_role + route + freq + age/weight bands).
  - Fail-loud: ALL parse + model-validation errors are collected and raised
    together via ``FormularyImportError`` BEFORE any commit. No partial imports.
  - Physical line numbers (1-based, counting comment lines) are reported in
    error messages so operators can find the bad row in any editor.
  - Lines starting with '#' are treated as comments and skipped.

Expected CSV columns (comma-delimited by default) — see the management command
docstring for the full per-column contract.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.pharmacy.models import DoseRule, Drug, MedicationFormulary

# Natural-key fields for DoseRule update_or_create lookup (matches the
# doserule_natural_key UniqueConstraint in DoseRule.Meta; includes all four
# age/weight band fields so rules differing only by patient band are not
# collapsed on re-import).
_DOSERULE_NATURAL_KEY = (
    "basis",
    "dose_role",
    "route",
    "freq_min_per_day",
    "freq_max_per_day",
    "age_min_days",
    "age_max_days",
    "weight_min_kg",
    "weight_max_kg",
)

# Clinical fields of a DoseRule whose change INVALIDATES a prior pharmacist
# sign-off. If a re-imported CSV changes any of these on an existing rule, the
# rule's ``validated`` flag (and by/at trail) MUST be reset: the new numbers
# were never signed off, so they may not enter the DoseChecker armed, and the
# audit trail may not keep pointing at the pharmacist who validated the OLD
# values. ``dose_unit`` is included deliberately — same numbers in a different
# unit are a different clinical rule.
_DOSERULE_CLINICAL_FIELDS = (
    "dose_unit",
    "enforcement",
    "min_per_dose",
    "max_per_dose",
    "min_per_kg",
    "max_per_kg",
    "absolute_max_dose",
    "max_per_day",
)


class FormularyImportError(Exception):
    """Raised when a CSV fails to parse or validate.

    Carries the full list of human-readable, line-numbered error strings so the
    caller (CLI or API) can render all of them at once — never a partial import.
    """

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("\n".join(errors))


@dataclass
class ImportSummary:
    """Counts returned by a preview (dry-run) or a committed import.

    ``revalidation_required`` counts existing VALIDATED rules whose clinical
    fields changed in this import — each one is de-armed (validated=False,
    by/at cleared) and needs a fresh pharmacist sign-off.
    ``changed_rules`` carries per-rule before/after detail for every existing
    rule whose clinical fields changed (validated or not); it is meant for the
    commit audit log, not for the JSON summary (hence excluded from as_dict).
    """

    row_count: int
    formularies_created: int
    formularies_updated: int
    rules_created: int
    rules_updated: int
    revalidation_required: int = 0
    changed_rules: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "row_count": self.row_count,
            "formularies_created": self.formularies_created,
            "formularies_updated": self.formularies_updated,
            "rules_created": self.rules_created,
            "rules_updated": self.rules_updated,
            "revalidation_required": self.revalidation_required,
        }


# ── cell parsers ──────────────────────────────────────────────────────────────


def _opt_decimal(row: dict, col: str) -> Decimal | None:
    """Return a Decimal from a CSV cell, or None if the column is missing/empty."""
    raw = row.get(col, "").strip()
    if not raw:
        return None
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError):
        raise ValueError(f"column '{col}' is not a valid decimal: {raw!r}") from None


def _opt_int(row: dict, col: str) -> int | None:
    """Return an int from a CSV cell, or None if the column is missing/empty."""
    raw = row.get(col, "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except (ValueError, TypeError):
        raise ValueError(f"column '{col}' is not a valid integer: {raw!r}") from None


def _required_str(row: dict, col: str) -> str:
    """Return a stripped string from a CSV cell; raise ValueError if empty/missing."""
    raw = row.get(col, "").strip()
    if not raw:
        raise ValueError(f"required column '{col}' is missing or empty")
    return raw


def parse_row(row: dict, *, line_number: int) -> dict:
    """Parse and validate one CSV row into a dict of typed values.

    Raises ValueError with a human-readable message on any parse failure.
    No clinical defaults are invented — every value comes from the CSV.
    """
    entry: dict = {"_line_number": line_number}

    entry["drug_name"] = _required_str(row, "drug_name")
    entry["drug_generic"] = row.get("drug_generic", "").strip()
    entry["strength_value"] = _opt_decimal(row, "strength_value")
    if entry["strength_value"] is None:
        raise ValueError("required column 'strength_value' is missing or empty")
    entry["strength_unit"] = _required_str(row, "strength_unit")
    entry["route"] = _required_str(row, "route")
    entry["basis"] = _required_str(row, "basis")
    if entry["basis"] not in ("per_kg", "fixed"):
        raise ValueError(f"column 'basis' must be 'per_kg' or 'fixed', got {entry['basis']!r}")
    entry["dose_unit"] = _required_str(row, "dose_unit")
    entry["dose_role"] = row.get("dose_role", "maintenance").strip() or "maintenance"

    # block vs advise (dose-engine v2, AXIS 3). Optional column; blank → 'block'
    # (the safe default). 'advise' is for drugs with no hard pharmacological
    # ceiling (opioids/sedatives) where the "max" is an alert threshold, not a
    # physical block. Honouring this per drug is what makes dose_safety
    # clinically correct rather than blanket-blocking every titrated drug.
    entry["enforcement"] = row.get("enforcement", "block").strip().lower() or "block"
    if entry["enforcement"] not in ("block", "advise"):
        raise ValueError(
            f"column 'enforcement' must be 'block' or 'advise', got {entry['enforcement']!r}"
        )

    entry["absolute_max_dose"] = _opt_decimal(row, "absolute_max_dose")
    if entry["absolute_max_dose"] is None:
        raise ValueError("required column 'absolute_max_dose' is missing or empty")

    entry["min_per_dose"] = _opt_decimal(row, "min_per_dose")
    entry["max_per_dose"] = _opt_decimal(row, "max_per_dose")
    entry["min_per_kg"] = _opt_decimal(row, "min_per_kg")
    entry["max_per_kg"] = _opt_decimal(row, "max_per_kg")
    entry["max_per_day"] = _opt_decimal(row, "max_per_day")
    entry["freq_min_per_day"] = _opt_int(row, "freq_min_per_day")
    entry["freq_max_per_day"] = _opt_int(row, "freq_max_per_day")

    # Age/weight band columns (all optional; blank → None = unbounded).
    # These are part of the natural key so that rules differing only by
    # patient band (e.g. neonate vs child vs adult) can coexist for the
    # same drug/route/basis without collapsing each other on re-import.
    entry["age_min_days"] = _opt_int(row, "age_min_days")
    entry["age_max_days"] = _opt_int(row, "age_max_days")
    entry["weight_min_kg"] = _opt_decimal(row, "weight_min_kg")
    entry["weight_max_kg"] = _opt_decimal(row, "weight_max_kg")

    return entry


# ── CSV → parsed rows (with full validation) ─────────────────────────────────


def _physical_lines(all_lines: list[str]) -> list[tuple[int, str]]:
    """(physical_line_number, line_text) for every non-comment line.

    Comment lines (starting with '#') are filtered out for DictReader, but their
    physical line numbers are preserved so error messages reference the TRUE
    position in the file.
    """
    return [
        (phys_idx + 1, ln)
        for phys_idx, ln in enumerate(all_lines)
        if not ln.lstrip().startswith("#")
    ]


def parse_and_validate(content: str, *, delimiter: str = ",") -> list[dict]:
    """Parse CSV text → list of validated parsed-row dicts.

    Runs the SAME two passes the command always ran:
      1. per-row parse (``parse_row``), and
      2. model-layer ``DoseRule.full_clean`` (per-basis invariants).
    ALL errors are collected; if any exist, a single ``FormularyImportError`` is
    raised and NOTHING is parsed-through. On success every row is guaranteed to
    parse and to satisfy the model field/clean validators.
    """
    all_lines = content.splitlines(keepends=True)
    physical_lines = _physical_lines(all_lines)
    if not physical_lines:
        raise FormularyImportError(["CSV file is empty or contains only comments."])

    # Feed only the text to DictReader (first kept line is the header).
    kept_texts = [ln for _, ln in physical_lines]
    reader = csv.DictReader(kept_texts, delimiter=delimiter)
    rows = list(reader)
    if not rows:
        raise FormularyImportError(["CSV file has a header but no data rows."])

    # Map each data row (0-based index into rows) to its physical line number.
    # physical_lines[0] is the header; physical_lines[i+1] is data row i.
    def _physical_line(data_row_index: int) -> int:
        kept_idx = data_row_index + 1  # +1 to skip the header kept line
        if kept_idx < len(physical_lines):
            return physical_lines[kept_idx][0]
        return data_row_index + 2  # fallback (should not happen)

    # ── Pass 1: per-row parse (collect ALL errors) ────────────────────────────
    line_errors: list[str] = []
    parsed_rows: list[dict] = []
    for data_idx, row in enumerate(rows):
        phys_line = _physical_line(data_idx)
        try:
            parsed_rows.append(parse_row(row, line_number=phys_line))
        except (ValueError, KeyError) as exc:
            line_errors.append(f"Line {phys_line}: {exc}")

    if line_errors:
        raise FormularyImportError(line_errors)

    # ── Pass 2: model-layer validation (full_clean) — still pre-commit ────────
    validation_errors: list[str] = []
    drug_name_max = Drug._meta.get_field("name").max_length
    drug_generic_max = Drug._meta.get_field("generic_name").max_length
    for entry in parsed_rows:
        # Drug field lengths — checked here so an oversized cell is a per-line
        # error instead of a DB-level DataError (HTTP 500) inside the atomic
        # block of write_rows.
        if drug_name_max and len(entry["drug_name"]) > drug_name_max:
            validation_errors.append(
                f"Line {entry['_line_number']}: column 'drug_name' exceeds "
                f"{drug_name_max} characters"
            )
        if drug_generic_max and len(entry.get("drug_generic", "")) > drug_generic_max:
            validation_errors.append(
                f"Line {entry['_line_number']}: column 'drug_generic' exceeds "
                f"{drug_generic_max} characters"
            )

        # MedicationFormulary constraints (strength_value max_digits/decimal_places,
        # strength_unit max_length/choices, route choices) — same fail-loud
        # per-line contract; without this a bad strength blows up mid-transaction.
        formulary_instance = MedicationFormulary(
            strength_value=entry["strength_value"],
            strength_unit=entry["strength_unit"],
            route=entry["route"],
            active=True,
        )
        try:
            formulary_instance.full_clean(exclude=["drug"])
        except ValidationError as exc:
            validation_errors.append(f"Line {entry['_line_number']}: {exc.message_dict}")

        rule_instance = DoseRule(
            # formulary FK intentionally left unset for this in-memory pass;
            # full_clean(exclude=["formulary"]) checks field-level + clean()
            # invariants without requiring the FK.
            basis=entry["basis"],
            dose_role=entry["dose_role"],
            enforcement=entry["enforcement"],
            dose_unit=entry["dose_unit"],
            route=entry["route"],
            min_per_dose=entry.get("min_per_dose"),
            max_per_dose=entry.get("max_per_dose"),
            min_per_kg=entry.get("min_per_kg"),
            max_per_kg=entry.get("max_per_kg"),
            absolute_max_dose=entry["absolute_max_dose"],
            max_per_day=entry.get("max_per_day"),
            freq_min_per_day=entry.get("freq_min_per_day"),
            freq_max_per_day=entry.get("freq_max_per_day"),
            age_min_days=entry.get("age_min_days"),
            age_max_days=entry.get("age_max_days"),
            weight_min_kg=entry.get("weight_min_kg"),
            weight_max_kg=entry.get("weight_max_kg"),
            active=True,
            validated=False,  # NEVER self-validate; human sign-off required
        )
        try:
            rule_instance.full_clean(exclude=["formulary"])
        except ValidationError as exc:
            validation_errors.append(f"Line {entry['_line_number']}: {exc.message_dict}")

    if validation_errors:
        raise FormularyImportError(validation_errors)

    return parsed_rows


def decode_csv(raw: bytes) -> str:
    """Decode uploaded CSV bytes: UTF-8 (BOM tolerant) with a Windows fallback.

    Excel on Windows PT-BR exports CSV as cp1252, not UTF-8 — the primary user
    of this upload is a pharmacist on exactly that setup, so we fall back to
    cp1252 (then latin-1) when strict UTF-8 fails. The fallback is safe for the
    numeric/clinical columns (ASCII is identical in all three encodings); only
    accented free-text like drug names is affected, and cp1252 is the correct
    guess for those files. Binary/UTF-16 uploads are rejected via the NUL check
    rather than being silently mojibake'd. Raises ``FormularyImportError`` with
    a friendly message instead of letting a raw UnicodeDecodeError escape.
    """
    text: str | None = None
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None or "\x00" in text:
        raise FormularyImportError(
            [
                "Não foi possível ler o arquivo como texto CSV (UTF-8 ou Windows-1252). "
                "Salve o CSV em UTF-8 e tente novamente."
            ]
        )
    return text


# ── parsed rows → DB (upsert) ────────────────────────────────────────────────


def write_rows(parsed_rows: list[dict], *, dry_run: bool = False) -> ImportSummary:
    """Upsert parsed rows into MedicationFormulary + DoseRule, atomically.

    ``dry_run=True`` performs the full ORM work inside a transaction that is
    always rolled back, so the returned counts reflect exactly what a real commit
    WOULD do without persisting anything (used by the preview endpoint).
    """
    formularies_created = formularies_updated = rules_created = rules_updated = 0
    revalidation_required = 0
    changed_rules: list[dict] = []

    with transaction.atomic():
        for entry in parsed_rows:
            # 1. Ensure the Drug exists (get_or_create by name).
            drug, _ = Drug.objects.get_or_create(
                name=entry["drug_name"],
                defaults={"generic_name": entry.get("drug_generic", "")},
            )

            # 2. Upsert the MedicationFormulary entry (one per drug).
            formulary, f_created = MedicationFormulary.objects.update_or_create(
                drug=drug,
                defaults={
                    "strength_value": entry["strength_value"],
                    "strength_unit": entry["strength_unit"],
                    "route": entry["route"],
                    "active": True,
                },
            )
            if f_created:
                formularies_created += 1
            else:
                formularies_updated += 1

            # 3. Upsert the DoseRule by natural key. The key includes all four
            #    band fields so rules differing only by patient band are not
            #    collapsed — each band gets its own row. Django's
            #    update_or_create handles None lookups as IS NULL, which combined
            #    with nulls_distinct=False on the UniqueConstraint means NULL-band
            #    rules also upsert correctly instead of accumulating duplicates.
            natural_key = {
                "formulary": formulary,
                "basis": entry["basis"],
                "dose_role": entry["dose_role"],
                "route": entry.get("route", ""),
                "freq_min_per_day": entry.get("freq_min_per_day"),
                "freq_max_per_day": entry.get("freq_max_per_day"),
                "age_min_days": entry.get("age_min_days"),
                "age_max_days": entry.get("age_max_days"),
                "weight_min_kg": entry.get("weight_min_kg"),
                "weight_max_kg": entry.get("weight_max_kg"),
            }
            rule_defaults = {
                "dose_unit": entry["dose_unit"],
                "enforcement": entry["enforcement"],
                "min_per_dose": entry.get("min_per_dose"),
                "max_per_dose": entry.get("max_per_dose"),
                "min_per_kg": entry.get("min_per_kg"),
                "max_per_kg": entry.get("max_per_kg"),
                "absolute_max_dose": entry["absolute_max_dose"],
                "max_per_day": entry.get("max_per_day"),
                "active": True,
                # validated stays False — human sign-off only, NEVER set by importer
            }

            # Detect clinically-changed fields BEFORE the upsert so a re-import
            # can (a) de-arm a previously validated rule and (b) leave a
            # before/after trail for the audit log.
            existing_rule = DoseRule.objects.filter(**natural_key).first()
            changed_fields: dict[str, dict] = {}
            if existing_rule is not None:
                for clinical_field in _DOSERULE_CLINICAL_FIELDS:
                    old = getattr(existing_rule, clinical_field)
                    new = rule_defaults[clinical_field]
                    if old != new:
                        changed_fields[clinical_field] = {
                            "before": None if old is None else str(old),
                            "after": None if new is None else str(new),
                        }
                if changed_fields:
                    changed_rules.append(
                        {
                            "drug": entry["drug_name"],
                            "route": entry.get("route", ""),
                            "basis": entry["basis"],
                            "dose_role": entry["dose_role"],
                            "was_validated": existing_rule.validated,
                            "changes": changed_fields,
                        }
                    )

            # SAFETY GATE: a validated rule whose clinical numbers changed goes
            # BACK to pending. The new values were never signed off — they must
            # not enter the DoseChecker armed, and validated_by/at must not keep
            # pointing at the pharmacist who approved the OLD values.
            if existing_rule is not None and existing_rule.validated and changed_fields:
                rule_defaults.update(
                    validated=False,
                    validated_by=None,
                    validated_at=None,
                )
                revalidation_required += 1

            _rule, r_created = DoseRule.objects.update_or_create(
                **natural_key,
                defaults=rule_defaults,
            )
            if r_created:
                rules_created += 1
            else:
                rules_updated += 1

        if dry_run:
            transaction.set_rollback(True)

    return ImportSummary(
        row_count=len(parsed_rows),
        formularies_created=formularies_created,
        formularies_updated=formularies_updated,
        rules_created=rules_created,
        rules_updated=rules_updated,
        revalidation_required=revalidation_required,
        changed_rules=changed_rules,
    )


# ── preview row serialization (for the upload UI) ────────────────────────────


def _band(low, high) -> str:
    """Render an optional [low, high] band as a human string ('—' when open)."""
    if low is None and high is None:
        return "—"
    lo = "—" if low is None else f"{low}"
    hi = "—" if high is None else f"{high}"
    return f"{lo}–{hi}"


def serialize_preview_row(entry: dict) -> dict:
    """Flat, JSON-safe display row for the preview table (all values are strings).

    The frontend renders these verbatim — it performs NO clinical math. Decimals
    are stringified so no float coercion can misrepresent a dose figure.
    """
    if entry["basis"] == "per_kg":
        therapeutic = (
            f"{_band(entry.get('min_per_kg'), entry.get('max_per_kg'))} {entry['dose_unit']}/kg"
        )
    else:
        therapeutic = (
            f"{_band(entry.get('min_per_dose'), entry.get('max_per_dose'))} {entry['dose_unit']}"
        )

    return {
        "line": entry["_line_number"],
        "drug_name": entry["drug_name"],
        "drug_generic": entry.get("drug_generic", ""),
        "strength": f"{entry['strength_value']} {entry['strength_unit']}",
        "route": entry["route"],
        "basis": entry["basis"],
        "dose_role": entry["dose_role"],
        "enforcement": entry["enforcement"],
        "dose_unit": entry["dose_unit"],
        "therapeutic_band": therapeutic,
        "absolute_max_dose": f"{entry['absolute_max_dose']} {entry['dose_unit']}",
        "max_per_day": (
            f"{entry['max_per_day']} {entry['dose_unit']}" if entry.get("max_per_day") else "—"
        ),
        "age_band_days": _band(entry.get("age_min_days"), entry.get("age_max_days")),
        "weight_band_kg": _band(entry.get("weight_min_kg"), entry.get("weight_max_kg")),
        "freq_band_per_day": _band(entry.get("freq_min_per_day"), entry.get("freq_max_per_day")),
    }
