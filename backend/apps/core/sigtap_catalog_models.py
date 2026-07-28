"""
SIGTAP procedure catalog + valores SUS (Sprint S1)
==================================================
Governed master-data catalog for the **SIGTAP** — Sistema de Gerenciamento da
Tabela de Procedimentos, Medicamentos e OPM do SUS — living in the **SHARED
(public)** schema and reusing the E1 terminology backbone
(:mod:`apps.core.terminology_base`). Like CID-10, TUSS, CBHPM, CBO/CNES,
LOINC/UCUM, the SAE taxonomies, the CNES bed-type catalog and the Manchester
protocol, the SIGTAP is a national reference standard published by DATASUS —
global, not per-tenant.

* :class:`SIGTAPProcedure` (S1) — a SUS procedure keyed on its SIGTAP code,
  carrying the three componentes de valor (Serviço Ambulatorial / Hospitalar /
  Profissional), the competência de vigência, the instrumento de registro
  (BPA-C / BPA-I / APAC / AIH), the complexidade, the fonte de financiamento and
  the minimal compatibility fields (sexo / faixa etária). Imported via the
  ``import_sigtap`` management command (provenance = DATASUS/SIGTAP), which
  reuses :class:`~apps.core.terminology_base.CatalogImporter`.

Modeling decision (S1): the three ``valor_*`` fields are **Decimal**
(max_digits=12, decimal_places=2) — SUS valoração is exact monetary arithmetic,
never float — mirroring :class:`~apps.core.cbhpm_models.CBHPMItem`'s Decimal
handling. :meth:`SIGTAPProcedure.valor_total` sums the three componentes.

Compatibility matrices (CBO × procedimento, CID × procedimento) are DEFERRED to
S2 — S1 keeps only the flat ``sexo_permitido`` / ``idade_min_dias`` /
``idade_max_dias`` compat fields inline. No SUS value is fabricated in code: the
importer copies only what the DATASUS source row provides, leaving inert
defaults otherwise. SIGTAP is public-domain DATASUS data; infra + a
representative SAMPLE ship here.

S2 contract: the BPA/APAC production models will FK :class:`SIGTAPProcedure`
cross-schema (tenant → public, DO_NOTHING + pre_delete PROTECT guard, exactly as
the CBHPM/TUSS links) and consume ``valor_sa`` / ``valor_sp`` plus
``Professional.cns`` / ``Professional.cbo`` / ``Professional.cnes`` /
``Patient.cns``.
"""

from __future__ import annotations

from decimal import Decimal

from django.db import models

from .terminology_base import TerminologyCatalog

# ─── S1: SIGTAP procedure catalog ────────────────────────────────────────────


class InstrumentoRegistro(models.TextChoices):
    """Instrumento de registro SIGTAP (como o procedimento é faturado ao SUS)."""

    BPA_C = "bpa_c", "BPA Consolidado"
    BPA_I = "bpa_i", "BPA Individualizado"
    APAC = "apac", "APAC (Autorização de Procedimento de Alta Complexidade)"
    AIH = "aih", "AIH (Autorização de Internação Hospitalar)"
    OUTROS = "outros", "Outros"


class Complexidade(models.TextChoices):
    """Nível de complexidade do procedimento na atenção do SUS."""

    ATENCAO_BASICA = "atencao_basica", "Atenção Básica"
    MEDIA = "media", "Média Complexidade"
    ALTA = "alta", "Alta Complexidade"
    NAO_SE_APLICA = "nao_se_aplica", "Não se aplica"


class SexoPermitido(models.TextChoices):
    """Sexo permitido para o procedimento (compat mínima S1)."""

    AMBOS = "ambos", "Ambos"
    MASCULINO = "M", "Masculino"
    FEMININO = "F", "Feminino"


