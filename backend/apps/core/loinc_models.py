"""
LIS terminology catalogs (Sprint M2-S3 · T1)
============================================
Governed master-data catalogs for the laboratory information system (LIS) that
live in the **SHARED (public)** schema and reuse the E1 terminology backbone
(:mod:`apps.core.terminology_base`). Reference data — like CID-10, TUSS and
ANVISA — so it is global, not per-tenant.

* :class:`LoincCode` (M2-S3-T1) — the LOINC observation catalog: a subset of the
  Logical Observation Identifiers Names and Codes used to give every laboratory
  test a universal, interoperable identity. ``code`` is the LOINC number and
  ``display`` its Long Common Name; the LOINC part axes (component / property /
  system) are carried as optional columns. Imported via ``import_loinc``
  (provenance = LOINC / Regenstrief), which reuses
  :class:`~apps.core.terminology_base.CatalogImporter`.

* :class:`UcumUnit` (M2-S3-T1) — the UCUM catalog: Unified Code for Units of
  Measure symbols (case-sensitive) with a human-readable display. Imported via
  ``import_ucum``.

Tenant clinical data (``emr.LabTest.loinc``) references :class:`LoincCode` via a
cross-schema FK (DO_NOTHING + a pre_delete protection signal in
``apps.core.signals``), mirroring the ``emr`` → ``core.CID10Code`` (E1-T5) and
``pharmacy.Drug`` → ``core.AnvisaProduct`` (E3-T2) patterns.
"""

from __future__ import annotations

from django.db import models

from .terminology_base import TerminologyCatalog

# ─── M2-S3-T1: LOINC observation catalog ─────────────────────────────────────


class LoincCode(TerminologyCatalog):
    """A LOINC observation code in the governed catalog (SHARED schema).

    Subclasses the governed :class:`TerminologyCatalog` base — inheriting
    ``code`` / ``display`` / ``system`` / ``version`` / ``active`` and the
    ``normalized_display`` accent/case-folded search column kept in sync on
    ``save()``. Here:

    * ``code``    → the LOINC number (e.g. ``718-7``) — natural key.
    * ``display`` → the Long Common Name (e.g. ``Hemoglobin [Mass/volume] in
      Blood``).

    The LOINC six-part axes we carry are optional: ``component`` (what is
    measured), ``property`` (the kind of quantity), and ``loinc_system`` (the
    specimen/system). They are named to avoid clobbering the inherited ``system``
    column (which stores the *terminology* identifier, always ``"loinc"`` here).
    No value is ever fabricated in code: the importer copies only what the LOINC
    source row provides, leaving inert defaults otherwise.
    """

    # ``system`` is redeclared only to pin the default so directly-constructed
    # instances (tests, admin) need not repeat it; the importer sets it too.
    system = models.CharField(
        "Sistema/terminologia",
        max_length=32,
        db_index=True,
        default="loinc",
        help_text="Identificador do sistema de terminologia (sempre 'loinc' aqui).",
    )

    component = models.CharField(
        "Componente (LOINC)",
        max_length=255,
        blank=True,
        default="",
        db_index=True,
        help_text="Eixo COMPONENT do LOINC — o que é medido (ex.: 'Hemoglobin').",
    )
    property = models.CharField(
        "Propriedade (LOINC)",
        max_length=64,
        blank=True,
        default="",
        help_text="Eixo PROPERTY do LOINC — tipo de grandeza (ex.: 'MCnc', 'SCnc').",
    )
    loinc_system = models.CharField(
        "Sistema/espécime (LOINC)",
        max_length=128,
        blank=True,
        default="",
        db_index=True,
        help_text="Eixo SYSTEM do LOINC — espécime/sistema (ex.: 'Bld', 'Ser/Plas').",
    )

    class Meta:
        app_label = "core"
        verbose_name = "Código LOINC"
        verbose_name_plural = "Códigos LOINC"
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(
                fields=["system", "code", "version"],
                name="uniq_loinc_code_natural_key",
            ),
        ]
        indexes = [
            models.Index(fields=["component"], name="loinc_component_idx"),
        ]

    def __str__(self):
        return f"{self.code} — {self.display[:60]}"


# ─── M2-S3-T1: UCUM unit catalog ─────────────────────────────────────────────


class UcumUnit(TerminologyCatalog):
    """A UCUM unit-of-measure symbol in the governed catalog (SHARED schema).

    ``code`` is the **case-sensitive** UCUM symbol (e.g. ``mg/dL``, ``10*9/L``)
    and ``display`` its human-readable name. UCUM case-sensitivity is preserved
    by the case-sensitive ``code`` column (the ``normalized_display`` search
    helper folds case only for the *display*, never the code).
    """

    # ``system`` redeclared only to pin the default (see LoincCode).
    system = models.CharField(
        "Sistema/terminologia",
        max_length=32,
        db_index=True,
        default="ucum",
        help_text="Identificador do sistema de terminologia (sempre 'ucum' aqui).",
    )

    class Meta:
        app_label = "core"
        verbose_name = "Unidade UCUM"
        verbose_name_plural = "Unidades UCUM"
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(
                fields=["system", "code", "version"],
                name="uniq_ucum_unit_natural_key",
            ),
        ]

    def __str__(self):
        return f"{self.code} — {self.display[:60]}"
