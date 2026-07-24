"""
Terminology backbone (Sprint E1-T1)
===================================
Reusable foundation for governed master-data terminology catalogs that live in
the **SHARED (public)** schema — CID-10 (E1-T2), and later ANVISA/DCB, CBHPM,
CBO, CNES, LOINC, … . Two pieces:

* :class:`TerminologyCatalog` — an abstract base model giving every catalog the
  same governed shape: ``code`` / ``display`` / ``system`` / ``version`` /
  ``active`` plus a ``normalized_display`` column kept in sync on ``save()`` for
  accent-and-case-insensitive lookup (Postgres unaccent is optional; we do not
  depend on the extension being installed).

* :class:`CatalogImporter` — an idempotent, provenance-logged import engine
  (mixin/base) reused by every catalog importer. It upserts keyed on the natural
  key ``(system, code, version)``, isolates per-row errors (one bad row never
  aborts the rest), supports ``dry_run`` (all writes rolled back), and records a
  :class:`TerminologyImportLog` row — the same shape as ``TUSSSyncLog`` but
  generic across systems.

No clinical/terminology value is ever fabricated here: the importer only writes
what the caller's ``build_defaults`` returns from a source row.
"""

from __future__ import annotations

import time
import unicodedata
from dataclasses import dataclass, field

from django.db import models, transaction

# ─── Normalization ────────────────────────────────────────────────────────────


def normalize_text(value: str | None) -> str:
    """Fold accents + case for accent/case-insensitive search keys.

    "Diabetes Melito" and "diabetes mellitus" style queries should match a
    stored ``normalized_display`` regardless of accents or casing. This is a
    pure-Python fallback so search works even when the Postgres ``unaccent``
    extension is not installed (E1-T4 upgrades to unaccent/ILIKE when present).
    """
    if not value:
        return ""
    nfkd = unicodedata.normalize("NFKD", str(value))
    stripped = "".join(ch for ch in nfkd if not unicodedata.combining(ch))
    return stripped.casefold().strip()


# ─── Abstract catalog base ────────────────────────────────────────────────────


class TerminologyCatalog(models.Model):
    """Abstract base for a governed terminology catalog (SHARED schema).

    Concrete subclasses (e.g. a future CBHPM/CBO/LOINC catalog, and the E1-T1
    test fixture) inherit the governed columns and the ``normalized_display``
    sync. ``CID10Code`` reuses the same field vocabulary and importer without
    structurally inheriting (its ``code`` is already globally unique on a
    populated table — see E1-T2).
    """

    code = models.CharField("Código", max_length=32, db_index=True)
    display = models.CharField("Descrição", max_length=500)
    system = models.CharField(
        "Sistema/terminologia",
        max_length=32,
        db_index=True,
        help_text="Identificador do sistema de terminologia (ex.: cid10, tuss, cbhpm).",
    )
    version = models.CharField("Versão", max_length=32, blank=True, default="")
    active = models.BooleanField("Ativo", default=True, db_index=True)
    normalized_display = models.CharField(
        "Descrição normalizada",
        max_length=500,
        blank=True,
        default="",
        db_index=True,
        help_text="display sem acentos e em minúsculas — mantido em sincronia no save().",
    )

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        # Keep the normalized search column in sync on every write.
        self.normalized_display = normalize_text(self.display)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.code} — {self.display[:60]}"


# ─── Provenance log (generic TUSSSyncLog analogue) ────────────────────────────


class TerminologyImportLog(models.Model):
    """Provenance record for a terminology catalog import run.

    Generic sibling of ``TUSSSyncLog``: one row per import run, per system, so
    ops can verify any catalog is current and audit where its data came from.
    Lives in the PUBLIC schema (apps.core is SHARED) — the catalogs are global,
    so their import logs are global too.
    """

    class Status(models.TextChoices):
        SUCCESS = "success", "Sucesso"
        PARTIAL = "partial", "Parcial"
        ERROR = "error", "Erro"

    class Source(models.TextChoices):
        MANAGEMENT_COMMAND = "management_command", "Management Command"
        API = "api", "API"
        SCHEDULED = "scheduled", "Agendado"

    import uuid as _uuid

    id = models.UUIDField(primary_key=True, default=_uuid.uuid4, editable=False)
    system = models.CharField("Sistema/terminologia", max_length=32, db_index=True)
    version = models.CharField("Versão", max_length=32, blank=True, default="")
    ran_at = models.DateTimeField(auto_now_add=True, db_index=True)
    source = models.CharField(
        max_length=30,
        choices=Source.choices,
        default=Source.MANAGEMENT_COMMAND,
        help_text="Origem da carga (ex.: DATASUS via management command).",
    )
    provenance = models.CharField(
        "Proveniência",
        max_length=100,
        blank=True,
        default="",
        help_text="Fonte de dados dos registros (ex.: DATASUS).",
    )
    row_count_total = models.PositiveIntegerField(default=0)
    row_count_added = models.PositiveIntegerField(default=0)
    row_count_updated = models.PositiveIntegerField(default=0)
    row_count_errors = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.SUCCESS)
    dry_run = models.BooleanField(default=False)
    error_message = models.TextField(
        blank=True,
        default="",
        help_text="Amostra dos erros por linha (truncada).",
    )
    duration_ms = models.PositiveIntegerField(default=0)

    class Meta:
        app_label = "core"
        verbose_name = "Log de Importação de Terminologia"
        verbose_name_plural = "Logs de Importação de Terminologia"
        ordering = ["-ran_at"]

    def __str__(self):
        return (
            f"TerminologyImportLog[{self.system}] {self.status} @ "
            f"{self.ran_at:%Y-%m-%d %H:%M} ({self.row_count_added}+{self.row_count_updated})"
        )


