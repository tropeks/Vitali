"""
Domain terminology catalogs (Sprint E3+)
========================================
Concrete governed master-data catalogs that live in the **SHARED (public)**
schema and reuse the E1 terminology backbone
(:mod:`apps.core.terminology_base`). Reference data — like CID-10 and TUSS — so
it is global, not per-tenant.

* :class:`AnvisaProduct` (E3-T1) — the Brazilian drug catalog: ANVISA product
  registrations keyed on the registration number, carrying DCB (Denominação
  Comum Brasileira), presentation, EAN barcode (indexed, for NF-e line matching),
  therapeutic class, and the Portaria 344/98 controlled list/tarja. Imported via
  the ``import_anvisa`` management command (provenance = ANVISA open data), which
  reuses :class:`~apps.core.terminology_base.CatalogImporter`.

* :class:`AnvisaPresentation` — as apresentações comerciais de um produto, com
  EAN e preço de referência, carregadas da lista CMED via ``import_anvisa_cmed``.
  Tabela própria porque as duas fontes públicas têm granularidades diferentes: o
  dado aberto de medicamentos é por produto e não publica código de barras; a
  CMED é por apresentação e é quem publica o EAN. Como a NF-e traz o código de
  barras da caixa, é por aqui que ``AnvisaProduct.by_ean`` resolve.

Tenant clinical/inventory data (``pharmacy.Drug``) references these via a
cross-schema FK (DO_NOTHING + a pre_delete protection signal), mirroring the
``emr`` → ``core.CID10Code`` pattern (E1-T5).
"""

from __future__ import annotations

from django.db import models

from .terminology_base import TerminologyCatalog

# ─── E3-T1: ANVISA drug catalog ──────────────────────────────────────────────


class AnvisaProduct(TerminologyCatalog):
    """A registered medicine in the ANVISA catalog (SHARED schema).

    Subclasses the governed :class:`TerminologyCatalog` base — inheriting
    ``code`` / ``display`` / ``system`` / ``version`` / ``active`` and the
    ``normalized_display`` accent/case-folded search column kept in sync on
    ``save()``. Here:

    * ``code``    → the ANVISA registration number (*registro*) — natural key.
    * ``display`` → the product/commercial name.

    The remaining columns capture the drug-specific reference data. No value is
    ever fabricated in code: the importer copies only what the ANVISA source row
    provides, leaving inert defaults otherwise.
    """

    # Portaria SVS/MS 344/1998 controlled lists (tarja). Mirrors
    # ``pharmacy.Drug.CONTROLLED_CHOICES`` so a Drug and its catalog product speak
    # the same controlled-class vocabulary. "none" = uncontrolled (no tarja).
    CONTROLLED_CHOICES = [
        ("none", "Não controlado"),
        ("A1", "Lista A1 — Entorpecentes"),
        ("A2", "Lista A2 — Entorpecentes especiais"),
        ("A3", "Lista A3 — Entorpecentes sujeitos a controle especial"),
        ("B1", "Lista B1 — Psicotrópicos"),
        ("B2", "Lista B2 — Psicotrópicos retinóides/anorexígenos"),
        ("C1", "Lista C1 — Outras substâncias sujeitas a controle"),
        ("C2", "Lista C2 — Retinóides de uso sistêmico"),
        ("C3", "Lista C3 — Imunossupressores"),
        ("C4", "Lista C4 — Antirretrovirais"),
        ("C5", "Lista C5 — Anabolizantes"),
    ]

    # ``system`` is redeclared only to pin the default so directly-constructed
    # instances (tests, admin) need not repeat it; the importer sets it too.
    system = models.CharField(
        "Sistema/terminologia",
        max_length=32,
        db_index=True,
        default="anvisa",
        help_text="Identificador do sistema de terminologia (sempre 'anvisa' aqui).",
    )

    dcb = models.CharField(
        "DCB",
        # 500, não 200: no dado aberto real da ANVISA a DCB de fitoterápicos e
        # dinamizados lista a associação inteira de substâncias e chega a 380
        # caracteres (mesma classe de estouro do REFER do CID-O, core 0037).
        # Truncar apagaria parte da composição, que é dado clínico.
        max_length=500,
        blank=True,
        default="",
        db_index=True,
        help_text="Denominação Comum Brasileira do princípio ativo (ex.: 'Amoxicilina').",
    )
    presentation = models.CharField(
        "Apresentação",
        max_length=500,
        blank=True,
        default="",
        help_text="Apresentação comercial (ex.: '500 MG COM REV CT BL AL PLAS INC X 21').",
    )
    ean = models.CharField(
        "EAN",
        max_length=14,
        blank=True,
        default="",
        db_index=True,
        help_text="Código de barras GTIN/EAN — usado para casar linhas de NF-e ao produto.",
    )
    therapeutic_class = models.CharField(
        "Classe terapêutica",
        max_length=200,
        blank=True,
        default="",
        help_text="Classe terapêutica ANVISA (ex.: 'ANTIBACTERIANOS').",
    )
    controlled_class = models.CharField(
        "Lista/tarja (Portaria 344)",
        max_length=5,
        choices=CONTROLLED_CHOICES,
        default="none",
        db_index=True,
        help_text="Lista de controle da Portaria 344/98 ('none' = sem tarja).",
    )

    class Meta:
        app_label = "core"
        verbose_name = "Produto ANVISA"
        verbose_name_plural = "Produtos ANVISA"
        ordering = ["display"]
        constraints = [
            models.UniqueConstraint(
                fields=["system", "code", "version"],
                name="uniq_anvisa_product_natural_key",
            ),
        ]
        indexes = [
            models.Index(fields=["ean"], name="anvisa_ean_idx"),
            models.Index(fields=["dcb"], name="anvisa_dcb_idx"),
        ]

    @property
    def is_controlled(self) -> bool:
        return self.controlled_class != "none"

    @classmethod
    def by_ean(cls, ean: str | None) -> AnvisaProduct | None:
        """Look up an active catalog product by its EAN barcode.

        Returns ``None`` for a blank barcode or no match — never raises. This is
        the primitive the NF-e line matcher uses to auto-suggest a catalog
        product from a scanned/imported barcode.

        The barcode is matched against :class:`AnvisaPresentation` first, since
        an EAN identifies the *pack* (presentation), not the product — that is
        where the CMED price list publishes it. The legacy ``ean`` column on the
        product itself is still consulted as a fallback so rows imported before
        the presentation table keep resolving.
        """
        ean = (ean or "").strip()
        # Só-zeros é ausência de código de barras, não um código: a NF-e traz o
        # GTIN zerado quando o item não tem um, e a CMED usa o mesmo placeholder.
        # Sem esta guarda, toda linha sem GTIN casaria com o produto que por
        # acaso carregasse o placeholder no catálogo.
        if not ean or set(ean) == {"0"}:
            return None
        found = (
            cls.objects.filter(presentations__ean=ean, presentations__active=True, active=True)
            .order_by("code")
            .first()
        )
        if found is not None:
            return found
        return cls.objects.filter(ean=ean, active=True).order_by("code").first()

    def __str__(self):
        return f"{self.code} — {self.display[:60]}"


