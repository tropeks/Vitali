"""
Regression tests for the professional-settlement / reconciliation hardening:

  * DjangoFilterBackend is actually wired (?status= filters instead of being
    silently ignored).
  * approve() never commits a phantom 'matched' tx on the already-settled path,
    and at most one bank transaction can settle a given receivable.
  * Maker-checker (segregation of duties) on payables and settlements rejects
    self-approval and requires a distinct approver.
  * Settlement approval is written to the audit trail.

Run: python manage.py test apps.billing.tests.test_settlement_reconciliation
"""

import datetime
from decimal import Decimal

from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.test import APIClient

from apps.billing.models import (
    AccountingCategory,
    AccountingEntry,
    AccountsReceivable,
    BankTransaction,
    InsuranceProvider,
    ProfessionalSettlement,
    TISSGuide,
)
from apps.core.models import AuditLog, FeatureFlag, Role, User
from apps.emr.models import Encounter, Patient, Professional
from apps.test_utils import TenantTestCase


class SettlementReconciliationTestCase(TenantTestCase):
    """Runs inside a tenant schema."""

    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain

        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant, module_key="billing", defaults={"is_enabled": True}
        )

        self.faturista_role = Role.objects.create(
            name="faturista",
            permissions=["billing.read", "billing.write"],
            is_system=True,
        )

        # Two distinct billing users → maker (creator) and checker (approver).
        self.maker = User.objects.create_user(
            email="maker@test.com",
            full_name="Maker Test",
            password="Str0ng!Pass#2024",
            role=self.faturista_role,
        )
        self.checker = User.objects.create_user(
            email="checker@test.com",
            full_name="Checker Test",
            password="Str0ng!Pass#2024",
            role=self.faturista_role,
        )
        prof_user = User.objects.create_user(
            email="prof@test.com",
            full_name="Dr. Prof",
            password="Str0ng!Pass#2024",
            role=self.faturista_role,
        )

        self.patient = Patient.objects.create(
            full_name="Maria Test",
            cpf="000.000.000-00",
            birth_date=datetime.date(1985, 1, 1),
            gender="F",
        )
        self.professional = Professional.objects.create(
            user=prof_user,
            council_type="CRM",
            council_number="99999",
            council_state="SP",
        )
        self.encounter = Encounter.objects.create(
            patient=self.patient,
            professional=self.professional,
        )
        self.provider = InsuranceProvider.objects.create(name="Unimed Test", ans_code="999999")

        self.maker_token = self._get_token("maker@test.com")
        self.checker_token = self._get_token("checker@test.com")

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _get_token(self, email):
        resp = self.client.post(
            "/api/v1/auth/login",
            {"email": email, "password": "Str0ng!Pass#2024"},
            format="json",
        )
        return resp.json().get("access")

    def _auth(self, token):
        c = APIClient()
        c.defaults["SERVER_NAME"] = self.__class__.domain.domain
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        return c

    def _make_guide(self, card="0001234567890001"):
        return TISSGuide.objects.create(
            guide_type="sadt",
            encounter=self.encounter,
            patient=self.patient,
            provider=self.provider,
            insured_card_number=card,
            competency="2026-03",
        )

    def _make_receivable(self, amount="100.00", status="billed"):
        return AccountsReceivable.objects.create(
            guide=self._make_guide(), amount=Decimal(amount), status=status
        )

    def _make_tx(self, external_id, amount="100.00", status="unmatched", receivable=None):
        return BankTransaction.objects.create(
            external_id=external_id,
            occurred_at=timezone.now(),
            amount=Decimal(amount),
            status=status,
            receivable=receivable,
        )

    # ── P1: DjangoFilterBackend wired ───────────────────────────────────────────

    def test_bank_transaction_status_filter_actually_filters(self):
        """?status=unmatched must return only unmatched rows (previously the
        filter backend was not wired, so every row leaked through)."""
        self._make_tx("tx-unm-1", status="unmatched")
        self._make_tx("tx-unm-2", status="unmatched")
        self._make_tx("tx-rev-1", status="review")
        rec = self._make_receivable()
        self._make_tx("tx-mat-1", status="matched", receivable=rec)

        client = self._auth(self.maker_token)
        resp = client.get("/api/v1/billing/bank-transactions/?status=unmatched")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        results = body["results"] if isinstance(body, dict) and "results" in body else body
        self.assertEqual(len(results), 2)
        self.assertTrue(all(r["status"] == "unmatched" for r in results))

        # Sanity: without the filter all four rows are visible.
        resp_all = client.get("/api/v1/billing/bank-transactions/")
        body_all = resp_all.json()
        all_results = body_all["results"] if "results" in body_all else body_all
        self.assertEqual(len(all_results), 4)

    # ── P1: approve() phantom fix + single-settlement invariant ─────────────────

    def test_approve_already_settled_does_not_commit_phantom_matched_tx(self):
        """Two bank rows bound to the SAME receivable: the first approve settles
        it; the second must 409 AND leave its own tx un-mutated (no phantom
        'matched'). Exactly one matched tx may exist for the receivable."""
        rec = self._make_receivable()
        tx1 = self._make_tx("tx-a", status="review", receivable=rec)
        tx2 = self._make_tx("tx-b", status="review", receivable=rec)

        client = self._auth(self.checker_token)
        r1 = client.post(f"/api/v1/billing/bank-transactions/{tx1.pk}/approve/")
        self.assertEqual(r1.status_code, 200)

        r2 = client.post(f"/api/v1/billing/bank-transactions/{tx2.pk}/approve/")
        self.assertEqual(r2.status_code, 409)

        tx1.refresh_from_db()
        tx2.refresh_from_db()
        rec.refresh_from_db()
        self.assertEqual(tx1.status, "matched")
        # No phantom: the losing tx was NOT flipped to matched (atomic rolled back).
        self.assertEqual(tx2.status, "review")
        self.assertEqual(rec.status, "received")
        self.assertEqual(
            BankTransaction.objects.filter(receivable=rec, status="matched").count(), 1
        )

    def test_db_constraint_blocks_two_matched_tx_per_receivable(self):
        """The partial unique index is the last line of defence even if the app
        locks were bypassed."""
        rec = self._make_receivable()
        self._make_tx("tx-c", status="matched", receivable=rec)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._make_tx("tx-d", status="matched", receivable=rec)

    # ── P2: maker-checker on payables ───────────────────────────────────────────

    def test_payable_self_approval_rejected(self):
        maker = self._auth(self.maker_token)
        create = maker.post(
            "/api/v1/billing/payables/",
            {
                "external_id": "pay-1",
                "description": "Aluguel",
                "amount": "500.00",
                "due_date": "2026-04-10",
            },
            format="json",
        )
        self.assertEqual(create.status_code, 201, create.content)
        pk = create.json()["id"]

        # Creator cannot approve their own payable.
        self_approve = maker.post(f"/api/v1/billing/payables/{pk}/approve/")
        self.assertEqual(self_approve.status_code, 403)

        # A payable cannot be paid before approval.
        early_pay = self._auth(self.checker_token).post(f"/api/v1/billing/payables/{pk}/pay/")
        self.assertEqual(early_pay.status_code, 409)

        # A DIFFERENT user approves, then pays.
        checker = self._auth(self.checker_token)
        ok_approve = checker.post(f"/api/v1/billing/payables/{pk}/approve/")
        self.assertEqual(ok_approve.status_code, 200)
        self.assertEqual(ok_approve.json()["status"], "approved")
        ok_pay = checker.post(f"/api/v1/billing/payables/{pk}/pay/")
        self.assertEqual(ok_pay.status_code, 200)
        self.assertEqual(ok_pay.json()["status"], "paid")

    # ── P2: maker-checker on settlements + audit ────────────────────────────────

    def test_settlement_self_approval_rejected_and_audited(self):
        settlement = ProfessionalSettlement.objects.create(
            professional=self.professional,
            competency="2026-03",
            created_by=self.maker,
        )

        # Creator cannot approve their own settlement.
        maker = self._auth(self.maker_token)
        self_approve = maker.post(f"/api/v1/billing/settlements/{settlement.pk}/approve/")
        self.assertEqual(self_approve.status_code, 403)

        # A distinct approver succeeds and the transition is audited.
        checker = self._auth(self.checker_token)
        ok = checker.post(f"/api/v1/billing/settlements/{settlement.pk}/approve/")
        self.assertEqual(ok.status_code, 200)
        settlement.refresh_from_db()
        self.assertEqual(settlement.status, "approved")
        self.assertEqual(settlement.approved_by_id, self.checker.id)

        self.assertTrue(
            AuditLog.objects.filter(
                action="settlement_approved", resource_id=str(settlement.pk)
            ).exists()
        )

        # pay() requires the prior approval and moves it to paid.
        pay = checker.post(f"/api/v1/billing/settlements/{settlement.pk}/pay/")
        self.assertEqual(pay.status_code, 200)
        settlement.refresh_from_db()
        self.assertEqual(settlement.status, "paid")

    def test_settlement_status_patch_is_ignored(self):
        """Plain PATCH cannot jump the status (it is read-only); transitions must
        go through approve()/pay()."""
        settlement = ProfessionalSettlement.objects.create(
            professional=self.professional,
            competency="2026-03",
            created_by=self.maker,
        )
        checker = self._auth(self.checker_token)
        resp = checker.patch(
            f"/api/v1/billing/settlements/{settlement.pk}/",
            {"status": "paid"},
            format="json",
        )
        self.assertIn(resp.status_code, (200, 400))
        settlement.refresh_from_db()
        self.assertEqual(settlement.status, "draft")

    # ── P3: recalculate rate coercion ───────────────────────────────────────────

    def test_recalculate_accepts_float_rate_without_typeerror(self):
        settlement = ProfessionalSettlement.objects.create(
            professional=self.professional,
            competency="2026-03",
            deductions=Decimal("10.00"),
            created_by=self.maker,
        )
        # A float rate previously raised Decimal * float TypeError.
        settlement.recalculate(rate=0.5)
        self.assertIsInstance(settlement.net_amount, Decimal)

    # ── Follow-up 1: reject() unbinds + audits ──────────────────────────────────

    def test_reject_unbinds_reviewed_tx_and_audits(self):
        """Rejecting a suggested (review) match unbinds the receivable and
        returns the tx to 'unmatched', writing a bank_tx_rejected audit row.
        The receivable was never settled in 'review', so it is untouched."""
        rec = self._make_receivable(status="billed")
        tx = self._make_tx("tx-rej-1", status="review", receivable=rec)

        client = self._auth(self.checker_token)
        resp = client.post(f"/api/v1/billing/bank-transactions/{tx.pk}/reject/")
        self.assertEqual(resp.status_code, 200)

        tx.refresh_from_db()
        rec.refresh_from_db()
        self.assertEqual(tx.status, "unmatched")
        self.assertIsNone(tx.receivable_id)
        self.assertIsNone(tx.confidence)
        self.assertIsNone(tx.matched_at)
        # Review never settled the receivable → left as-is.
        self.assertEqual(rec.status, "billed")

        self.assertTrue(
            AuditLog.objects.filter(action="bank_tx_rejected", resource_id=str(tx.pk)).exists()
        )

    def test_reject_matched_tx_unsettles_receivable(self):
        """Rejecting a fully matched (approved) tx also un-settles the receivable
        so we never leave a 'received' receivable with no settling transaction."""
        rec = self._make_receivable(status="billed")
        tx = self._make_tx("tx-rej-2", status="review", receivable=rec)
        client = self._auth(self.checker_token)
        self.assertEqual(
            client.post(f"/api/v1/billing/bank-transactions/{tx.pk}/approve/").status_code, 200
        )
        rec.refresh_from_db()
        self.assertEqual(rec.status, "received")

        resp = client.post(f"/api/v1/billing/bank-transactions/{tx.pk}/reject/")
        self.assertEqual(resp.status_code, 200)
        tx.refresh_from_db()
        rec.refresh_from_db()
        self.assertEqual(tx.status, "unmatched")
        self.assertIsNone(tx.receivable_id)
        self.assertEqual(rec.status, "billed")
        self.assertIsNone(rec.received_at)
        # No matched tx remains for the receivable.
        self.assertEqual(
            BankTransaction.objects.filter(receivable=rec, status="matched").count(), 0
        )

    def test_reject_is_idempotent(self):
        """Rejecting an already-unmatched, unbound tx is a harmless no-op."""
        tx = self._make_tx("tx-rej-3", status="unmatched")
        client = self._auth(self.checker_token)
        resp = client.post(f"/api/v1/billing/bank-transactions/{tx.pk}/reject/")
        self.assertEqual(resp.status_code, 200)
        tx.refresh_from_db()
        self.assertEqual(tx.status, "unmatched")
        self.assertIsNone(tx.receivable_id)

    # ── Follow-up 2: dre honors unit / cost_center ──────────────────────────────

    def test_dre_filters_by_unit_and_cost_center(self):
        """The DRE @action must scope revenue/expense by the unit and cost_center
        query params (previously ignored)."""
        cat = AccountingCategory.objects.create(code="3.1", name="Receitas", kind="revenue")
        # Two revenue entries in the same competency, different unit + cost_center.
        AccountingEntry.objects.create(
            category=cat,
            kind="revenue",
            amount=Decimal("1000.00"),
            competency=datetime.date(2026, 3, 1),
            unit="matriz",
            cost_center="cc-a",
        )
        AccountingEntry.objects.create(
            category=cat,
            kind="revenue",
            amount=Decimal("250.00"),
            competency=datetime.date(2026, 3, 1),
            unit="filial",
            cost_center="cc-b",
        )

        client = self._auth(self.maker_token)

        # No dimension filter → both entries counted.
        base = client.get("/api/v1/billing/accounting/entries/dre/").json()
        self.assertEqual(Decimal(base["revenue"]), Decimal("1250.00"))
        self.assertEqual(base["entries"], 2)

        # unit filter narrows to the matriz entry only.
        by_unit = client.get("/api/v1/billing/accounting/entries/dre/?unit=matriz").json()
        self.assertEqual(Decimal(by_unit["revenue"]), Decimal("1000.00"))
        self.assertEqual(by_unit["entries"], 1)

        # cost_center filter narrows to the cc-b entry only.
        by_cc = client.get("/api/v1/billing/accounting/entries/dre/?cost_center=cc-b").json()
        self.assertEqual(Decimal(by_cc["revenue"]), Decimal("250.00"))
        self.assertEqual(by_cc["entries"], 1)
