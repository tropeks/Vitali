"""
CBO + CNES governed catalogs (Sprint M2-S1)
===========================================
Concrete governed master-data catalogs living in the **SHARED (public)** schema,
reusing the E1 terminology backbone (:mod:`apps.core.terminology_base`). Both are
national reference data — global, not per-tenant.

* :class:`CBOCode` (S1-T1) — the CBO (Classificação Brasileira de Ocupações)
  occupation table: each row is an occupation keyed on its CBO code, carrying the
  occupation title (``display``) and its *família ocupacional* (``family``).
  Imported via the ``import_cbo`` management command (provenance = MTE/DATASUS),
  which reuses :class:`~apps.core.terminology_base.CatalogImporter`.

* :class:`CNESEstablishment` (S1-T2) — the CNES (Cadastro Nacional de
  Estabelecimentos de Saúde) establishment table: each row is a health
  establishment keyed on its CNES number, carrying the establishment name
  (``display``), its type (``establishment_type``) and IBGE municipality code
  (``municipality_ibge``). Imported via ``import_cnes`` (provenance =
  CNES/DATASUS).

Tenant operational data (``emr.Professional``, ``organization.Facility``)
references these via cross-schema FKs (DO_NOTHING + a pre_delete protection
signal), mirroring the ``emr`` → ``core.CID10Code`` pattern (E1-T5).

No value is ever fabricated in code: the importers copy only what the source row
provides, leaving inert defaults otherwise.
"""

from __future__ import annotations

from django.db import models

from .terminology_base import TerminologyCatalog

# ─── S1-T1: CBO occupation catalog ───────────────────────────────────────────


class CBOCode(TerminologyCatalog):
    """A CBO occupation (SHARED schema).

    Subclasses the governed :class:`TerminologyCatalog` base — inheriting
    ``code`` / ``display`` / ``system`` / ``version`` / ``active`` and the
    ``normalized_display`` accent/case-folded search column kept in sync on
    ``save()``. Here:

    * ``code``    → the CBO occupation code — natural key.
    * ``display`` → the occupation title (título da ocupação).
    * ``family``  → the CBO *família ocupacional* grouping code.
    """

    # ``system`` is redeclared only to pin the default so directly-constructed
    # instances (tests, admin) need not repeat it; the importer sets it too.
    system = models.CharField(
        "Sistema/terminologia",
        max_length=32,
        db_index=True,
        default="cbo",
        help_text="Identificador do sistema de terminologia (sempre 'cbo' aqui).",
    )

    family = models.CharField(
        "Família ocupacional",
        max_length=16,
        blank=True,
        default="",
        db_index=True,
        help_text="Código da família ocupacional CBO (ex.: '2251' — Médicos clínicos).",
    )

    class Meta:
        app_label = "core"
        verbose_name = "Ocupação CBO"
        verbose_name_plural = "Ocupações CBO"
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(
                fields=["system", "code", "version"],
                name="uniq_cbo_code_natural_key",
            ),
        ]
        indexes = [
            models.Index(fields=["family"], name="cbo_family_idx"),
        ]

    def __str__(self):
        return f"{self.code} — {self.display[:60]}"


# ─── S1-T2: CNES establishment catalog ───────────────────────────────────────


class CNESEstablishment(TerminologyCatalog):
    """A health establishment in the CNES catalog (SHARED schema).

    Subclasses the governed :class:`TerminologyCatalog` base — inheriting
    ``code`` / ``display`` / ``system`` / ``version`` / ``active`` and the
    ``normalized_display`` accent/case-folded search column kept in sync on
    ``save()``. Here:

    * ``code``    → the CNES establishment number — natural key.
    * ``display`` → the establishment name (nome fantasia/empresarial).

    ``active`` (inherited) mirrors the CNES cadastral status. No value is ever
    fabricated in code: the importer copies only what the CNES source row
    provides, leaving inert defaults otherwise.
    """

    # ``system`` is redeclared only to pin the default so directly-constructed
    # instances (tests, admin) need not repeat it; the importer sets it too.
    system = models.CharField(
        "Sistema/terminologia",
        max_length=32,
        db_index=True,
        default="cnes",
        help_text="Identificador do sistema de terminologia (sempre 'cnes' aqui).",
    )

    establishment_type = models.CharField(
        "Tipo de estabelecimento",
        max_length=120,
        blank=True,
        default="",
        db_index=True,
        help_text="Tipo/natureza do estabelecimento (ex.: 'HOSPITAL GERAL', 'CLINICA').",
    )
    municipality_ibge = models.CharField(
        "Município (IBGE)",
        max_length=7,
        blank=True,
        default="",
        db_index=True,
        help_text="Código IBGE (7 dígitos) do município do estabelecimento.",
    )

    class Meta:
        app_label = "core"
        verbose_name = "Estabelecimento CNES"
        verbose_name_plural = "Estabelecimentos CNES"
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(
                fields=["system", "code", "version"],
                name="uniq_cnes_establishment_natural_key",
            ),
        ]
        indexes = [
            models.Index(fields=["municipality_ibge"], name="cnes_municipality_idx"),
        ]

    def __str__(self):
        return f"{self.code} — {self.display[:60]}"
