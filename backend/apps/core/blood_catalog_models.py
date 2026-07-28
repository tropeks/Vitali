"""
Banco de Sangue/Hemoterapia — governed hemocomponente catalog (Sprint H1)
=========================================================================
Governed master-data catalog for the **hemocomponentes** (blood components) that
lives in the **SHARED (public)** schema and reuses the E1 terminology backbone
(:mod:`apps.core.terminology_base`). Like CID-10, TUSS, CBO/CNES, LOINC/UCUM, the
SAE taxonomies, the CNES bed-type catalog, the Manchester protocol and SIGTAP,
the hemocomponente classification (ISBT-128 / HEMOBRAS) is a reference standard —
global, not per-tenant.

* :class:`BloodComponentCatalog` (H1) — the hemocomponente taxonomy: each row is
  a blood component keyed on its code, carrying the component name (``display``),
  a ``default_validade_dias`` shelf-life hint and a free ``context`` grouping.
  The canonical hemocomponentes are concentrado de hemácias (CH), plasma fresco
  congelado (PFC), concentrado de plaquetas (CP) and crioprecipitado (CRIO).
  Imported via ``import_blood_components`` (provenance = ISBT-128/HEMOBRAS).

Mirrors :mod:`apps.core.adt_catalog_models` exactly: the tenant ``emr.BloodBag``
model references this catalog cross-schema (tenant → public), so the matching
``pre_delete`` PROTECT guard (``protect_blood_component_deletion`` in
:mod:`apps.core.signals`) blocks hard-deleting a component any tenant references.

No terminology value is fabricated in code: the importer copies only what the
source row provides. The classification ships as infra + a representative sample.
"""

from __future__ import annotations

from django.db import models

from .terminology_base import TerminologyCatalog

# ─── H1: hemocomponente catalog ──────────────────────────────────────────────


class BloodComponentCatalog(TerminologyCatalog):
    """A blood component (hemocomponente) in the governed catalog (SHARED schema).

    Subclasses the governed :class:`TerminologyCatalog` base — inheriting
    ``code`` / ``display`` / ``system`` / ``version`` / ``active`` and the
    ``normalized_display`` accent/case-folded search column kept in sync on
    ``save()``. Here:

    * ``code``    → the hemocomponente code (natural key, ex.: 'CH', 'PFC').
    * ``display`` → the component name (ex.: 'Concentrado de hemácias').

    ``default_validade_dias`` is an optional shelf-life hint (dias) and
    ``context`` carries a free grouping (ex.: 'Hemácias', 'Plasma', 'Plaquetas').
    No value is fabricated in code.
    """

    # ``system`` is redeclared only to pin the default so directly-constructed
    # instances (tests, admin) need not repeat it; the importer sets it too.
    system = models.CharField(
        "Sistema/terminologia",
        max_length=32,
        db_index=True,
        default="blood_component",
        help_text="Identificador do sistema de terminologia (sempre 'blood_component' aqui).",
    )

    default_validade_dias = models.PositiveIntegerField(
        "Validade padrão (dias)",
        null=True,
        blank=True,
        help_text="Prazo de validade sugerido do hemocomponente em dias (nulo = sem sugestão).",
    )
    context = models.CharField(
        "Contexto/grupo",
        max_length=120,
        blank=True,
        default="",
        db_index=True,
        help_text="Agrupamento do hemocomponente (ex.: 'Hemácias', 'Plasma', 'Plaquetas').",
    )

    class Meta:
        app_label = "core"
        verbose_name = "Hemocomponente (catálogo)"
        verbose_name_plural = "Hemocomponentes (catálogo)"
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(
                fields=["system", "code", "version"],
                name="uniq_blood_component_natural_key",
            ),
        ]
        indexes = [
            models.Index(fields=["context"], name="blood_component_context_idx"),
        ]

    def __str__(self):
        return f"{self.code} — {self.display[:60]}"