# ─── Import engine ────────────────────────────────────────────────────────────


@dataclass
class ImportResult:
    """Outcome of a :meth:`CatalogImporter.run` invocation."""

    total: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    status: str = TerminologyImportLog.Status.SUCCESS
    duration_ms: int = 0
    dry_run: bool = False
    log_id: object = None

    @property
    def error_count(self) -> int:
        return len(self.errors)


class CatalogImporter:
    """Idempotent, provenance-logged importer for terminology catalogs.

    Subclass and set :attr:`model`, :attr:`system`, then implement
    :meth:`build_defaults` (map a raw source row to model field values). Callers
    invoke :meth:`run` with an iterable of source rows.

    Guarantees:
      * **Idempotent** — upsert via ``update_or_create`` keyed on the natural key
        ``(system, code, version)`` (override :attr:`key_fields` /
        :meth:`natural_key` if a catalog needs a different key).
      * **Per-row error isolation** — each row runs in its own savepoint; a bad
        row is recorded in ``errors`` and skipped, never aborting the batch.
      * **dry_run** — everything runs, then the whole transaction is rolled back
        so nothing persists (validation preview).
      * **Provenance** — a :class:`TerminologyImportLog` row is written recording
        counts, status, source and provenance label.
    """

    model: type[models.Model] | None = None
    system: str = ""
    key_fields: tuple[str, ...] = ("system", "code", "version")

    def __init__(
        self,
        *,
        version: str = "",
        source: str = TerminologyImportLog.Source.MANAGEMENT_COMMAND,
        provenance: str = "",
        dry_run: bool = False,
    ):
        if self.model is None:
            raise ValueError("CatalogImporter subclass must set `model`.")
        if not self.system:
            raise ValueError("CatalogImporter subclass must set `system`.")
        self.version = version
        self.source = source
        self.provenance = provenance
        self.dry_run = dry_run

    # ── Hooks for subclasses ──────────────────────────────────────────────────

    def get_code(self, row: dict) -> str:
        """Extract the catalog code from a raw row (override if key differs)."""
        code = (row.get("code") or "").strip()
        if not code:
            raise ValueError("row is missing a non-empty 'code'")
        return code

    def natural_key(self, row: dict) -> dict:
        """Natural key kwargs for update_or_create keyed on (system, code, version)."""
        return {"system": self.system, "code": self.get_code(row), "version": self.version}

    def build_defaults(self, row: dict) -> dict:
        """Map a raw source row to model field values (excluding the natural key).

        MUST be implemented by subclasses. Never invent values here — only map
        what the source row provides.
        """
        raise NotImplementedError

    # ── Engine ────────────────────────────────────────────────────────────────

    def run(self, rows) -> ImportResult:
        assert self.model is not None  # subclasses set `model` (validated in __init__)
        rows = list(rows)
        result = ImportResult(total=len(rows), dry_run=self.dry_run)
        start_ms = int(time.time() * 1000)

        with transaction.atomic():
            for index, row in enumerate(rows):
                try:
                    # Per-row savepoint: a DB error on one row does not poison the
                    # surrounding transaction — we roll back just this row.
                    with transaction.atomic():
                        key = self.natural_key(row)
                        defaults = self.build_defaults(row)
                        manager = self.model.objects  # type: ignore[attr-defined]
                        _, created = manager.update_or_create(defaults=defaults, **key)
                    if created:
                        result.created += 1
                    else:
                        result.updated += 1
                except Exception as exc:  # noqa: BLE001 — isolate every row
                    result.skipped += 1
                    result.errors.append(f"row {index + 1}: {exc}")

            if self.dry_run:
                transaction.set_rollback(True)

        result.duration_ms = int(time.time() * 1000) - start_ms
        result.status = self._status_for(result)
        result.log_id = self._write_log(result)
        return result

    def _status_for(self, result: ImportResult) -> str:
        if result.errors and (result.created or result.updated):
            return TerminologyImportLog.Status.PARTIAL
        if result.errors:
            return TerminologyImportLog.Status.ERROR
        return TerminologyImportLog.Status.SUCCESS

    def _write_log(self, result: ImportResult):
        """Persist a provenance log row. Best-effort — never breaks the import."""
        error_sample = "\n".join(result.errors[:20])[:2000]
        try:
            log = TerminologyImportLog.objects.create(
                system=self.system,
                version=self.version,
                source=self.source,
                provenance=self.provenance,
                row_count_total=result.total,
                row_count_added=result.created,
                row_count_updated=result.updated,
                row_count_errors=result.error_count,
                status=result.status,
                dry_run=result.dry_run,
                error_message=error_sample,
                duration_ms=result.duration_ms,
            )
            return log.id
        except Exception:  # noqa: BLE001
            return None
