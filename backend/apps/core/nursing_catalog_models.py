"""
Nursing terminology catalogs — NANDA-I / NIC / NOC (Sprint N1-T1)
================================================================
Governed master-data catalogs for the SAE (Sistematização da Assistência de
Enfermagem) taxonomies that live in the **SHARED (public)** schema and reuse the
E1 terminology backbone (:mod:`apps.core.terminology_base`). Like CID-10, TUSS,
CBO/CNES and LOINC/UCUM, these are national/international reference standards —
global, not per-tenant.

* :class:`NandaDiagnosis` (N1-T1) — the NANDA-I nursing diagnosis taxonomy: each
  row is a diagnosis keyed on its NANDA code, carrying the diagnosis label
  (``display``), its taxonomy ``domain`` and ``nanda_class`` grouping, the
  ``definition``, and the optional ``defining_characteristics`` /
  ``related_factors`` text. Imported via ``import_nanda`` (provenance = NANDA-I).

* :class:`NicIntervention` (N1-T1) — the NIC (Nursing Interventions
  Classification) taxonomy: each row is an intervention keyed on its NIC code,
  carrying the intervention label (``display``), the ``definition`` and optional
  ``activities`` text. Imported via ``import_nic`` (provenance = NIC).

* :class:`NocOutcome` (N1-T1) — the NOC (Nursing Outcomes Classification)
  taxonomy: each row is an outcome keyed on its NOC code, carrying the outcome
  label (``display``), the ``definition`` and optional ``indicators`` text.
  Imported via ``import_noc`` (provenance = NOC).

These are standalone catalogs for now: no tenant model references them yet, so
(unlike CBO/CNES/LOINC) they have NO cross-schema ``pre_delete`` PROTECT signal
today — that scaffolding is added in N2 when ``emr`` care-plan capture wires the
FKs (see the note in ``apps.core.signals``). Mirroring the CBOCode shape exactly
means adding the guard then is a one-block change.

No clinical value is ever fabricated in code: the importers copy only what the
source row provides, leaving inert defaults otherwise. The taxonomies are
licensed, so only infrastructure + a small representative sample ship here (as
with CBO/CNES/LOINC).
"""

from __future__ import annotations

from django.db import models

from .terminology_base import TerminologyCatalog

# ─── N1-T1: NANDA-I nursing diagnosis catalog ────────────────────────────────


class NandaDiagnosis(TerminologyCatalog):
    """A NANDA-I nursing diagnosis in the governed catalog (SHARED schema).

    Subclasses the governed :class:`TerminologyCatalog` base — inheriting
    ``code`` / ``display`` / ``system`` / ``version`` / ``active`` and the
    ``normalized_display`` accent/case-folded search column kept in sync on
    ``save()``. Here:

    * ``code``    → the NANDA-I diagnosis code (e.g. ``00132``) — natural key.
    * ``display`` → the diagnosis label (rótulo diagnóstico).

    ``domain`` and ``nanda_class`` carry the NANDA-I Taxonomy II placement.
    ``nanda_class`` is named to avoid the Python reserved word ``class``. The
    ``definition`` plus optional ``defining_characteristics`` / ``related_factors``
    round out the standard NANDA-I structure. No value is fabricated in code.
    """

    # ``system`` is redeclared only to pin the default so directly-constructed
    # instances (tests, admin) need not repeat it; the importer sets it too.
    system = models.CharField(
        "Sistema/terminologia",
        max_length=32,
        db_index=True,
        default="nanda",
        help_text="Identificador do sistema de terminologia (sempre 'nanda' aqui).",
    )

    domain = models.CharField(
        "Domínio (NANDA-I)",
        max_length=120,
        blank=True,
        default="",
        db_index=True,
        help_text="Domínio da Taxonomia II NANDA-I (ex.: '12 Conforto').",
    )
    nanda_class = models.CharField(
        "Classe (NANDA-I)",
        max_length=120,
        blank=True,
        default="",
        db_index=True,
        help_text="Classe da Taxonomia II NANDA-I (ex.: '1 Conforto físico').",
    )
    definition = models.TextField(
        "Definição",
        blank=True,
        default="",
        help_text="Definição do diagnóstico de enfermagem.",
    )
    defining_characteristics = models.TextField(
        "Características definidoras",
        blank=True,
        default="",
        help_text="Características definidoras (opcional; texto/lista da fonte).",
    )
    related_factors = models.TextField(
        "Fatores relacionados",
        blank=True,
        default="",
        help_text="Fatores relacionados / de risco (opcional; texto/lista da fonte).",
    )

    class Meta:
        app_label = "core"
        verbose_name = "Diagnóstico NANDA-I"
        verbose_name_plural = "Diagnósticos NANDA-I"
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(
                fields=["system", "code", "version"],
                name="uniq_nanda_diagnosis_natural_key",
            ),
        ]
        indexes = [
            models.Index(fields=["domain"], name="nanda_domain_idx"),
        ]

    def __str__(self):
        return f"{self.code} — {self.display[:60]}"


