"""
Sprint M1-S2 — Livro de escrituração de controlados (SNGPC-like).

Regulatory book (livro de escrituração) per (controlled substance/Drug,
presentation, competency period) derived from the append-only StockMovement
ledger, plus a signed period closing with maker-checker segregation.

S2-T1 → TestControlledSubstanceLedger*
S2-T2 → TestControlledLedgerClosing*
"""

from datetime import date, datetime
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from apps.core.models import Role, User
from apps.pharmacy.models import (
    ControlledLedgerClosing,
    Drug,
    StockItem,
    StockMovement,
)
from apps.pharmacy.services.controlled_ledger import (
    ControlledLedgerBuilder,
    ControlledLedgerClosingService,
)
from apps.test_utils import TenantTestCase

JUL_START = date(2026, 7, 1)
JUL_END = date(2026, 7, 31)


def _aware(y, m, d):
    return timezone.make_aware(datetime(y, m, d, 12, 0))


def make_controlled_drug(controlled_class="A1", **kw):
    defaults = {
        "name": "Morfina",
        "dosage_form": "ampola",
        "concentration": "10mg/ml",
        "controlled_class": controlled_class,
        "unit_of_measure": "amp",
    }
    defaults.update(kw)
    return Drug.objects.create(**defaults)


def make_item(drug, **kw):
    return StockItem.objects.create(drug=drug, lot_number="L1", quantity=Decimal("0"), **kw)


def mv(item, qty, mtype="entry", when=None, actor=None):
    """Create a StockMovement; optionally backdate created_at (test-only)."""
    m = StockMovement(
        stock_item=item,
        movement_type=mtype,
        quantity=Decimal(qty),
        performed_by=actor,
    )
    m.save()
    if when is not None:
        # created_at is auto_now_add; QuerySet.update() bypasses the immutable
        # instance.save() guard so tests can place a movement in a prior period.
        StockMovement.objects.filter(pk=m.pk).update(created_at=when)
    return m


def pharmacist(email, perms=("pharmacy.controlled_book_sign",)):
    role = Role.objects.create(name=f"rt_{email}", permissions=list(perms))
    return User.objects.create_user(email=email, password="pw", role=role)


# ─── S2-T1 ────────────────────────────────────────────────────────────────────


class TestControlledSubstanceLedgerBuilder(TenantTestCase):
    def _seed(self):
        drug = make_controlled_drug()
        item = make_item(drug)
        # Prior period (June) — establishes the opening balance.
        mv(item, "100", "entry", when=_aware(2026, 6, 15))
        # In-period (July): +50 entry, -30 and -20 exits.
        mv(item, "50", "entry", when=_aware(2026, 7, 5))
        mv(item, "-30", "dispense", when=_aware(2026, 7, 10))
        mv(item, "-20", "dispense", when=_aware(2026, 7, 20))
        return drug

    def test_builder_reconciles_with_movements(self):
        drug = self._seed()
        ledger = ControlledLedgerBuilder.build(
            drug=drug, period_start=JUL_START, period_end=JUL_END
        )
        self.assertEqual(ledger.opening_balance, Decimal("100"))
        self.assertEqual(ledger.total_entries, Decimal("50"))
        self.assertEqual(ledger.total_exits, Decimal("50"))
        self.assertEqual(ledger.closing_balance, Decimal("100"))
        # Book identity: closing == opening + entries - exits.
        self.assertEqual(
            ledger.closing_balance,
            ledger.opening_balance + ledger.total_entries - ledger.total_exits,
        )
        # Reconciles with the raw StockMovement running total up to period end.
        running = sum(
            m.quantity
            for m in StockMovement.objects.filter(stock_item__drug=drug)
            if m.created_at.date() <= JUL_END
        )
        self.assertEqual(ledger.closing_balance, running)

    def test_snapshot_fields_capture_class_and_presentation(self):
        drug = self._seed()
        ledger = ControlledLedgerBuilder.build(
            drug=drug, period_start=JUL_START, period_end=JUL_END
        )
        self.assertEqual(ledger.controlled_class, "A1")
        self.assertIn("ampola", ledger.presentation)
        self.assertIn("10mg/ml", ledger.presentation)

    def test_only_controlled_drugs_are_booked(self):
        drug = make_controlled_drug(controlled_class="none", name="Dipirona")
        item = make_item(drug)
        mv(item, "10", "entry", when=_aware(2026, 7, 5))
        with self.assertRaises(ValidationError):
            ControlledLedgerBuilder.build(drug=drug, period_start=JUL_START, period_end=JUL_END)

    def test_explicit_opening_balance_override(self):
        drug = make_controlled_drug()
        item = make_item(drug)
        mv(item, "40", "entry", when=_aware(2026, 7, 5))
        ledger = ControlledLedgerBuilder.build(
            drug=drug,
            period_start=JUL_START,
            period_end=JUL_END,
            opening_balance=Decimal("7"),
        )
        self.assertEqual(ledger.opening_balance, Decimal("7"))
        self.assertEqual(ledger.closing_balance, Decimal("47"))

    def test_builder_records_maker(self):
        drug = self._seed()
        maker = pharmacist("maker@t.com")
        ledger = ControlledLedgerBuilder.build(
            drug=drug, period_start=JUL_START, period_end=JUL_END, actor=maker
        )
        self.assertEqual(ledger.built_by_id, maker.pk)


