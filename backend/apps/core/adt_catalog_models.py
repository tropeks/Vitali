"""
ADT/Leitos governed catalog — bed types (Sprint L1)
===================================================
Governed master-data catalog for the CNES *tipo de leito* taxonomy that lives in
the **SHARED (public)** schema and reuses the E1 terminology backbone
(:mod:`apps.core.terminology_base`). Like CID-10, TUSS, CBO/CNES, LOINC/UCUM and
the SAE (NANDA/NIC/NOC) taxonomies, the CNES bed-type classification is a
national reference standard — global, not per-tenant.

* :class:`BedType` (L1) — the CNES bed-type taxonomy: each row is a bed type
  keyed on its CNES code, carrying the type label (``display``) and its CNES
  ``category`` grouping (clínico, cirúrgico, complementar/UTI, obstétrico,
  pediátrico, …). Imported via ``import_bed_types`` (provenance = CNES).

Mirrors :mod:`apps.core.nursing_catalog_models` exactly: the tenant ``emr.Bed``
model references this catalog cross-schema (tenant → public), so the matching
``pre_delete`` PROTECT guard (``protect_bed_type_deletion`` in
:mod:`apps.core.signals`) blocks hard-deleting a bed type any tenant references.

No terminology value is fabricated in code: the importer copies only what the
source row provides. The CNES classification ships as infra + a representative
sample.
"""

from __future__ import annotations

from django.db import models

from .terminology_base import TerminologyCatalog

# ─── L1: CNES bed-type catalog ───────────────────────────────────────────────


class BedType(TerminologyCatalog):
    """A CNES bed type in the governed catalog (SHARED schema).

    Subclasses the governed :class:`TerminologyCatalog` base — inheriting
    ``code`` / ``display`` / ``system`` / ``version`` / ``active`` and the
    ``normalized_display`` accent/case-folded search column kept in sync on
    ``save()``. Here:

    * ``code``    → the CNES bed-type code (natural key).
    * ``display`` → the bed-type label (ex.: 'UTI adulto tipo II').

    ``category`` carries the CNES bed grouping (ex.: 'Complementar', 'Clínico').
    No value is fabricated in code.
    """

    # ``system`` is redeclared only to pin the default so directly-constructed
    # instances (tests, admin) need not repeat it; the importer sets it too.
    system = models.CharField(
        "Sistema/terminologia",
        max_length=32,
        db_index=True,
        default="bed_type",
        help_text="Identificador do sistema de terminologia (sempre 'bed_type' aqui).",
    )

    category = models.CharField(
        "Categoria (CNES)",
        max_length=120,
        blank=True,
        default="",
        db_index=True,
        help_text="Grupo do leito na classificação CNES (ex.: 'Complementar', 'Clínico').",
    )

    class Meta:
        app_label = "core"
        verbose_name = "Tipo de Leito (CNES)"
        verbose_name_plural = "Tipos de Leito (CNES)"
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(
                fields=["system", "code", "version"],
                name="uniq_bed_type_natural_key",
            ),
        ]
        indexes = [
            models.Index(fields=["category"], name="bed_type_category_idx"),
        ]

    def __str__(self):
        return f"{self.code} — {self.display[:60]}"