class AnvisaPresentation(models.Model):
    """Uma apresentação comercial de um :class:`AnvisaProduct` (schema SHARED).

    Existe porque as duas fontes públicas da ANVISA têm granularidades
    diferentes: o dado aberto de medicamentos é por **produto** (registro de 9
    dígitos) e não publica código de barras, enquanto a lista de preços da CMED
    é por **apresentação** (registro de 13 dígitos = os 9 do produto + 4 da
    apresentação) e é quem publica o EAN. Como a NF-e traz o código de barras da
    caixa, o EAN é atributo da apresentação — guardá-lo no produto obrigaria a
    escolher arbitrariamente uma das apresentações e jogar as outras fora.

    Preços são **referência da competência importada**, não verdade corrente: a
    CMED republica a lista periodicamente. Só as colunas sem imposto são
    guardadas; as 25+ variações por alíquota estadual ficam de fora.
    """

    product = models.ForeignKey(
        AnvisaProduct,
        on_delete=models.CASCADE,
        related_name="presentations",
        verbose_name="Produto ANVISA",
    )
    code = models.CharField(
        "Registro da apresentação",
        max_length=20,
        unique=True,
        db_index=True,
        help_text="Registro ANVISA de 13 dígitos (produto + apresentação), como publicado pela CMED.",
    )
    presentation = models.CharField(
        "Apresentação",
        max_length=500,
        blank=True,
        default="",
        help_text="Apresentação comercial (ex.: '500 MG COM REV CT BL AL PLAS INC X 21').",
    )
    ean = models.CharField(
        "EAN",
        max_length=14,
        blank=True,
        default="",
        db_index=True,
        help_text="Código de barras GTIN/EAN da caixa — casa a linha da NF-e com o catálogo.",
    )
    price_pf = models.DecimalField(
        "Preço de fábrica (sem impostos)",
        max_digits=12,
        decimal_places=4,
        null=True,
        blank=True,
        help_text="PF sem impostos da lista CMED da competência importada. Null = não publicado.",
    )
    price_pmc = models.DecimalField(
        "Preço máximo ao consumidor (sem impostos)",
        max_digits=12,
        decimal_places=4,
        null=True,
        blank=True,
        help_text="PMC sem impostos da lista CMED da competência importada. Null = não publicado.",
    )
    version = models.CharField(
        "Versão/competência",
        max_length=20,
        blank=True,
        default="",
        help_text="Competência da lista CMED de origem (ex.: '2026-08').",
    )
    active = models.BooleanField("Ativo", default=True, db_index=True)

    class Meta:
        app_label = "core"
        verbose_name = "Apresentação ANVISA"
        verbose_name_plural = "Apresentações ANVISA"
        ordering = ["code"]
        indexes = [
            models.Index(fields=["ean"], name="anvisa_pres_ean_idx"),
        ]

    def __str__(self):
        return f"{self.code} — {self.presentation[:60]}"
