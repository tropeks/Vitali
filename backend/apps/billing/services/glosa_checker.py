"""Deterministic glosa-check engine — glosa-safety wedge PR G1.

REVENUE-INTEGRITY logic. This module is PURE and DETERMINISTIC:

  * NO database queries / writes. The orchestrator
    (``apps.billing.services.glosa_safety.GlosaSafetyService``) pre-computes every
    DB-derived input (active-table membership, the currently-active negotiated
    value, the cross-guide duplicate flag) and passes them in as a plain
    ``GuideContext``. This keeps the engine trivially unit-testable and mirrors
    ``apps.pharmacy.services.dose_checker.DoseChecker``.
  * NO LLM, NO network, NO clock. The engine never decides "is this stale by
    date" — the service resolves the *currently active* table and hands over the
    comparison value; the engine only compares.
  * Decimal-only for any numeric compare — NEVER float. A float mid-comparison
    could silently mask (or invent) a price divergence.
  * Every reason string is a deterministic, human-readable pt-BR sentence that
    EMBEDS the offending value, so editing the guide changes the message (the
    override-preservation predicate in the service keys on the message — the dose
    wedge's lesson: a static label lets an acknowledged block be bypassed by
    editing only the amount).

The engine DECIDES (authoritative, like the dose engine); a future LLM only
explains/prioritises. Fail-safe posture lives in the service (engine raises →
advisory), not here.

ANS glosa-code mapping (see ``apps.billing.models.GLOSA_REASON_CODES``):
  * not_in_table → "01" (Procedimento não coberto). Direct, confident map.
  * incomplete (missing beneficiary data) → "05" (Inconsistência nos dados do
    beneficiário). Confident for card/competency; CID-10 absence is also a
    beneficiary/clinical-data inconsistency, mapped here too.
  * duplicate → "99" (Outro). ⚠️ The ANS TISS reason table HAS no single fixed
    code for "procedimento já apresentado" in this codebase's GLOSA_REASON_CODES
    set; left as "99/outro" for the faturista/pharmacist to confirm the exact
    operator-specific code.
  * stale_price → "" (blank). A snapshot-vs-current divergence is an internal
    caution, not (yet) a denial reason emitted to the operator — no ANS code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

# ── ANS glosa-code mapping (single source of truth) ───────────────────────────
# Keys mirror GlosaSafetyAlert.CheckCode values. See module docstring for the
# confidence notes; "99" and "" are the unsure/not-applicable cases.
ANS_CODE_NOT_IN_TABLE = "01"  # Procedimento não coberto
ANS_CODE_INCOMPLETE = "05"  # Inconsistência nos dados do beneficiário
ANS_CODE_DUPLICATE = "99"  # Outro — TODO confirm operator-specific "já apresentado" code
ANS_CODE_STALE_PRICE = ""  # internal caution, no operator-facing ANS reason
ANS_CODE_TABLE_UNRESOLVED = ""  # coverage not verified — internal caution, no ANS reason


@dataclass(frozen=True)
class GuideItemContext:
    """Per-line input the service pre-computes for one TISSGuideItem.

    ``in_active_table`` / ``active_table_value`` are resolved by the service from
    the provider's CURRENTLY ACTIVE PriceTable (not the guide's snapshot table).
    ``duplicate`` is True when the service found another active-status guide with
    the same encounter + TUSS code (cross-guide, under an Encounter lock).
    """

    item_id: int
    tuss_code: str
    unit_value: Decimal
    in_active_table: bool
    active_table_value: Decimal | None
    duplicate: bool


@dataclass(frozen=True)
class GuideContext:
    """Plain, DB-free snapshot of a guide for the engine. The service fills it."""

    guide_type: str
    authorization_number: str
    insured_card_number: str
    competency: str
    cid10_codes: list
    items: list[GuideItemContext] = field(default_factory=list)
    # False when the service could NOT confidently resolve an active price table
    # for the provider. The engine then SKIPS the table-dependent checks
    # (not_in_table / stale_price) and emits ONE table_unresolved advise instead
    # of blocking every line — fail toward advise, never block, when coverage
    # cannot be determined. Defaults True for the pure unit tests / safe callers.
    table_resolved: bool = True


@dataclass(frozen=True)
class GlosaFinding:
    """Immutable result of a single glosa check.

    ``guide_item_id`` is the offending item for per-line checks, or None for the
    guide-level structural-completeness check. ``ans_glosa_code`` is the mapped
    ANS reason code ("" when none applies).
    """

    check_code: str
    severity: str
    message: str
    recommendation: str
    ans_glosa_code: str
    guide_item_id: int | None = None


# Severities per check (REVISED post eng-review — conservative, no crying-wolf):
#   duplicate / not_in_table → block (real, high-confidence denials)
#   stale_price / incomplete → advise (override can be legitimate)
_SEVERITY_BLOCK = "block"
_SEVERITY_ADVISE = "advise"


class GlosaChecker:
    """Pure, deterministic glosa checker. No state, no I/O."""

    @staticmethod
    def check(*, guide_ctx: GuideContext) -> list[GlosaFinding]:
        """Evaluate one guide and return every finding.

        Per-item checks run first (duplicate, not_in_table, stale_price), then the
        single guide-level structural-completeness check. The body never touches
        the DB and never raises on normal input; the service wraps it in
        try/except for defence-in-depth (engine error → advisory, never block).
        """
        findings: list[GlosaFinding] = []

        for item in guide_ctx.items:
            findings.extend(GlosaChecker._check_item(item, table_resolved=guide_ctx.table_resolved))

        # When the active price table could not be resolved, the table-dependent
        # checks are suppressed per-item above; emit ONE guide-level advise so
        # the faturista knows coverage was not verified (never a per-line block).
        if not guide_ctx.table_resolved:
            findings.append(
                GlosaFinding(
                    check_code="table_unresolved",
                    severity=_SEVERITY_ADVISE,
                    message=(
                        "Não foi possível resolver a tabela de preços vigente da operadora; "
                        "cobertura não verificada para esta guia."
                    ),
                    recommendation=(
                        "Confirme manualmente que há uma tabela negociada vigente e que os "
                        "procedimentos estão cobertos antes de faturar."
                    ),
                    ans_glosa_code=ANS_CODE_TABLE_UNRESOLVED,
                    guide_item_id=None,
                )
            )

        incomplete = GlosaChecker._check_incomplete(guide_ctx)
        if incomplete is not None:
            findings.append(incomplete)

        return findings

    # ── per-item checks ─────────────────────────────────────────────────────────

    @staticmethod
    def _check_item(item: GuideItemContext, *, table_resolved: bool = True) -> list[GlosaFinding]:
        findings: list[GlosaFinding] = []

        # 1. DUPLICATE (block) — same encounter + TUSS already on another active
        #    guide. Highest-confidence denial: the operator rejects a procedure
        #    already presented.
        if item.duplicate:
            findings.append(
                GlosaFinding(
                    check_code="duplicate",
                    severity=_SEVERITY_BLOCK,
                    message=(
                        f"Procedimento {item.tuss_code} já apresentado em outra guia ativa "
                        f"do mesmo atendimento (possível duplicidade)."
                    ),
                    recommendation=(
                        "Remova a linha duplicada ou confirme que se trata de execução "
                        "distinta antes de fechar o lote."
                    ),
                    ans_glosa_code=ANS_CODE_DUPLICATE,
                    guide_item_id=item.item_id,
                )
            )

        # Table-dependent checks (not_in_table + stale_price) are MEANINGFUL only
        # when the service confidently resolved an active price table. When it
        # could NOT, suppress both here — the service/engine emits a single
        # guide-level table_unresolved advise instead of blocking every line.
        if not table_resolved:
            return findings

        # 2. NOT_IN_TABLE (block) — TUSS code absent from the provider's currently
        #    active price table → not covered / not negotiated.
        if not item.in_active_table:
            findings.append(
                GlosaFinding(
                    check_code="not_in_table",
                    severity=_SEVERITY_BLOCK,
                    message=(
                        f"Procedimento {item.tuss_code} não consta na tabela de preços "
                        f"vigente da operadora (não coberto/não tabelado)."
                    ),
                    recommendation=(
                        "Confirme a cobertura do procedimento ou inclua o código na tabela "
                        "negociada vigente antes de faturar."
                    ),
                    ans_glosa_code=ANS_CODE_NOT_IN_TABLE,
                    guide_item_id=item.item_id,
                )
            )
        # 3. STALE_PRICE (advise) — item is in the active table AND we know the
        #    currently-negotiated value AND the guide's snapshot value diverges
        #    from it. This is NOT a naive value-vs-contract check (the unit_value
        #    was resolved from the table at guide creation): it flags that the
        #    snapshot drifted from the CURRENTLY active table value — either the
        #    table changed after the guide was created, or the faturista overrode
        #    the value manually (which can be legitimate, e.g. coparticipação).
        #    Only meaningful when the code IS tabulated, so it is mutually
        #    exclusive with not_in_table.
        elif item.active_table_value is not None and Decimal(item.unit_value) != Decimal(
            item.active_table_value
        ):
            findings.append(
                GlosaFinding(
                    check_code="stale_price",
                    severity=_SEVERITY_ADVISE,
                    message=(
                        f"Valor da linha {item.tuss_code} (R$ {Decimal(item.unit_value)}) "
                        f"diverge da tabela vigente (R$ {Decimal(item.active_table_value)}); "
                        f"possível tabela desatualizada ou override manual."
                    ),
                    recommendation=(
                        "Verifique se o valor deve seguir a tabela vigente ou se o override "
                        "manual é intencional (ex.: coparticipação)."
                    ),
                    ans_glosa_code=ANS_CODE_STALE_PRICE,
                    guide_item_id=item.item_id,
                )
            )

        return findings

    # ── guide-level check ─────────────────────────────────────────────────────

    @staticmethod
    def _check_incomplete(guide_ctx: GuideContext) -> GlosaFinding | None:
        """Structural completeness (advise). One combined finding listing every
        missing mandatory field. ``authorization_number`` is ADVISE-only and NEVER
        a block in G1 — many guide types (consulta/sadt) don't require a senha,
        so blocking on a missing auth would cry wolf. All missing fields collapse
        into a single guide-level finding."""
        missing: list[str] = []

        if not (guide_ctx.insured_card_number or "").strip():
            missing.append("número da carteirinha")
        if not (guide_ctx.competency or "").strip():
            missing.append("competência")
        if not guide_ctx.cid10_codes:
            missing.append("CID-10")
        # Auth is advise-only and folded into the same finding (never blocks).
        if not (guide_ctx.authorization_number or "").strip():
            missing.append("senha de autorização")

        if not missing:
            return None

        joined = ", ".join(missing)
        return GlosaFinding(
            check_code="incomplete",
            severity=_SEVERITY_ADVISE,
            message=(
                f"Guia com dados obrigatórios ausentes: {joined}. "
                f"Pode gerar glosa por inconsistência cadastral."
            ),
            recommendation=(
                "Complete os campos ausentes antes do envio "
                "(a senha de autorização nem sempre é exigida — confira a regra do convênio)."
            ),
            ans_glosa_code=ANS_CODE_INCOMPLETE,
            guide_item_id=None,
        )
