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
  * duplicate → "1702" (Cobrança de procedimento em duplicidade). The cross-guide
    duplicate check fires when the same TUSS procedure was already PRESENTED to the
    payer on another active guide of the same encounter. "1702" is the ANS TISS 4.01
    Tabela 38 (Terminologia de mensagens) standard code for procedure-level duplicate
    billing — the closest authoritative match for "procedimento já apresentado". The
    guide-level variant is "1308" (Guia já apresentada); "1807" (Procedimentos médicos
    duplicados) is the specialty-specific variant. We map to the item-level "1702"
    because this alert is per-procedure (guide_item is set), not per-guide.
  * stale_price → "" (blank). A snapshot-vs-current divergence is an internal
    caution, not (yet) a denial reason emitted to the operator — no ANS code.
  * quantity_exceeds → "" (blank). The line quantity exceeds the contract's
    per-procedure ceiling (PriceTableItem.max_per_procedure). No quantity-specific
    code exists in GLOSA_REASON_CODES, so — like stale_price — it stays an
    internal caution with no operator-facing ANS reason.
  * authorization_missing → "" (blank). The line's PriceTableItem requires an
    authorization (senha) but none is valid. GLOSA_REASON_CODES has no
    authorization-specific reason ("01"=não coberto and "04"=carência are
    different causes), so — like stale_price/quantity_exceeds — it stays an
    internal caution with no operator-facing ANS reason.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

# ── ANS glosa-code mapping (single source of truth) ───────────────────────────
# Keys mirror GlosaSafetyAlert.CheckCode values. See module docstring for the
# confidence notes; "" marks the cases with no operator-facing ANS reason.
ANS_CODE_NOT_IN_TABLE = "01"  # Procedimento não coberto
ANS_CODE_INCOMPLETE = "05"  # Inconsistência nos dados do beneficiário
# ANS TISS 4.01 Tabela 38: "Cobrança de procedimento em duplicidade". Item-level
# duplicate code (this alert is per-procedure). Must stay in sync with the entry
# added to apps.billing.models.GLOSA_REASON_CODES so the retorno parser round-trips
# an inbound "1702" instead of downgrading it to "99".
ANS_CODE_DUPLICATE = "1702"
ANS_CODE_STALE_PRICE = ""  # internal caution, no operator-facing ANS reason
ANS_CODE_TABLE_UNRESOLVED = ""  # coverage not verified — internal caution, no ANS reason
# Clinical-incompatibility ANS reason codes (glosa wedge G3b).
#   "03" → procedimento incompatível com a idade do beneficiário.
#   "02" → procedimento incompatível com o sexo do beneficiário.
# CID incompatibility has NO single fixed code in this codebase's
# GLOSA_REASON_CODES set, so it is left "" (blank/unmapped) for the faturista to
# confirm the exact operator-specific code — NOT guessed here.
ANS_CODE_AGE_INCOMPAT = "03"  # incompatível com a idade
ANS_CODE_SEX_INCOMPAT = "02"  # incompatível com o sexo
ANS_CODE_CID_INCOMPAT = ""  # no fixed ANS code — left blank, confirmed by faturista
# Per-procedure quantity ceiling (glosa wedge G3c). The GLOSA_REASON_CODES set in
# this codebase has NO quantity/limit-specific reason ("99/Outro" is too generic
# to assert confidently), so — like stale_price — this stays "" (blank): a
# contract-internal caution, not (yet) an operator-facing ANS denial reason. The
# faturista confirms the operator-specific code if a denial actually lands.
ANS_CODE_QUANTITY_EXCEEDS = ""  # no fixed ANS code — internal caution, left blank
# Authorization-required (glosa wedge G3d). The GLOSA_REASON_CODES set in this
# codebase has NO authorization/senha-specific reason: "01" (não coberto) is a
# coverage denial (a different cause), "04" (prazo de carência) is a waiting
# period, and "00/99" are too generic to assert. The ANS TISS standard's
# authorization-failure reasons are not represented here, so — like stale_price
# and quantity_exceeds — this stays "" (blank): an internal caution, not an
# operator-facing ANS denial reason. The faturista confirms the operator-specific
# code if a denial actually lands.
ANS_CODE_AUTHORIZATION_MISSING = ""  # no fixed ANS code — internal caution, left blank


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
    # ── Per-procedure quantity ceiling (G3c) ────────────────────────────────────
    # ``quantity`` is the guide line's quantity (TISSGuideItem.quantity is a
    # Decimal). ``max_per_procedure`` is the contract ceiling resolved by the
    # service off the line's ACTIVE PriceTableItem — None means NO ceiling, so the
    # quantity_exceeds check is INERT. Both default to the inert state so the pure
    # unit tests and safe callers fire nothing.
    quantity: Decimal = Decimal("0")
    max_per_procedure: int | None = None
    # ── Authorization (G3d) ──────────────────────────────────────────────────────
    # ``authorization_required`` mirrors the line's ACTIVE PriceTableItem
    # .requires_authorization (default False → the check is INERT for the item).
    # ``authorization_satisfied`` is PRE-RESOLVED by the service (NO DB here): it
    # is True when the guide already carries an authorization_number OR the service
    # found a matching approved+in-window Authorization row (matching patient +
    # provider + this item's TUSS, or a generic tuss=null auth). The engine only
    # compares these two booleans — it never queries the Authorization table. Both
    # default to the inert state (not required / treated as satisfied) so the pure
    # unit tests and safe callers fire nothing.
    authorization_required: bool = False
    authorization_satisfied: bool = False
    # ── Clinical-compatibility metadata (G3b), resolved by the service from the
    # public core.TUSSCode row. These are ANS-STANDARD TRUTH, never fabricated:
    # the service copies them straight off the TUSS row. When the row has no ANS
    # metadata (the default), the values below are INERT (null age window /
    # sex "B" / empty whitelist) and the clinical_incompat check fires NOTHING.
    tuss_age_min_days: int | None = None
    tuss_age_max_days: int | None = None
    tuss_sex_allowed: str = "B"  # M / F / B (B = both/any → no constraint)
    tuss_cid10_whitelist: list = field(default_factory=list)


