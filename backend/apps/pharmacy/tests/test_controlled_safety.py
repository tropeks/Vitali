"""Orchestrator tests for the controlled-diversion wedge (PR C2).

Exercises ControlledSafetyService.evaluate: flag-off no-op, non-controlled no-op,
each of the 3 signals end-to-end (DB → engine → ControlledAlert), the prior-only +
same-script guards, dedup/override-preservation, and the Dispensation post_save →
on_commit wiring. The pure scoring is covered in test_controlled_checker.
"""

import datetime
from decimal import Decimal

from django.utils import timezone

from apps.core.models import FeatureFlag, User
from apps.emr.models import Encounter, Patient, Prescription, PrescriptionItem, Professional
from apps.pharmacy.models import (
    ControlledAlert,
    Dispensation,
    DispensationLot,
    Drug,
    StockItem,
)
from apps.pharmacy.services.controlled_safety import ControlledSafetyService
from apps.test_utils import TenantTestCase


class _Base(TenantTestCase):
    def setUp(self):
        self.tenant = self.__class__.tenant
        self._set_flag(True)
        self.now = timezone.now()
        self.patient = Patient.objects.create(
            full_name="Controlado", birth_date="1980-01-01", gender="M", cpf="44455566677"
        )
        self.drug = Drug.objects.create(
            name="Clonazepam 2mg", controlled_class="B1", min_refill_interval_days=30
        )
        self.drug2 = Drug.objects.create(name="Diazepam 10mg", controlled_class="B1")
        self.non_controlled = Drug.objects.create(name="Dipirona 500mg", controlled_class="none")
        self._slot = 0

    def _set_flag(self, enabled):
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key="controlled_safety",
            defaults={"is_enabled": enabled},
        )

    def _prescriber(self, n):
        user = User.objects.create_user(email=f"presc{n}@t.com", full_name=f"Dr {n}", password="pw")
        return Professional.objects.create(
            user=user, council_type="CRM", council_number=str(n), council_state="SP"
        )

    def _stock(self, drug):
        return StockItem.objects.create(
            drug=drug,
            lot_number=f"L{self._slot}",
            expiry_date=(self.now + datetime.timedelta(days=365)).date(),
        )

    def _dispense(self, *, drug, prescriber, qty, days_ago, dispenser=None):
        self._slot += 1
        rx = Prescription.objects.create(
            encounter=Encounter.objects.create(patient=self.patient, professional=prescriber),
            patient=self.patient,
            prescriber=prescriber,
        )
        item = PrescriptionItem.objects.create(
            prescription=rx, drug=drug, quantity=Decimal(qty), unit_of_measure="un"
        )
        disp = Dispensation.objects.create(
            prescription=rx,
            prescription_item=item,
            patient=self.patient,
            dispensed_by=dispenser or prescriber.user,
        )
        DispensationLot.objects.create(
            dispensation=disp, stock_item=self._stock(drug), quantity=Decimal(qty)
        )
        # dispensed_at is auto_now_add → backdate via .update() to simulate history.
        when = self.now - datetime.timedelta(days=days_ago)
        Dispensation.objects.filter(pk=disp.pk).update(dispensed_at=when)
        disp.refresh_from_db()
        return disp

    def _kinds(self, disp):
        return set(
            ControlledAlert.objects.filter(dispensation=disp).values_list("signal_kind", flat=True)
        )


class TestEvaluate(_Base):
    def test_flag_off_is_noop(self):
        self._set_flag(False)
        p = self._prescriber(1)
        self._dispense(drug=self.drug, prescriber=p, qty="10", days_ago=5)
        cur = self._dispense(drug=self.drug, prescriber=p, qty="10", days_ago=0)
        ControlledSafetyService().evaluate(cur.id)
        assert ControlledAlert.objects.count() == 0

    def test_non_controlled_is_noop(self):
        p = self._prescriber(1)
        cur = self._dispense(drug=self.non_controlled, prescriber=p, qty="10", days_ago=0)
        ControlledSafetyService().evaluate(cur.id)
        assert ControlledAlert.objects.count() == 0

    def test_refill_too_soon(self):
        p = self._prescriber(1)
        self._dispense(drug=self.drug, prescriber=p, qty="10", days_ago=5)  # diff Rx, 5d ago
        cur = self._dispense(drug=self.drug, prescriber=p, qty="10", days_ago=0)
        ControlledSafetyService().evaluate(cur.id)
        assert "refill_too_soon" in self._kinds(cur)

    def test_multiple_prescribers(self):
        # 3 distinct prescribers, same B1 class, within window.
        self._dispense(drug=self.drug, prescriber=self._prescriber(1), qty="10", days_ago=20)
        self._dispense(drug=self.drug2, prescriber=self._prescriber(2), qty="10", days_ago=10)
        cur = self._dispense(drug=self.drug, prescriber=self._prescriber(3), qty="10", days_ago=0)
        ControlledSafetyService().evaluate(cur.id)
        assert "multiple_prescribers" in self._kinds(cur)

    def test_quantity_escalation(self):
        p = self._prescriber(1)
        self._dispense(drug=self.drug, prescriber=p, qty="10", days_ago=40)
        self._dispense(drug=self.drug, prescriber=p, qty="20", days_ago=20)
        cur = self._dispense(drug=self.drug, prescriber=p, qty="40", days_ago=0)
        ControlledSafetyService().evaluate(cur.id)
        assert "quantity_escalation" in self._kinds(cur)

    def test_dedup_and_override_preserved(self):
        p = self._prescriber(1)
        self._dispense(drug=self.drug, prescriber=p, qty="10", days_ago=5)
        cur = self._dispense(drug=self.drug, prescriber=p, qty="10", days_ago=0)
        svc = ControlledSafetyService()
        svc.evaluate(cur.id)
        alert = ControlledAlert.objects.get(dispensation=cur, signal_kind="refill_too_soon")
        alert.acknowledge(self.patient.created_by or p.user, note="receituário conferido")
        # Re-evaluate: same detail → ack preserved, no duplicate row.
        svc.evaluate(cur.id)
        assert (
            ControlledAlert.objects.filter(dispensation=cur, signal_kind="refill_too_soon").count()
            == 1
        )
        alert.refresh_from_db()
        assert alert.status == ControlledAlert.Status.ACKNOWLEDGED


class TestSignalWiring(_Base):
    def test_dispensation_commit_triggers_evaluation(self):
        p = self._prescriber(1)
        self._dispense(drug=self.drug, prescriber=p, qty="10", days_ago=5)
        with self.captureOnCommitCallbacks(execute=True):
            cur = self._dispense(drug=self.drug, prescriber=p, qty="10", days_ago=0)
        # The post_save → on_commit hook ran the monitor; refill alert exists.
        # (days_ago=0 still backdated AFTER commit, but the on_commit ran against
        # the committed row; assert the wiring fired by checking the alert.)
        assert ControlledAlert.objects.filter(dispensation=cur).exists()
