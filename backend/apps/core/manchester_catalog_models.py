"""
Manchester Triage catalog — fluxogramas + discriminadores (Sprint E1)
====================================================================
Governed master-data for the **Sistema de Triagem de Manchester (STM)** that
lives in the **SHARED (public)** schema and reuses the E1 terminology backbone
(:mod:`apps.core.terminology_base`). Like CID-10, TUSS, CBO/CNES, LOINC/UCUM,
the SAE taxonomies and the CNES bed-type catalog, the Manchester protocol is a
national/international reference standard — global, not per-tenant.

Three pieces:

* :class:`AcuityLevel` — the five Manchester priority levels
  (vermelho > laranja > amarelo > verde > azul) plus the module-level
  :data:`ACUITY_TARGET_MINUTES` mapping (priority → tempo-alvo de atendimento em
  minutos) and the :func:`acuity_target_minutes` helper.

* :class:`ManchesterFlowchart` (SHARED governed catalog) — the fluxograma de
  apresentação (ex.: "Dor torácica", "Dispneia", "Mal-estar no adulto").
  Subclasses :class:`~apps.core.terminology_base.TerminologyCatalog` so it gains
  ``code`` / ``display`` / ``system`` / ``version`` / ``active`` + the normalized
  search column, and is registered in :mod:`apps.core.terminology`.

* :class:`ManchesterDiscriminator` (SHARED) — the discriminador que, dentro de um
  fluxograma, dispara um nível de acuidade (ex.: "Dor pré-cordial" → laranja).
  FK ``flowchart`` → :class:`ManchesterFlowchart` (same-schema SHARED FK,
  PROTECT), unique ``(flowchart, code)``. Not a TerminologyCatalog because it is
  flowchart-scoped, not a flat global vocabulary.

E2 (boletim + RiskClassification) will FK ManchesterFlowchart /
ManchesterDiscriminator + carry an ``acuity_level`` from a tenant schema. Because
PostgreSQL does not enforce FK integrity across schemas (tenant → public), a
``pre_delete`` PROTECT guard (mirroring ``protect_bed_type_deletion`` in
:mod:`apps.core.signals`) must be added THEN — exactly as the nursing catalogs
deferred their guard to N2. No guard ships in E1 (no tenant model references the
catalog yet).

Manchester protocol content is licensed (GBCR — Grupo Brasileiro de Classificação
de Risco). Only infrastructure + a small representative SAMPLE ship here, as with
NANDA/TUSS/BedType. No clinical value is fabricated in code: the importer copies
only what the source row provides.
"""

from __future__ import annotations

from django.db import models

from .terminology_base import TerminologyCatalog

# ─── Acuidade (níveis de prioridade Manchester) ──────────────────────────────


class AcuityLevel(models.TextChoices):
    """The five Manchester priority levels (highest → lowest urgency)."""

    VERMELHO = "vermelho", "Vermelho (emergência)"
    LARANJA = "laranja", "Laranja (muito urgente)"
    AMARELO = "amarelo", "Amarelo (urgente)"
    VERDE = "verde", "Verde (pouco urgente)"
    AZUL = "azul", "Azul (não urgente)"


# Manchester priority → tempo-alvo de atendimento (minutos). Vermelho = imediato
# (0); azul = pode aguardar até 240 min. These are the canonical STM targets and
# are what E2's queue/SLA logic will consume.
ACUITY_TARGET_MINUTES: dict[str, int] = {
    AcuityLevel.VERMELHO: 0,
    AcuityLevel.LARANJA: 10,
    AcuityLevel.AMARELO: 60,
    AcuityLevel.VERDE: 120,
    AcuityLevel.AZUL: 240,
}


def acuity_target_minutes(level: str) -> int:
    """Return the Manchester tempo-alvo de atendimento (minutes) for ``level``.

    Raises :class:`KeyError` for an unknown level so callers fail loud rather than
    silently applying a wrong SLA.
    """
    return ACUITY_TARGET_MINUTES[AcuityLevel(level)]


# Manchester priority → urgency rank (1 = most urgent). Vermelho first, azul last —
# the ordering key E3's PS queue sorts classified boletins by (lower rank wins).
ACUITY_RANK: dict[str, int] = {
    AcuityLevel.VERMELHO: 1,
    AcuityLevel.LARANJA: 2,
    AcuityLevel.AMARELO: 3,
    AcuityLevel.VERDE: 4,
    AcuityLevel.AZUL: 5,
}