@dataclass(frozen=True)
class GuideContext:
    """Plain, DB-free snapshot of a guide for the engine. The service fills it."""

    guide_type: str
    authorization_number: str
    insured_card_number: str
    competency: str
    cid10_codes: list
    items: list[GuideItemContext] = field(default_factory=list)
    # ── Patient clinical context (G3b), pre-computed by the service from the
    # guide's Patient: age in days from Patient.birth_date, sex from
    # Patient.gender normalised to M/F (anything else → None = unknown, so the
    # sex check stays inert). guide_cid10_codes is the flat list of CID-10 code
    # strings extracted from the guide's cid10_codes JSON. All default to the
    # inert "unknown / none" so the pure unit tests and safe callers fire nothing.
    patient_age_days: int | None = None
    patient_sex: str | None = None  # "M" / "F" / None (unknown → inert)
    guide_cid10_codes: list = field(default_factory=list)
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
    def _check_clinical_incompat(
        item: GuideItemContext, guide_ctx: GuideContext
    ) -> GlosaFinding | None:
        """Clinical-compatibility check (advise, NEVER block) — glosa wedge G3b.

        Compares the patient's age/sex and the guide's CID-10 codes against the
        ANS clinical-compatibility metadata on the procedure's TUSS row. INERT by
        construction: when the TUSS row carries no ANS metadata (null age window,
        sex_allowed="B", empty CID whitelist) NOTHING fires — and when the patient
        context is unknown (age None / sex None / no CIDs on the guide) the
        respective sub-check is skipped rather than guessed. Always ``advise``:
        the ANS source data is sparse/may have typos, so it must never block the
        close().

        All sub-violations for ONE item collapse into a SINGLE clinical_incompat
        finding (one message, joined reasons) so the per-item alert row stays
        unique under (guide, guide_item, check_code, source) — mirrors the
        guide-level ``_check_incomplete`` collapse. The most specific ANS code is
        kept (age "03" > sex "02" > cid blank), matching the order of detection.
        """
        reasons: list[str] = []
        ans_code = ANS_CODE_CID_INCOMPAT  # least specific default

        # ── age window ────────────────────────────────────────────────────────
        # Only meaningful when the TUSS has a bound AND we know the patient's age.
        age = guide_ctx.patient_age_days
        if age is not None and (
            item.tuss_age_min_days is not None or item.tuss_age_max_days is not None
        ):
            below = item.tuss_age_min_days is not None and age < item.tuss_age_min_days
            above = item.tuss_age_max_days is not None and age > item.tuss_age_max_days
            if below or above:
                lo = item.tuss_age_min_days if item.tuss_age_min_days is not None else "sem mínimo"
                hi = item.tuss_age_max_days if item.tuss_age_max_days is not None else "sem máximo"
                reasons.append(
                    f"idade do paciente ({age} dias) fora da janela permitida ({lo}–{hi} dias)"
                )
                ans_code = ANS_CODE_AGE_INCOMPAT

        # ── sex ───────────────────────────────────────────────────────────────
        # Only when the TUSS restricts to M or F AND we know the patient's sex.
        if (
            item.tuss_sex_allowed in ("M", "F")
            and guide_ctx.patient_sex is not None
            and guide_ctx.patient_sex != item.tuss_sex_allowed
        ):
            reasons.append(
                f"sexo do paciente ({guide_ctx.patient_sex}) incompatível "
                f"(permitido: {item.tuss_sex_allowed})"
            )
            if ans_code == ANS_CODE_CID_INCOMPAT:
                ans_code = ANS_CODE_SEX_INCOMPAT

        # ── CID-10 whitelist ──────────────────────────────────────────────────
        # Only meaningful when the TUSS has a non-empty whitelist AND the guide
        # actually carries at least one CID. A guide with NO CIDs must SKIP this
        # sub-check (an empty guide_cids is "unknown", not "incompatible") — the
        # missing-CID structural case is covered separately by _check_incomplete.
        # Compare case-insensitively: CID-10 codes are normalised to uppercase at
        # the data boundaries (guide extraction + whitelist import), and we upper
        # again here for defence-in-depth so "a00" matches whitelist "A00".
        whitelist = {str(c).strip().upper() for c in (item.tuss_cid10_whitelist or [])}
        guide_cids = {str(c).strip().upper() for c in (guide_ctx.guide_cid10_codes or [])}
        if whitelist and guide_cids and guide_cids.isdisjoint(whitelist):
            reasons.append(
                f"CID da guia não compatível (CIDs aceitos: {', '.join(sorted(whitelist))})"
            )

        if not reasons:
            return None

        joined = "; ".join(reasons)
        return GlosaFinding(
            check_code="clinical_incompat",
            severity=_SEVERITY_ADVISE,
            message=(
                f"Procedimento {item.tuss_code} clinicamente incompatível com o paciente: {joined}."
            ),
            recommendation=(
                "Confirme idade, sexo e diagnóstico (CID-10) do paciente e a indicação clínica "
                "do procedimento antes de faturar."
            ),
            ans_glosa_code=ans_code,
            guide_item_id=item.item_id,
        )

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
            # Clinical-compatibility (G3b) is TUSS-metadata driven, not price-table
            # driven, so it runs regardless of table_resolved. Always advise; one
            # combined finding per item (or None when inert).
            clinical = GlosaChecker._check_clinical_incompat(item, guide_ctx)
            if clinical is not None:
                findings.append(clinical)

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

        # QUANTITY_EXCEEDS (advise, NEVER block) — glosa wedge G3c. Purely local,
        # in-memory: when the line's active PriceTableItem carries a
        # max_per_procedure ceiling AND the line quantity exceeds it, advise. INERT
        # when max_per_procedure is None (the default → no ceiling configured).
        # Decimal-safe compare (quantity is a Decimal; the ceiling is an int).
        # Runs independently of table_resolved: the ceiling is None unless the
        # service resolved it off the active table, so this never fires spuriously.
        if item.max_per_procedure is not None and Decimal(item.quantity) > Decimal(
            item.max_per_procedure
        ):
            qty_str = Decimal(item.quantity).normalize()
            findings.append(
                GlosaFinding(
                    check_code="quantity_exceeds",
                    severity=_SEVERITY_ADVISE,
                    message=(
                        f"Quantidade do procedimento {item.tuss_code} ({qty_str}) acima do teto "
                        f"do procedimento no contrato ({qty_str} > {item.max_per_procedure})."
                    ),
                    recommendation=(
                        "Confirme se a quantidade está correta ou se há justificativa "
                        "(ex.: autorização específica) antes de faturar."
                    ),
                    ans_glosa_code=ANS_CODE_QUANTITY_EXCEEDS,
                    guide_item_id=item.item_id,
                )
            )

        # AUTHORIZATION_MISSING (advise, NEVER block) — glosa wedge G3d. Fires ONLY
        # when the line's active PriceTableItem is flagged requires_authorization
        # (authorization_required=True) AND no valid authorization was found
        # (authorization_satisfied=False). "Valid" is resolved by the service: the
        # guide already carries an authorization_number, OR a matching approved,
        # in-window Authorization row exists (patient + provider + this TUSS, or a
        # generic tuss=null auth). INERT when authorization_required is False (the
        # default), so procedures that need no senha are never false-flagged. Runs
        # independently of table_resolved: authorization_required is False unless
        # the service resolved it off the active table, so this never fires
        # spuriously when coverage is unknown.
        if item.authorization_required and not item.authorization_satisfied:
            findings.append(
                GlosaFinding(
                    check_code="authorization_missing",
                    severity=_SEVERITY_ADVISE,
                    message=(
                        f"Procedimento {item.tuss_code} exige autorização; "
                        f"nenhuma autorização válida encontrada."
                    ),
                    recommendation=(
                        "Solicite/registre a autorização (senha) da operadora — preencha a senha "
                        "na guia ou cadastre uma autorização aprovada e vigente antes de faturar."
                    ),
                    ans_glosa_code=ANS_CODE_AUTHORIZATION_MISSING,
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
