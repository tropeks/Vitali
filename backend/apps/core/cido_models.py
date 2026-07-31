"""
CID-O morfologia — catálogo governado de oncologia (greenfield)
===============================================================
Governed master-data catalog for the CID-O **morphology** axis (histologic type +
behaviour), living in the SHARED (public) schema and reusing the E1 terminology
backbone (:mod:`apps.core.terminology_base`). Mirrors :class:`BedType` /
:class:`SIGTAPProcedure`: a national/international reference standard, global not
per-tenant.

The CID-O has two axes: **topography** (where the tumour is — the ``C`` codes,
already governed by :class:`core.CID10Code`, chapter II) and **morphology** (the
histologic type + behaviour — the ``M`` codes, e.g. ``8500/3`` invasive ductal
carcinoma). Only morphology is modelled here; topography reuses CID-10.

* ``code``     → CID-O morphology code ``NNNN/B`` (e.g. ``8500/3``), the digit
  after ``/`` being the behaviour (0 benign, 1 uncertain, 2 in situ, 3 malignant
  primary, 6 metastatic, 9 malignant uncertain).
* ``display``  → the morphology label.
* ``behaviour``→ the behaviour digit (denormalized from the code for filtering,
  e.g. "malignos = behaviour 3").
* ``cid10_ref``→ the correlated CID-10 topography code from the DATASUS REFER
  column (e.g. ``C81.3``), when the source provides one.

Imported via ``import_cido`` (provenance = DATASUS). No value is fabricated in
code — the importer copies only what the source row provides. ``emr.PathologyReport``
will reference this catalog cross-schema (tenant → public) with a matching
``pre_delete`` PROTECT guard.
"""

from __future__ import annotations

from django.db import models

from .terminology_base import TerminologyCatalog


class CIDOMorphology(TerminologyCatalog):
    """A CID-O morphology code in the governed catalog (SHARED schema)."""

    system = models.CharField(
        "Sistema/terminologia",
        max_length=32,
        db_index=True,
        default="cid_o",
        help_text="Identificador do sistema de terminologia (sempre 'cid_o' aqui).",
    )

    behaviour = models.CharField(
        "Comportamento",
        max_length=1,
        blank=True,
        default="",
        db_index=True,
        help_text="Dígito de comportamento do código CID-O (0 benigno … 3 maligno primário …).",
    )
    cid10_ref = models.CharField(
        "CID-10 correlato",
        max_length=10,
        blank=True,
        default="",
        help_text="Código CID-10 de topografia correlato (coluna REFER do DATASUS), quando houver.",
    )

    class Meta:
        app_label = "core"
        verbose_name = "Morfologia CID-O"
        verbose_name_plural = "Morfologias CID-O"
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(
                fields=["system", "code", "version"],
                name="uniq_cido_morphology_natural_key",
            ),
        ]
        indexes = [
            models.Index(fields=["behaviour"], name="cido_behaviour_idx"),
        ]

    def __str__(self):
        return f"{self.code} — {self.display[:60]}"