def acuity_rank(level: str) -> int:
    """Return the urgency rank (1 = most urgent) for ``level``.

    Raises :class:`KeyError` for an unknown level so callers fail loud rather than
    silently mis-ordering the PS queue.
    """
    return ACUITY_RANK[AcuityLevel(level)]


# ─── E1: fluxograma de apresentação (governed catalog) ───────────────────────


class ManchesterFlowchart(TerminologyCatalog):
    """A Manchester fluxograma de apresentação in the governed catalog (SHARED).

    Subclasses the governed :class:`TerminologyCatalog` base — inheriting
    ``code`` / ``display`` / ``system`` / ``version`` / ``active`` and the
    ``normalized_display`` accent/case-folded search column kept in sync on
    ``save()``. Here:

    * ``code``    → the fluxograma code (natural key).
    * ``display`` → the fluxograma label (ex.: 'Dor torácica').

    No value is fabricated in code.
    """

    # ``system`` is redeclared only to pin the default so directly-constructed
    # instances (tests, admin) need not repeat it; the importer sets it too.
    system = models.CharField(
        "Sistema/terminologia",
        max_length=32,
        db_index=True,
        default="manchester_flowchart",
        help_text="Identificador do sistema de terminologia (sempre 'manchester_flowchart' aqui).",
    )

    class Meta:
        app_label = "core"
        verbose_name = "Fluxograma Manchester"
        verbose_name_plural = "Fluxogramas Manchester"
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(
                fields=["system", "code", "version"],
                name="uniq_manchester_flowchart_natural_key",
            ),
        ]

    def __str__(self):
        return f"{self.code} — {self.display[:60]}"


# ─── E1: discriminador (flowchart-scoped) ────────────────────────────────────


class ManchesterDiscriminator(models.Model):
    """A Manchester discriminador — dispara um nível de acuidade num fluxograma.

    NOT a :class:`TerminologyCatalog`: a discriminador is scoped to its
    ``flowchart`` (ou é geral), não é um vocabulário global plano. Cada linha
    liga um discriminador (ex.: 'Dor pré-cordial', 'SatO2 < 95%') ao nível de
    acuidade (:class:`AcuityLevel`) que ele dispara.

    ``flowchart`` é uma FK same-schema SHARED (public → public) com PROTECT.
    ``is_general`` marca discriminadores gerais (aplicáveis a vários fluxogramas)
    vs. específicos. Unique ``(flowchart, code)``.
    """

    flowchart = models.ForeignKey(
        ManchesterFlowchart,
        on_delete=models.PROTECT,
        related_name="discriminators",
        verbose_name="Fluxograma",
        help_text="Fluxograma de apresentação ao qual este discriminador pertence.",
    )
    code = models.CharField(
        "Código",
        max_length=32,
        db_index=True,
        help_text="Código do discriminador (único dentro do fluxograma).",
    )
    name = models.CharField(
        "Discriminador",
        max_length=255,
        help_text="Texto do discriminador (ex.: 'Dor pré-cordial').",
    )
    description = models.TextField(
        "Descrição",
        blank=True,
        default="",
        help_text="Descrição / critério do discriminador (opcional).",
    )
    acuity_level = models.CharField(
        "Nível de acuidade",
        max_length=10,
        choices=AcuityLevel.choices,
        db_index=True,
        help_text="Nível de prioridade Manchester que este discriminador dispara.",
    )
    is_general = models.BooleanField(
        "Geral",
        default=False,
        db_index=True,
        help_text="Discriminador geral (aplicável a vários fluxogramas) vs. específico.",
    )
    active = models.BooleanField("Ativo", default=True, db_index=True)

    class Meta:
        app_label = "core"
        verbose_name = "Discriminador Manchester"
        verbose_name_plural = "Discriminadores Manchester"
        ordering = ["flowchart", "code"]
        constraints = [
            models.UniqueConstraint(
                fields=["flowchart", "code"],
                name="uniq_manchester_discriminator_flowchart_code",
            ),
        ]
        indexes = [
            models.Index(fields=["acuity_level"], name="manchester_disc_acuity_idx"),
        ]

    def __str__(self):
        return f"{self.code} — {self.name[:60]} ({self.acuity_level})"

    @property
    def target_minutes(self) -> int:
        """Tempo-alvo de atendimento (min) do nível de acuidade deste discriminador."""
        return acuity_target_minutes(self.acuity_level)
