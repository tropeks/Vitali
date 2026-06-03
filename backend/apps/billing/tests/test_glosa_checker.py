"""Unit tests for the PURE deterministic glosa engine (wedge PR G1).

These never touch the DB — they build GuideContext/GuideItemContext by hand and
assert the findings + severities. Mirrors apps.emr.tests for the dose engine.

Run: python manage.py test apps.billing.tests.test_glosa_checker
"""

from decimal import Decimal
from unittest import TestCase

from apps.billing.services.glosa_checker import (
    ANS_CODE_INCOMPLETE,
    ANS_CODE_NOT_IN_TABLE,
    GlosaChecker,
    GuideContext,
    GuideItemContext,
)


def _item(**overrides):
    base = {
        "item_id": 1,
        "tuss_code": "10101012",
        "unit_value": Decimal("100.00"),
        "in_active_table": True,
        "active_table_value": Decimal("100.00"),
        "duplicate": False,
    }
    base.update(overrides)
    return GuideItemContext(**base)


def _ctx(items=None, **overrides):
    base = {
        "guide_type": "sadt",
        "authorization_number": "AUTH123",
        "insured_card_number": "0001234567890001",
        "competency": "2026-03",
        "cid10_codes": [{"code": "J00"}],
        "items": items if items is not None else [_item()],
    }
    base.update(overrides)
    return GuideContext(**base)


class GlosaCheckerTests(TestCase):
    """Each of the 4 checks fires with the right severity; clean guide is silent."""

    def test_clean_guide_no_findings(self):
        findings = GlosaChecker.check(guide_ctx=_ctx())
        self.assertEqual(findings, [])

    def test_duplicate_fires_block(self):
        findings = GlosaChecker.check(guide_ctx=_ctx(items=[_item(duplicate=True)]))
        codes = {(f.check_code, f.severity) for f in findings}
        self.assertIn(("duplicate", "block"), codes)
        dup = next(f for f in findings if f.check_code == "duplicate")
        self.assertEqual(dup.guide_item_id, 1)
        self.assertIn("10101012", dup.message)

    def test_not_in_table_fires_block(self):
        findings = GlosaChecker.check(
            guide_ctx=_ctx(items=[_item(in_active_table=False, active_table_value=None)])
        )
        nit = next(f for f in findings if f.check_code == "not_in_table")
        self.assertEqual(nit.severity, "block")
        self.assertEqual(nit.ans_glosa_code, ANS_CODE_NOT_IN_TABLE)
        self.assertEqual(nit.guide_item_id, 1)

    def test_stale_price_fires_advise_with_decimal_compare(self):
        # Snapshot 100.00 diverges from currently-active 120.50 → advise.
        findings = GlosaChecker.check(
            guide_ctx=_ctx(
                items=[_item(unit_value=Decimal("100.00"), active_table_value=Decimal("120.50"))]
            )
        )
        stale = next(f for f in findings if f.check_code == "stale_price")
        self.assertEqual(stale.severity, "advise")
        self.assertIn("100.00", stale.message)
        self.assertIn("120.50", stale.message)

    def test_stale_price_equal_value_no_finding(self):
        # Equal Decimal values must NOT fire (decimal compare, not float).
        findings = GlosaChecker.check(
            guide_ctx=_ctx(
                items=[_item(unit_value=Decimal("100.0"), active_table_value=Decimal("100.00"))]
            )
        )
        self.assertEqual([f.check_code for f in findings], [])

    def test_not_in_table_and_stale_price_mutually_exclusive(self):
        # When not in the table, stale_price must NOT also fire for the same item.
        findings = GlosaChecker.check(
            guide_ctx=_ctx(
                items=[
                    _item(
                        in_active_table=False,
                        active_table_value=None,
                        unit_value=Decimal("100.00"),
                    )
                ]
            )
        )
        codes = [f.check_code for f in findings]
        self.assertIn("not_in_table", codes)
        self.assertNotIn("stale_price", codes)

    def test_incomplete_missing_card_fires_advise(self):
        findings = GlosaChecker.check(guide_ctx=_ctx(insured_card_number=""))
        inc = next(f for f in findings if f.check_code == "incomplete")
        self.assertEqual(inc.severity, "advise")
        self.assertIsNone(inc.guide_item_id)
        self.assertEqual(inc.ans_glosa_code, ANS_CODE_INCOMPLETE)
        self.assertIn("carteirinha", inc.message)

    def test_incomplete_missing_competency_and_cid(self):
        findings = GlosaChecker.check(guide_ctx=_ctx(competency="", cid10_codes=[]))
        inc = next(f for f in findings if f.check_code == "incomplete")
        self.assertIn("competência", inc.message)
        self.assertIn("CID-10", inc.message)

    def test_missing_auth_is_advise_only_never_block(self):
        # Missing authorization_number is folded into the (advise) incomplete
        # finding — and NEVER produces a block in G1.
        findings = GlosaChecker.check(guide_ctx=_ctx(authorization_number=""))
        blocks = [f for f in findings if f.severity == "block"]
        self.assertEqual(blocks, [])
        inc = next(f for f in findings if f.check_code == "incomplete")
        self.assertIn("senha de autorização", inc.message)

    def test_complete_guide_with_auth_present_no_incomplete(self):
        findings = GlosaChecker.check(guide_ctx=_ctx())
        self.assertNotIn("incomplete", [f.check_code for f in findings])

    def test_multiple_findings_combine(self):
        # A duplicate line on a guide that is also missing CID-10 → both fire.
        findings = GlosaChecker.check(guide_ctx=_ctx(items=[_item(duplicate=True)], cid10_codes=[]))
        codes = {f.check_code for f in findings}
        self.assertEqual(codes, {"duplicate", "incomplete"})

    # ── FIX 2: table_resolved=False suppresses table checks, emits one advise ──

    def test_table_unresolved_suppresses_not_in_table_and_emits_one_advise(self):
        # Two items NOT in any table, but table_resolved=False → engine must NOT
        # block either line with not_in_table; instead exactly ONE guide-level
        # table_unresolved advise (fail toward advise, never block).
        items = [
            _item(item_id=1, in_active_table=False, active_table_value=None),
            _item(item_id=2, in_active_table=False, active_table_value=None),
        ]
        findings = GlosaChecker.check(guide_ctx=_ctx(items=items, table_resolved=False))
        codes = [f.check_code for f in findings]
        self.assertNotIn("not_in_table", codes)
        self.assertNotIn("stale_price", codes)
        self.assertEqual(codes.count("table_unresolved"), 1)
        adv = next(f for f in findings if f.check_code == "table_unresolved")
        self.assertEqual(adv.severity, "advise")
        self.assertIsNone(adv.guide_item_id)
        self.assertEqual([f for f in findings if f.severity == "block"], [])

    def test_table_unresolved_still_allows_duplicate_block(self):
        # Duplicate is NOT table-dependent — it must still fire even when the
        # table is unresolved.
        findings = GlosaChecker.check(
            guide_ctx=_ctx(items=[_item(duplicate=True)], table_resolved=False)
        )
        codes = {f.check_code for f in findings}
        self.assertIn("duplicate", codes)
        self.assertIn("table_unresolved", codes)
        self.assertNotIn("not_in_table", codes)
