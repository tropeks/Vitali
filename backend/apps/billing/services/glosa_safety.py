"""Glosa-safety orchestrator — glosa-safety wedge PR G1.

Bridges the PURE deterministic engine (``apps.billing.services.glosa_checker``)
to the billing side-effects: resolving the provider's currently-active price
table, computing the cross-guide duplicate flag under an Encounter lock, writing
each engine finding to a ``GlosaSafetyAlert(source="engine")``, and recording the
flywheel ``AuditLog``. The engine DECIDES; this service persists.

Mirrors ``apps.emr.services.dose_safety.DoseCheckService``:
  * service-layer orchestrator, NOT signals;
  * atomic DB block; one AuditLog per side-effect with the labeled-example
    fields (gate, guide_id, item, check_code, severity, value) for the flywheel;
  * idempotent update_or_create keyed on the unique_together — never clobbers an
    acknowledged override unless the message genuinely changed;
  * fail-open: the engine raising degrades to a single advisory alert
    ("verificação de glosa indisponível"), NEVER a block (dose D-T3 parity);
  * feature flag ``glosa_safety`` (default OFF). When off, evaluate_guide is a
    no-op and ``has_blocking_glosa_alert`` returns False FIRST — so a stale
    flagged row from a previously-ON period can never permanently lock the gate.

Decision A-1: this is a DEDICATED model, not a reuse of apps.ai.GlosaPrediction.
Decision A-2: gate is PER-GUIA — the close() 409 names only the offending guides.
Decision A-5: was_denied stays NULL here (backfilled later, item-level).
"""

from __future__ import annotations

import datetime
import logging
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import uuid4

from django.db import connection, transaction
from django.db.models import Q

from apps.billing.models import (
    GlosaSafetyAlert,
    PriceTable,
    PriceTableItem,
    TISSGuideItem,
)
from apps.billing.services.glosa_checker import (
    GlosaChecker,
    GlosaFinding,
    GuideContext,
    GuideItemContext,
)
from apps.core.models import AuditLog
from apps.core.utils import tenant_has_feature

if TYPE_CHECKING:
    from apps.billing.models import TISSBatch, TISSGuide

logger = logging.getLogger(__name__)

GLOSA_SAFETY_FEATURE_KEY = "glosa_safety"

# Guide statuses that make a line "already presented" for DUPLICATE detection.
# A duplicate block means "this procedure was already PRESENTED to the payer on
# another guide" — the classic double-bill we must catch.
#
# INCLUDED (counts as already presented):
#   * pending   — queued for submission
#   * submitted — sent to the payer
#   * paid      — already PRESENTED and settled; re-billing the same
#                 encounter+TUSS on a NEW guide is the classic paid-then-rebilled
#                 double-bill. Excluding it was a false-negative that let a paid
#                 procedure be billed twice — so "paid" MUST be included.
#
# EXCLUDED:
#   * draft  — never presented to the payer (may be an abandoned draft for the
#              same encounter+TUSS); including it would permanently/falsely flag
#              the real guide as a duplicate (false BLOCK).
#   * denied — the payer GLOSOU this line; a re-presentation of the same
#              encounter+TUSS is a legitimate recurso/correction. Flagging it
#              would false-BLOCK the recovery flow.
#   * appeal — the line is in an active recurso; same rationale as denied — a
#              correction/re-presentation during the appeal must not be blocked.
#   * self   — the guide being evaluated is always excluded (see exclude() below).
#
# (Guides go draft→pending→submitted→paid/denied→appeal; there is no "closed"
# GUIDE status — "closed" is a BATCH status.)
_ACTIVE_GUIDE_STATUSES = ["pending", "submitted", "paid"]


