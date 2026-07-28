"""
M2-S3-T3 — Laboratory delta check.

run_delta_check compares a new numeric result to the patient's most recent prior
result for the same test and raises a LabDeltaAlert when the percentage variation
exceeds the test's configured threshold.

Cases: no prior → no alert; within threshold → no alert; beyond → alert carrying
the delta; inert test (threshold NULL) → no alert; idempotent re-run.
"""

import datetime
from decimal import Decimal

from django.utils import timezone

from apps.emr.models import LabDeltaAlert, LabOrder, LabOrderItem, LabTest, Patient
from apps.emr.services.delta_check import run_delta_check
from apps.test_utils import TenantTestCase


class DeltaCheckTestCase(TenantTestCase):
    def setUp(self):
        self.patient = Patient.objects.create(
            full_name="Delta Paciente", birth_date="1985-05-05", gender="M", cpf="53333333333"
        )
        self.user = _make_user()
        self.test = LabTest.objects.create(
            code="GLUC", name="Glicose", unit="mg/dL", delta_threshold_pct=Decimal("20")
        )

    def _result(self, value, *, days_ago, test=None):
        test = test or self.test
        order = LabOrder.objects.create(patient=self.patient, requested_by=self.user)
        item = LabOrderItem.objects.create(
            order=order,
            test=test,
            test_name=test.name,
            result_value=str(value),
            resulted_at=timezone.now() - datetime.timedelta(days=days_ago),
        )
        return item

    def test_no_prior_result_no_alert(self):
        item = self._result(100, days_ago=0)
        self.assertIsNone(run_delta_check(item))
        self.assertEqual(LabDeltaAlert.objects.count(), 0)

    def test_within_threshold_no_alert(self):
        self._result(100, days_ago=10)  # prior
        current = self._result(110, days_ago=0)  # +10% ≤ 20% threshold
        self.assertIsNone(run_delta_check(current))
        self.assertEqual(LabDeltaAlert.objects.count(), 0)

    def test_beyond_threshold_raises_alert_with_delta(self):
        self._result(100, days_ago=10)  # prior
        current = self._result(150, days_ago=0)  # +50% > 20% threshold
        alert = run_delta_check(current)
        self.assertIsNotNone(alert)
        self.assertEqual(alert.previous_value, Decimal("100"))
        self.assertEqual(alert.current_value, Decimal("150"))
        self.assertEqual(alert.delta_absolute, Decimal("50"))
        self.assertEqual(alert.delta_pct, Decimal("50"))
        self.assertEqual(alert.threshold_pct, Decimal("20"))

    def test_uses_most_recent_prior(self):
        self._result(100, days_ago=30)  # older
        self._result(140, days_ago=5)  # most recent prior
        current = self._result(150, days_ago=0)  # vs 140 → ~7.1% ≤ 20% → no alert
        self.assertIsNone(run_delta_check(current))

    def test_inert_when_threshold_unset(self):
        inert_test = LabTest.objects.create(code="NA", name="Sódio", delta_threshold_pct=None)
        self._result(100, days_ago=10, test=inert_test)
        current = self._result(200, days_ago=0, test=inert_test)
        self.assertIsNone(run_delta_check(current))

    def test_non_numeric_current_value_skipped(self):
        self._result(100, days_ago=10)
        current = self._result("positivo", days_ago=0)
        self.assertIsNone(run_delta_check(current))

    def test_idempotent_rerun_does_not_duplicate(self):
        self._result(100, days_ago=10)
        current = self._result(150, days_ago=0)
        run_delta_check(current)
        run_delta_check(current)
        self.assertEqual(LabDeltaAlert.objects.filter(order_item=current).count(), 1)


def _make_user():
    from apps.core.models import Role, User

    role = Role.objects.create(name="delta_lab", permissions=["emr.read", "emr.write"])
    return User.objects.create_user(email="delta-lab@example.com", password="pw", role=role)