class SIGTAPProcedure(TerminologyCatalog):
    """A SUS procedure in the governed SIGTAP catalog (SHARED schema).

    Subclasses the governed :class:`TerminologyCatalog` base — inheriting
    ``code`` / ``display`` / ``system`` / ``version`` / ``active`` and the
    ``normalized_display`` accent/case-folded search column kept in sync on
    ``save()``. Here:

    * ``code``    → the SIGTAP procedure code (10 digits) — natural key.
    * ``display`` → the procedure name.

    No SUS value is fabricated in code.
    """

    # ``system`` is redeclared only to pin the default so directly-constructed
    # instances (tests, admin) need not repeat it; the importer sets it too.
    system = models.CharField(
        "Sistema/terminologia",
        max_length=32,
        db_index=True,
        default="sigtap",
        help_text="Identificador do sistema de terminologia (sempre 'sigtap' aqui).",
    )

    # ── Valores SUS (Decimal exato — nunca float) ─────────────────────────────
    valor_sa = models.DecimalField(
        "Valor Serviço Ambulatorial (SA)",
        max_digits=12,
        decimal_places=2,
        default=Decimal("0"),
        help_text="Componente de valor do Serviço Ambulatorial (R$).",
    )
    valor_sh = models.DecimalField(
        "Valor Serviço Hospitalar (SH)",
        max_digits=12,
        decimal_places=2,
        default=Decimal("0"),
        help_text="Componente de valor do Serviço Hospitalar (R$).",
    )
    valor_sp = models.DecimalField(
        "Valor Serviço Profissional (SP)",
        max_digits=12,
        decimal_places=2,
        default=Decimal("0"),
        help_text="Componente de valor do Serviço Profissional (R$).",
    )

    competencia_vigencia = models.CharField(
        "Competência de vigência",
        max_length=7,
        blank=True,
        default="",
        help_text="Competência de vigência da tabela SIGTAP no formato 'AAAA-MM'.",
    )
    instrumento_registro = models.CharField(
        "Instrumento de registro",
        max_length=10,
        choices=InstrumentoRegistro.choices,
        default=InstrumentoRegistro.OUTROS,
        db_index=True,
        help_text="Instrumento de registro SIGTAP (BPA-C / BPA-I / APAC / AIH / outros).",
    )
    complexidade = models.CharField(
        "Complexidade",
        max_length=16,
        choices=Complexidade.choices,
        default=Complexidade.NAO_SE_APLICA,
        db_index=True,
        help_text="Nível de complexidade do procedimento (atenção básica / média / alta).",
    )
    financiamento = models.CharField(
        "Fonte de financiamento",
        max_length=120,
        blank=True,
        default="",
        help_text="Fonte de financiamento do procedimento (ex.: 'MAC', 'PAB', 'FAEC').",
    )

    # ── Compatibilidade mínima (S1). Matrizes CBO/CID → S2. ───────────────────
    sexo_permitido = models.CharField(
        "Sexo permitido",
        max_length=8,
        choices=SexoPermitido.choices,
        default=SexoPermitido.AMBOS,
        help_text="Sexo permitido para o procedimento (compat mínima S1).",
    )
    idade_min_dias = models.PositiveIntegerField(
        "Idade mínima (dias)",
        null=True,
        blank=True,
        help_text="Idade mínima permitida em dias (nulo = sem restrição).",
    )
    idade_max_dias = models.PositiveIntegerField(
        "Idade máxima (dias)",
        null=True,
        blank=True,
        help_text="Idade máxima permitida em dias (nulo = sem restrição).",
    )

    class Meta:
        app_label = "core"
        verbose_name = "Procedimento SIGTAP"
        verbose_name_plural = "Procedimentos SIGTAP"
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(
                fields=["system", "code", "version"],
                name="uniq_sigtap_procedure_natural_key",
            ),
        ]
        indexes = [
            models.Index(fields=["instrumento_registro"], name="sigtap_instrumento_idx"),
            models.Index(fields=["complexidade"], name="sigtap_complexidade_idx"),
        ]

    def valor_total(self) -> Decimal:
        """Valor total do procedimento: ``valor_sa + valor_sh + valor_sp``.

        Pure Decimal arithmetic — never float — so SUS valores never drift by
        binary-floating rounding. Returns ``Decimal('0')`` while every componente
        is at its inert default (never fabricates a value).
        """
        sa = self.valor_sa if self.valor_sa is not None else Decimal("0")
        sh = self.valor_sh if self.valor_sh is not None else Decimal("0")
        sp = self.valor_sp if self.valor_sp is not None else Decimal("0")
        return sa + sh + sp

    def __str__(self):
        return f"{self.code} — {self.display[:60]}"