class GlosaSafetyService:
    """Service-layer orchestrator for the deterministic glosa engine."""

    def __init__(self, *, requesting_user) -> None:
        self.requesting_user = requesting_user
        self.correlation_id = str(uuid4())

    # ── public API ────────────────────────────────────────────────────────────

    @classmethod
    def is_enabled(cls) -> bool:
        """True if the current tenant has the glosa_safety feature flag enabled."""
        try:
            tenant = connection.tenant  # type: ignore[attr-defined]
            return tenant_has_feature(tenant, GLOSA_SAFETY_FEATURE_KEY)
        except Exception:
            logger.warning(
                "Could not resolve glosa_safety feature flag; defaulting to disabled.",
                exc_info=True,
            )
            return False

    def evaluate_guide(self, guide: TISSGuide, *, gate: str) -> None:
        """Evaluate one guide and persist the engine's findings.

        No-op when the feature flag is off (gate behaves exactly as today). Builds
        the DB-derived context (active-table membership/value + cross-guide
        duplicate flag under an Encounter lock), runs the pure engine, then
        upserts a GlosaSafetyAlert per finding and resolves stale alerts whose
        finding no longer fires. Fails open: any engine/context exception degrades
        to a single advisory alert, never a block.

        ``gate`` is e.g. "batch_close" — recorded in the flywheel.
        """
        if not self.is_enabled():
            return

        try:
            with transaction.atomic():
                guide_ctx = self._build_context(guide)
                findings = GlosaChecker.check(guide_ctx=guide_ctx)
                self._persist(guide, findings, gate=gate)
        except Exception:
            logger.exception(
                "GlosaSafetyService.evaluate_guide failed for guide=%s — degrading to advisory.",
                getattr(guide, "id", None),
            )
            self._raise_engine_error_advisory(guide, gate=gate)

    @staticmethod
    def has_blocking_glosa_alert(guide: TISSGuide) -> bool:
        """True if the guide has an outstanding BLOCKING engine glosa alert.

        Blocking = source="engine", severity="block", status="flagged" (NOT yet
        acknowledged). Acknowledging flips status to "acknowledged", so the
        predicate stops matching and the re-close succeeds.

        When the glosa_safety flag is OFF this ALWAYS returns False FIRST, so the
        gate is fully released — a stale flagged row from a previously-ON period
        can never permanently lock the gate after the flag is turned off (mirrors
        the dose flag-off fix).
        """
        if not GlosaSafetyService.is_enabled():
            return False

        return GlosaSafetyAlert.objects.filter(
            guide=guide,
            source=GlosaSafetyAlert.Source.ENGINE,
            severity=GlosaSafetyAlert.Severity.BLOCK,
            status=GlosaSafetyAlert.Status.FLAGGED,
        ).exists()

    @staticmethod
    def blocking_glosa_alerts_for_batch(batch: TISSBatch):
        """List of (guide, [alerts]) for guides in the batch with unacked blocking
        alerts — the per-guide 409 payload. When the flag is OFF this is empty
        (has_blocking_glosa_alert short-circuits).

        DEPRECATED for the close() gate: it re-queries ``batch.guides.all()``, a
        FRESH set that may differ from the set close() actually evaluated (a
        concurrent ``guides.add`` between evaluation and this call would put an
        UNEVALUATED guide in the blocking set). The close() gate must instead use
        ``blocking_glosa_alerts_for_guides`` over the SAME id set it evaluated.
        Kept for any non-gate/diagnostic caller."""
        if not GlosaSafetyService.is_enabled():
            return []
        return GlosaSafetyService.blocking_glosa_alerts_for_guides(
            list(batch.guides.values_list("pk", flat=True))
        )

    @staticmethod
    def blocking_glosa_alerts_for_guides(guide_ids):
        """List of (guide, [alerts]) for the EXACT set of guide ids supplied that
        have unacknowledged BLOCKING engine alerts — the per-guide 409 payload.

        The close() gate passes the very id set it evaluated (captured once under
        the batch-row lock), so the evaluated set and the blocking-checked set are
        PROVABLY identical — no guide can be present-but-unevaluated between the
        two steps. When the flag is OFF this is empty (gate fully released)."""
        result: list[tuple[TISSGuide, list[GlosaSafetyAlert]]] = []
        if not GlosaSafetyService.is_enabled():
            return result
        if not guide_ids:
            return result

        alerts = (
            GlosaSafetyAlert.objects.filter(
                guide_id__in=guide_ids,
                source=GlosaSafetyAlert.Source.ENGINE,
                severity=GlosaSafetyAlert.Severity.BLOCK,
                status=GlosaSafetyAlert.Status.FLAGGED,
            )
            .select_related("guide")
            .order_by("guide_id")
        )

        by_guide: dict[object, list[GlosaSafetyAlert]] = {}
        guide_by_id: dict[object, TISSGuide] = {}
        for alert in alerts:
            by_guide.setdefault(alert.guide_id, []).append(alert)
            guide_by_id[alert.guide_id] = alert.guide
        for guide_id, guide_alerts in by_guide.items():
            result.append((guide_by_id[guide_id], guide_alerts))
        return result

    # ── context building (DB-derived inputs for the pure engine) ────────────────

    def _build_context(self, guide: TISSGuide) -> GuideContext:
        items = list(guide.items.select_related("tuss_code").all())

        # Active table for the provider covering the guide's effective date.
        # table_resolved tells the pure engine whether table-dependent checks
        # (not_in_table / stale_price) are MEANINGFUL: when no active table can
        # be confidently resolved, we must NOT block every line — fail toward a
        # single advise instead (see _active_table_values).
        active_value_by_tuss, table_resolved = self._active_table_values(guide)
        active_codes = set(active_value_by_tuss.keys())

        # Cross-guide duplicate detection (race fix, decision A-2): lock the
        # Encounter row FIRST so two concurrent closes cannot both pass, then find
        # other active-status guides' items with the same encounter + TUSS.
        duplicate_tuss = self._duplicate_tuss_codes(guide, [i.tuss_code.code for i in items])

        item_ctxs: list[GuideItemContext] = []
        for item in items:
            tuss = item.tuss_code
            code = tuss.code
            in_table = code in active_codes
            item_ctxs.append(
                GuideItemContext(
                    item_id=item.id,
                    tuss_code=code,
                    unit_value=Decimal(item.unit_value),
                    in_active_table=in_table,
                    active_table_value=active_value_by_tuss.get(code),
                    duplicate=code in duplicate_tuss,
                    # Clinical-compatibility metadata copied STRAIGHT off the
                    # public core.TUSSCode row (G3b). ANS-sourced, never
                    # fabricated; defaults (null/B/[]) keep the check inert.
                    tuss_age_min_days=tuss.age_min_days,
                    tuss_age_max_days=tuss.age_max_days,
                    tuss_sex_allowed=tuss.sex_allowed or "B",
                    tuss_cid10_whitelist=list(tuss.cid10_whitelist or []),
                )
            )

        # Patient clinical context for the G3b clinical_incompat check. Resolved
        # from the guide's Patient (emr.Patient.birth_date / .gender). Sex is
        # normalised to M/F; anything else (O/N/blank) → None so the sex check
        # stays inert. Age is computed in DAYS relative to the guide's effective
        # date (the billing date), not "now", so a re-evaluation is stable.
        patient_age_days, patient_sex = self._patient_clinical_context(guide)

        return GuideContext(
            guide_type=guide.guide_type,
            authorization_number=guide.authorization_number,
            insured_card_number=guide.insured_card_number,
            competency=guide.competency,
            cid10_codes=list(guide.cid10_codes or []),
            items=item_ctxs,
            table_resolved=table_resolved,
            patient_age_days=patient_age_days,
            patient_sex=patient_sex,
            guide_cid10_codes=self._guide_cid10_code_list(guide),
        )

    def _patient_clinical_context(self, guide: TISSGuide) -> tuple[int | None, str | None]:
        """(age_in_days, sex) for the guide's patient, for the G3b check.

        Age is computed from ``emr.Patient.birth_date`` relative to the guide's
        effective (billing) date. Sex comes from ``emr.Patient.gender``,
        normalised to "M"/"F"; the model's other choices (O = Outro, N = Não
        informado) and any blank map to None, which the engine treats as
        "unknown" → the sex sub-check stays inert (never guesses a constraint)."""
        patient = getattr(guide, "patient", None)
        if patient is None:
            return None, None

        age_days: int | None = None
        birth = getattr(patient, "birth_date", None)
        if birth is not None:
            effective = self._guide_effective_date(guide)
            age_days = max((effective - birth).days, 0)

        gender = (getattr(patient, "gender", "") or "").upper()
        sex = gender if gender in ("M", "F") else None
        return age_days, sex

    @staticmethod
    def _guide_cid10_code_list(guide: TISSGuide) -> list[str]:
        """Flatten the guide's ``cid10_codes`` JSON (list of {"code": "X00"}) to a
        plain list of CID-10 code strings for the whitelist comparison. Tolerates
        either dicts or bare strings; skips anything without a code."""
        out: list[str] = []
        for entry in guide.cid10_codes or []:
            if isinstance(entry, dict):
                code = (entry.get("code") or "").strip().upper()
            else:
                code = str(entry).strip().upper()
            if code:
                out.append(code)
        return out

    def _guide_effective_date(self, guide: TISSGuide) -> datetime.date:
        """The actual date used to test PriceTable validity windows.

        We compare against a real DATE (not the 1st-of-month competency floor)
        so a table negotiated mid-month — valid_from on the 15th — still covers a
        guide created on/after the 15th. Prefer the guide's own creation date
        (the real date the procedure was billed); fall back to the competency
        month's first day, then to today, so we always have a concrete date."""
        created = getattr(guide, "created_at", None)
        if created is not None:
            return created.date() if isinstance(created, datetime.datetime) else created
        competency_date = self._competency_to_date(guide.competency)
        if competency_date is not None:
            return competency_date
        return datetime.date.today()

    def _active_table_values(self, guide: TISSGuide) -> tuple[dict[str, Decimal], bool]:
        """Resolve the provider's CURRENTLY ACTIVE PriceTable whose validity window
        contains the guide's effective date, and return
        ({tuss_code: negotiated_value}, table_resolved).

        Robust resolution: an active table covers the guide when its
        valid_from is on/before the effective date AND valid_until is null or
        on/after it. A table negotiated mid-month (valid_from = the 15th) thus
        still covers a guide dated the 15th-or-later — the old 1st-of-month
        competency floor would have wrongly excluded it and flagged EVERY line
        not_in_table.  If multiple tables match, pick the most recent valid_from.

        Returns table_resolved=False with an empty dict when NO active table can
        be confidently resolved. The caller/engine must then SKIP the
        table-dependent checks and emit a single advise (never block every
        line)."""
        effective_date = self._guide_effective_date(guide)

        table = (
            PriceTable.objects.filter(provider=guide.provider, is_active=True)
            .filter(valid_from__lte=effective_date)
            .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=effective_date))
            .order_by("-valid_from")
            .first()
        )
        if table is None:
            return {}, False

        values = {
            pti.tuss_code.code: Decimal(pti.negotiated_value)
            for pti in PriceTableItem.objects.filter(table=table).select_related("tuss_code")
        }
        return values, True

    def _duplicate_tuss_codes(self, guide: TISSGuide, tuss_codes: list[str]) -> set[str]:
        """TUSS codes on this guide that ALSO appear on another active-status guide
        of the SAME encounter. Locks the Encounter row first (select_for_update)
        so two concurrent batch closes cannot both slip a duplicate past."""
        if not tuss_codes:
            return set()

        # Lock the encounter row FIRST — serialises concurrent evaluations of any
        # guide sharing this encounter. Use guide.encounter_id (already loaded)
        # so we do NOT trigger a redundant lazy fetch of the Encounter object.
        from apps.emr.models import Encounter

        Encounter.objects.select_for_update().filter(pk=guide.encounter_id).first()

        return set(
            TISSGuideItem.objects.filter(
                guide__encounter_id=guide.encounter_id,
                guide__status__in=_ACTIVE_GUIDE_STATUSES,
                tuss_code__code__in=tuss_codes,
            )
            .exclude(guide_id=guide.id)
            .values_list("tuss_code__code", flat=True)
        )

    @staticmethod
    def _competency_to_date(competency: str) -> datetime.date | None:
        """'AAAA-MM' → first day of that month, for the validity-window compare.
        None when unparseable (then we skip the window filter and take the latest
        active table)."""
        if not competency:
            return None
        try:
            year, month = competency.split("-")
            return datetime.date(int(year), int(month), 1)
        except (ValueError, TypeError):
            return None

    # ── persistence ─────────────────────────────────────────────────────────────

    def _persist(self, guide: TISSGuide, findings: list[GlosaFinding], *, gate: str) -> None:
        """Upsert one alert per finding (keyed on the unique_together), then
        resolve any previously-flagged alert whose finding no longer fires."""
        fired_keys: set[tuple] = set()

        for finding in findings:
            key = (finding.check_code, finding.guide_item_id)
            fired_keys.add(key)
            self._upsert_alert(guide, finding, gate=gate)

        # Resolve stale alerts: still flagged/acknowledged engine alerts whose
        # (check_code, guide_item) is no longer produced by the engine.
        self._resolve_stale(guide, fired_keys, gate=gate)

    def _upsert_alert(self, guide: TISSGuide, finding: GlosaFinding, *, gate: str) -> None:
        guide_item = None
        if finding.guide_item_id is not None:
            guide_item = TISSGuideItem.objects.filter(pk=finding.guide_item_id).first()

        existing = (
            GlosaSafetyAlert.objects.select_for_update()
            .filter(
                guide=guide,
                guide_item=guide_item,
                check_code=finding.check_code,
                source=GlosaSafetyAlert.Source.ENGINE,
            )
            .first()
        )

        # Override-preservation: an already-acknowledged alert for the SAME
        # situation (same message) must NOT be reset and re-blocked on
        # re-evaluation — the override stands. Only a genuinely changed message
        # (e.g. the value was edited) resets the ack. Mirrors the dose lesson.
        if (
            existing is not None
            and existing.status == GlosaSafetyAlert.Status.ACKNOWLEDGED
            and existing.message == finding.message
        ):
            self._audit("glosa_alert_override_kept", guide, finding, gate, alert_id=existing.id)
            return

        alert, _created = GlosaSafetyAlert.objects.update_or_create(
            guide=guide,
            guide_item=guide_item,
            check_code=finding.check_code,
            source=GlosaSafetyAlert.Source.ENGINE,
            defaults={
                "severity": finding.severity,
                "status": GlosaSafetyAlert.Status.FLAGGED,
                "message": finding.message,
                "recommendation": finding.recommendation,
                "ans_glosa_code": finding.ans_glosa_code,
                # A new/changed finding must re-flag, so reset the ack fields.
                "acknowledged_by": None,
                "override_reason": "",
                "acknowledged_at": None,
            },
        )
        self._audit("glosa_alert_raised", guide, finding, gate, alert_id=alert.id)

    def _resolve_stale(self, guide: TISSGuide, fired_keys: set[tuple], *, gate: str) -> None:
        open_alerts = GlosaSafetyAlert.objects.filter(
            guide=guide,
            source=GlosaSafetyAlert.Source.ENGINE,
        ).exclude(status=GlosaSafetyAlert.Status.RESOLVED)
        for alert in open_alerts:
            if (alert.check_code, alert.guide_item_id) in fired_keys:
                continue
            alert.status = GlosaSafetyAlert.Status.RESOLVED
            alert.acknowledged_by = None
            alert.override_reason = ""
            alert.acknowledged_at = None
            alert.save(
                update_fields=[
                    "status",
                    "acknowledged_by",
                    "override_reason",
                    "acknowledged_at",
                    "updated_at",
                ]
            )
            self._audit_resolved(guide, alert, gate)

    def _raise_engine_error_advisory(self, guide: TISSGuide, *, gate: str) -> None:
        """Fail-open: a single guide-level advisory alert when the engine/context
        raised. NEVER blocking (dose D-T3 ENGINE_ERROR=advisory parity)."""
        try:
            with transaction.atomic():
                alert, _created = GlosaSafetyAlert.objects.update_or_create(
                    guide=guide,
                    guide_item=None,
                    check_code=GlosaSafetyAlert.CheckCode.ENGINE_ERROR,
                    source=GlosaSafetyAlert.Source.ENGINE,
                    defaults={
                        "severity": GlosaSafetyAlert.Severity.ADVISE,
                        "status": GlosaSafetyAlert.Status.FLAGGED,
                        "message": (
                            "Verificação de glosa indisponível (falha interna); "
                            "confira a guia manualmente."
                        ),
                        "recommendation": "Revise a guia manualmente antes do envio.",
                        "ans_glosa_code": "",
                        "acknowledged_by": None,
                        "override_reason": "",
                        "acknowledged_at": None,
                    },
                )
                AuditLog.objects.create(
                    user=self.requesting_user,
                    action="glosa_check_unavailable",
                    resource_type="tiss_guide",
                    resource_id=str(guide.id),
                    new_data={
                        "correlation_id": self.correlation_id,
                        "gate": gate,
                        "guide_id": str(guide.id),
                        "alert_id": str(alert.id),
                    },
                )
        except Exception:
            logger.exception("Failed to write glosa engine-error advisory for guide=%s", guide.id)

    # ── audit (flywheel) ─────────────────────────────────────────────────────────

    def _audit(
        self, action: str, guide: TISSGuide, finding: GlosaFinding, gate: str, *, alert_id
    ) -> None:
        """One AuditLog per side-effect, carrying the labeled-example flywheel
        fields (gate, guide_id, item, check_code, severity, value)."""
        value = None
        if finding.guide_item_id is not None:
            item = TISSGuideItem.objects.filter(pk=finding.guide_item_id).first()
            if item is not None:
                value = str(item.unit_value)
        AuditLog.objects.create(
            user=self.requesting_user,
            action=action,
            resource_type="tiss_guide",
            resource_id=str(guide.id),
            new_data={
                "correlation_id": self.correlation_id,
                "gate": gate,
                "guide_id": str(guide.id),
                "guide_item_id": str(finding.guide_item_id)
                if finding.guide_item_id is not None
                else None,
                "check_code": finding.check_code,
                "severity": finding.severity,
                "ans_glosa_code": finding.ans_glosa_code,
                "value": value,
                "alert_id": str(alert_id),
                "message": finding.message,
            },
        )

    def _audit_resolved(self, guide: TISSGuide, alert: GlosaSafetyAlert, gate: str) -> None:
        AuditLog.objects.create(
            user=self.requesting_user,
            action="glosa_alert_resolved",
            resource_type="tiss_guide",
            resource_id=str(guide.id),
            new_data={
                "correlation_id": self.correlation_id,
                "gate": gate,
                "guide_id": str(guide.id),
                "guide_item_id": str(alert.guide_item_id)
                if alert.guide_item_id is not None
                else None,
                "check_code": alert.check_code,
                "severity": alert.severity,
                "alert_id": str(alert.id),
            },
        )
