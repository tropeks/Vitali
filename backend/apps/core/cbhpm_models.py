"""
CBHPM procedure catalog + valoração por porte (Sprint M1-S1)
============================================================
Concrete governed master-data catalog living in the **SHARED (public)** schema,
reusing the E1 terminology backbone (:mod:`apps.core.terminology_base`).

* :class:`CBHPMItem` (S1-T1) — the CBHPM/AMB procedure table (Classificação
  Brasileira Hierarquizada de Procedimentos Médicos): each row is a procedure
  keyed on its CBHPM/AMB code, carrying the *porte* (numeric porte value, the CH
  multiplier), the *valor CH/UCO* (monetary value of the coeficiente de
  honorários / Unidade de Custo Operacional), the anesthetic porte, film count
  and auxiliary count. Imported via the ``import_cbhpm`` management command
  (provenance = CBHPM/AMB), which reuses
  :class:`~apps.core.terminology_base.CatalogImporter`.

  Modeling decision (S1-T1): ``porte`` is stored as a **Decimal** — the numeric
  porte value (quantity of CH the porte is worth) — because valoração
  (:meth:`CBHPMItem.valor`) is ``porte × valor_ch`` and must be exact Decimal
  arithmetic, never float. The alphanumeric porte *label* (e.g. "2C") is not the
  multiplier; the multiplier is this numeric value.

* (S1-T2) ``CBHPMItem.tuss`` — a nullable cross-catalog FK to
  :class:`~apps.core.models.TUSSCode`: a CBHPM porte row maps to a TUSS
  procedure. ``TUSSCode.table_number`` (added in S1-T2) tags TUSS rows by their
  source table.

No clinical/valuation value is ever fabricated in code: the importer copies only
what the CBHPM/AMB source row provides, leaving inert defaults otherwise.
"""

from __future__ import annotations

from decimal import Decimal

from django.db import models

from .terminology_base import TerminologyCatalog

# ─── S1-T1: CBHPM procedure catalog ──────────────────────────────────────────


class CBHPMItem(TerminologyCatalog):
    """A procedure in the CBHPM/AMB catalog (SHARED schema).

    Subclasses the governed :class:`TerminologyCatalog` base — inheriting
    ``code`` / ``display`` / ``system`` / ``version`` / ``active`` and the
    ``normalized_display`` accent/case-folded search column kept in sync on
    ``save()``. Here:

    * ``code``    → the CBHPM/AMB procedure code — natural key.
    * ``display`` → the procedure description.
    """

    # ``system`` is redeclared only to pin the default so directly-constructed
    # instances (tests, admin) need not repeat it; the importer sets it too.
    system = models.CharField(
        "Sistema/terminologia",
        max_length=32,
        db_index=True,
        default="cbhpm",
        help_text="Identificador do sistema de terminologia (sempre 'cbhpm' aqui).",
    )

    # ── O porte é CÓDIGO, não número (ordem 013) ─────────────────────────────
    #
    # Este campo nasceu DecimalField, rotulado "quantidade de CH". Na CBHPM
    # publicada pela AMB o porte é CLASSE HIERÁRQUICA — "3B", "13C" — e, em toda
    # a Medicina Laboratorial, FRAÇÃO de uma classe: "0,01 de 1A". Medido na
    # edição 2022 rev. ago/2023: das 4.883 linhas do livro, ZERO têm porte
    # numérico e 1.046 são fracionárias.
    #
    # Guardar "1A" como 1 perderia a fração e inflaria o porte de 25 a 100 vezes
    # no capítulo mais volumoso — INTENT §Limites, nenhum número contratual
    # inventado. A única leitura fiel do livro é a string publicada.
    porte = models.CharField(
        "Porte (classe CBHPM)",
        max_length=32,
        blank=True,
        default="",
        db_index=True,
        help_text=(
            "Classe de porte como publicada na CBHPM (ex.: '3B', '13C', "
            "'0,01 de 1A'). Vazio = não informado. NÃO é valor monetário."
        ),
    )
    # ── E a valoração vive à parte, porque é contrato, não catálogo ──────────
    #
    # A CBHPM classifica; quantos CH vale cada classe, e quanto vale o CH em
    # reais, é negociado entre clínica e operadora — o §1.2 do próprio livro diz
    # que os portes "não expressam valores monetários". Então este campo só se
    # popula por tabela de valoração CONTRATADA, nunca pelo import do livro, e
    # fica no default inerte até lá.
    porte_ch = models.DecimalField(
        "Porte em CH (quantidade)",
        max_digits=10,
        decimal_places=4,
        default=Decimal("0"),
        help_text=(
            "Quantidade de CH correspondente ao porte, vinda da tabela de "
            "valoração contratada. Zero = sem valoração — e aí valor() é zero."
        ),
    )
    valor_ch = models.DecimalField(
        "Valor CH/UCO",
        max_digits=12,
        decimal_places=6,
        default=Decimal("0"),
        help_text="Valor monetário do CH (coeficiente de honorários) / UCO.",
    )
    porte_anestesico = models.CharField(
        "Porte anestésico",
        max_length=8,
        blank=True,
        default="",
        help_text="Porte anestésico do procedimento (código, ex.: '3'). Vazio = não informado.",
    )
    numero_filme = models.DecimalField(
        "Número de filme",
        max_digits=10,
        decimal_places=4,
        default=Decimal("0"),
        help_text="Quantidade de filme radiológico associada ao procedimento.",
    )
    numero_auxiliares = models.PositiveSmallIntegerField(
        "Número de auxiliares",
        default=0,
        help_text="Número de auxiliares previstos para o procedimento.",
    )
    vigencia = models.CharField(
        "Vigência",
        max_length=32,
        blank=True,
        default="",
        help_text="Rótulo da competência/vigência da tabela (ex.: '2024').",
    )

    # ── S1-T2: link to the TUSS procedure table ──────────────────────────────
    # A CBHPM porte row maps to a TUSS procedure. Nullable: not every CBHPM row
    # has (yet) a TUSS correspondence. Same schema (both in SHARED/public), so a
    # real DB-enforced FK is fine here (unlike the cross-schema tenant links).
    tuss = models.ForeignKey(
        "core.TUSSCode",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cbhpm_items",
        help_text="Procedimento TUSS correspondente a este porte CBHPM (opcional).",
    )

    class Meta:
        app_label = "core"
        verbose_name = "Item CBHPM"
        verbose_name_plural = "Itens CBHPM"
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(
                fields=["system", "code", "version"],
                name="uniq_cbhpm_item_natural_key",
            ),
        ]

    def valor(self) -> Decimal:
        """Valoração do procedimento: ``porte_ch × valor_ch`` (Decimal exato).

        Pure Decimal arithmetic — never float — so honorários never drift by
        binary-floating rounding. Returns ``Decimal('0')`` while either factor
        is at its inert default (never fabricates a value).

        Ordem 013: o multiplicador saiu de ``porte`` para ``porte_ch``. ``porte``
        virou a classe publicada ("3B", "0,01 de 1A"), que não é número e não
        multiplica nada. Importar o livro passa a NÃO produzir preço — e é assim
        que tem de ser: preço é contrato.
        """
        porte_ch = self.porte_ch if self.porte_ch is not None else Decimal("0")
        valor_ch = self.valor_ch if self.valor_ch is not None else Decimal("0")
        return porte_ch * valor_ch

    def __str__(self):
        return f"{self.code} — {self.display[:60]}"