class TestControlledSubstanceLedgerImmutability(TenantTestCase):
    def _ledger(self):
        drug = make_controlled_drug()
        item = make_item(drug)
        mv(item, "10", "entry", when=_aware(2026, 7, 5))
        return ControlledLedgerBuilder.build(drug=drug, period_start=JUL_START, period_end=JUL_END)

    def test_update_blocked(self):
        ledger = self._ledger()
        ledger.total_entries = Decimal("999")
        with self.assertRaises(ValueError):
            ledger.save()

    def test_delete_blocked(self):
        ledger = self._ledger()
        with self.assertRaises(ValueError):
            ledger.delete()


# ─── S2-T2 ────────────────────────────────────────────────────────────────────


class TestControlledLedgerClosing(TenantTestCase):
    def setUp(self):
        self.drug = make_controlled_drug()
        item = make_item(self.drug)
        mv(item, "100", "entry", when=_aware(2026, 6, 15))
        mv(item, "50", "entry", when=_aware(2026, 7, 5))
        mv(item, "-30", "dispense", when=_aware(2026, 7, 10))
        self.maker = pharmacist("maker@t.com")
        self.checker = pharmacist("checker@t.com")
        self.ledger = ControlledLedgerBuilder.build(
            drug=self.drug,
            period_start=JUL_START,
            period_end=JUL_END,
            actor=self.maker,
        )

    def test_closing_requires_pharmacist(self):
        layperson = User.objects.create_user(email="clerk@t.com", password="pw")
        with self.assertRaises(PermissionDenied):
            ControlledLedgerClosingService.close(
                ledger=self.ledger,
                signer=layperson,
                checked_balance=self.ledger.closing_balance,
            )

    def test_maker_cannot_self_close(self):
        with self.assertRaises(PermissionDenied):
            ControlledLedgerClosingService.close(
                ledger=self.ledger,
                signer=self.maker,
                checked_balance=self.ledger.closing_balance,
            )

    def test_distinct_pharmacist_closes(self):
        closing = ControlledLedgerClosingService.close(
            ledger=self.ledger,
            signer=self.checker,
            checked_balance=self.ledger.closing_balance,
            signature_hash="abc123",
        )
        self.assertIsInstance(closing, ControlledLedgerClosing)
        self.assertEqual(closing.signed_by_id, self.checker.pk)
        self.assertIsNotNone(closing.closed_at)
        self.assertEqual(closing.signature_hash, "abc123")

    def test_cannot_close_twice(self):
        ControlledLedgerClosingService.close(
            ledger=self.ledger,
            signer=self.checker,
            checked_balance=self.ledger.closing_balance,
        )
        with self.assertRaises(ValidationError):
            ControlledLedgerClosingService.close(
                ledger=self.ledger,
                signer=self.checker,
                checked_balance=self.ledger.closing_balance,
            )

    def test_closed_period_rebuild_blocked(self):
        ControlledLedgerClosingService.close(
            ledger=self.ledger,
            signer=self.checker,
            checked_balance=self.ledger.closing_balance,
        )
        with self.assertRaises(ValidationError):
            ControlledLedgerBuilder.build(
                drug=self.drug,
                period_start=JUL_START,
                period_end=JUL_END,
                actor=self.maker,
            )

    def test_closing_is_immutable(self):
        closing = ControlledLedgerClosingService.close(
            ledger=self.ledger,
            signer=self.checker,
            checked_balance=self.ledger.closing_balance,
        )
        closing.checked_balance = Decimal("0")
        with self.assertRaises(ValueError):
            closing.save()
        with self.assertRaises(ValueError):
            closing.delete()

    def test_report_reflects_reconciled_balances(self):
        closing = ControlledLedgerClosingService.close(
            ledger=self.ledger,
            signer=self.checker,
            checked_balance=self.ledger.closing_balance,
        )
        report = ControlledLedgerClosingService.export_report(closing)
        self.assertEqual(report["controlled_class"], "A1")
        self.assertEqual(Decimal(str(report["opening_balance"])), Decimal("100"))
        self.assertEqual(Decimal(str(report["total_entries"])), Decimal("50"))
        self.assertEqual(Decimal(str(report["total_exits"])), Decimal("30"))
        self.assertEqual(Decimal(str(report["closing_balance"])), Decimal("120"))
        self.assertTrue(report["reconciles"])
        self.assertEqual(report["signer"]["email"], "checker@t.com")
        self.assertEqual(report["period"]["start"], "2026-07-01")
        # SNGPC seed: per-movement detail lines for the period.
        self.assertEqual(len(report["movements"]), 2)
