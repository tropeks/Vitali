"""
Material/OPME — governed Simpro price catalog (Sprint B4a)
=========================================================
Governed master-data catalog for **material/OPME/medicamento** price references
that lives in the **SHARED (public)** schema and reuses the E1 terminology
backbone (:mod:`apps.core.terminology_base`). Like CID-10, TUSS, CBO/CNES,
LOINC/UCUM, the SAE taxonomies, the CNES bed-type catalog, the hemocomponente
catalog, the Manchester protocol and SIGTAP, the **Simpro** table is a national
reference standard — global, not per-tenant.

Why Simpro (and not TUSS/PriceTable)
------------------------------------
No Brasil, material/OPME **não** precifica por TUSS/PriceTable como os
procedimentos. A referência de mercado é a tabela **Simpro** (preço de referência
de material/OPME, edição bimestral); o convênio negocia um valor em cima dela.
Este catálogo modela essa fonte de preço, espelhando a infra de
``PriceTable``/``PriceTableItem`` que já existe para procedimentos — mas com o
preço de referência morando aqui (SHARED), e o valor negociado por convênio no
tenant (:class:`~apps.billing.material_models.MaterialPriceItem`).

* :class:`SimproMaterial` (B4a) — cada linha é um item Simpro keyed on its Simpro
  ``code`` (natural key), carregando a descrição (``display``), o ``kind``
  (material / opme / medicamento), o TUSS TISS correspondente (tabela 20 material
  / 19 medicamento), o ``reference_price`` da edição e a ``edition``/competência.

Mirrors :mod:`apps.core.blood_catalog_models` exactly: the tenant
``billing.MaterialPriceItem`` model references this catalog cross-schema
(tenant → public), so the matching ``pre_delete`` PROTECT guard
(``protect_simpro_material_deletion`` in :mod:`apps.core.signals`) blocks
hard-deleting a material any tenant references.

No terminology/price value is fabricated in code: the importer copies only what
the source row provides. Simpro é conteúdo licenciado — aqui vai só a estrutura +
uma amostra representativa (nos testes).
"""

from __future__ import annotations

from django.db import models

from .terminology_base import TerminologyCatalog

# ─── B4a: Simpro material/OPME price catalog ─────────────────────────────────


class SimproMaterial(TerminologyCatalog):
    """A Simpro material/OPME/medicamento in the governed catalog (SHARED schema).

    Subclasses the governed :class:`TerminologyCatalog` base — inheriting
    ``code`` / ``display`` / ``system`` / ``version`` / ``active`` and the
    ``normalized_display`` accent/case-folded search column kept in sync on
    ``save()``. Here:

    * ``code``    → o código Simpro (natural key).
    * ``display`` → a descrição do material (ex.: 'Parafuso de titânio 4.5mm').

    ``reference_price`` é o preço de referência da edição Simpro; ``edition`` é a
    competência dessa edição (ex.: '2026-07'). ``tuss_code`` liga ao código TUSS
    TISS correspondente (tabela 20 material / 19 medicamento) — FK public↔public
    normal (ambos SHARED). No value is fabricated in code.
    """

    class Kind(models.TextChoices):
        MATERIAL = "material", "Material"
        OPME = "opme", "OPME"
        MEDICAMENTO = "medicamento", "Medicamento"

    # ``system`` is redeclared only to pin the default so directly-constructed
    # instances (tests, admin) need not repeat it; the importer sets it too.
    system = models.CharField(
        "Sistema/terminologia",
        max_length=32,
        db_index=True,
        default="simpro",
        help_text="Identificador do sistema de terminologia (sempre 'simpro' aqui).",
    )

    kind = models.CharField(
        "Tipo",
        max_length=12,
        choices=Kind.choices,
        default=Kind.MATERIAL,
        db_index=True,
        help_text="Classe do item Simpro: material, OPME ou medicamento.",
    )
    # FK public↔public (ambos SHARED) — PROTECT normal, sem cross-schema. É o
    # código TUSS TISS (tabela 20 material / 19 medicamento) correspondente.
    tuss_code = models.ForeignKey(
        "core.TUSSCode",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="simpro_materials",
        verbose_name="TUSS correspondente",
        help_text="Código TUSS TISS do material/medicamento (tabela 20/19). Vazio = sem correspondência.",
    )
    reference_price = models.DecimalField(
        "Preço de referência (R$)",
        max_digits=12,
        decimal_places=4,
        default=0,
        help_text="Preço de referência da edição Simpro para este item.",
    )
    edition = models.CharField(
        "Edição/competência",
        max_length=16,
        blank=True,
        default="",
        db_index=True,
        help_text="Edição/competência da tabela Simpro (ex.: '2026-07').",
    )
    unit = models.CharField(
        "Unidade",
        max_length=16,
        blank=True,
        default="",
        help_text="Unidade de comercialização (ex.: 'UN', 'FR').",
    )

    class Meta:
        app_label = "core"
        verbose_name = "Material Simpro (catálogo)"
        verbose_name_plural = "Materiais Simpro (catálogo)"
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(
                fields=["system", "code", "version"],
                name="uniq_simpro_material_natural_key",
            ),
        ]
        indexes = [
            models.Index(fields=["kind"], name="simpro_material_kind_idx"),
        ]

    def __str__(self):
        return f"{self.code} — {self.display[:60]}"