# ─── N1-T1: NIC intervention catalog ─────────────────────────────────────────


class NicIntervention(TerminologyCatalog):
    """A NIC (Nursing Interventions Classification) intervention (SHARED schema).

    Subclasses the governed :class:`TerminologyCatalog` base. Here:

    * ``code``    → the NIC intervention code (e.g. ``1400``) — natural key.
    * ``display`` → the intervention label (título da intervenção).

    ``definition`` and the optional ``activities`` text round out the standard
    NIC structure. No value is fabricated in code.
    """

    # ``system`` redeclared only to pin the default (see NandaDiagnosis).
    system = models.CharField(
        "Sistema/terminologia",
        max_length=32,
        db_index=True,
        default="nic",
        help_text="Identificador do sistema de terminologia (sempre 'nic' aqui).",
    )

    definition = models.TextField(
        "Definição",
        blank=True,
        default="",
        help_text="Definição da intervenção de enfermagem.",
    )
    activities = models.TextField(
        "Atividades",
        blank=True,
        default="",
        help_text="Atividades da intervenção (opcional; texto/lista da fonte).",
    )

    class Meta:
        app_label = "core"
        verbose_name = "Intervenção NIC"
        verbose_name_plural = "Intervenções NIC"
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(
                fields=["system", "code", "version"],
                name="uniq_nic_intervention_natural_key",
            ),
        ]

    def __str__(self):
        return f"{self.code} — {self.display[:60]}"


# ─── N1-T1: NOC outcome catalog ──────────────────────────────────────────────


class NocOutcome(TerminologyCatalog):
    """A NOC (Nursing Outcomes Classification) outcome (SHARED schema).

    Subclasses the governed :class:`TerminologyCatalog` base. Here:

    * ``code``    → the NOC outcome code (e.g. ``2102``) — natural key.
    * ``display`` → the outcome label (título do resultado).

    ``definition`` and the optional ``indicators`` text round out the standard
    NOC structure. No value is fabricated in code.
    """

    # ``system`` redeclared only to pin the default (see NandaDiagnosis).
    system = models.CharField(
        "Sistema/terminologia",
        max_length=32,
        db_index=True,
        default="noc",
        help_text="Identificador do sistema de terminologia (sempre 'noc' aqui).",
    )

    definition = models.TextField(
        "Definição",
        blank=True,
        default="",
        help_text="Definição do resultado de enfermagem.",
    )
    indicators = models.TextField(
        "Indicadores",
        blank=True,
        default="",
        help_text="Indicadores do resultado (opcional; texto/lista da fonte).",
    )

    class Meta:
        app_label = "core"
        verbose_name = "Resultado NOC"
        verbose_name_plural = "Resultados NOC"
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(
                fields=["system", "code", "version"],
                name="uniq_noc_outcome_natural_key",
            ),
        ]

    def __str__(self):
        return f"{self.code} — {self.display[:60]}"
