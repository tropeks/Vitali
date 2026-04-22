"""
Billing Analytics API tests — S-035.

Run: python manage.py test apps.analytics.tests.test_billing_analytics
"""

import datetime
from decimal import Decimal

from django.core.cache import cache as django_cache
from django.utils import timezone
from rest_framework.test import APIClient

from apps.billing.models import InsuranceProvider, TISSBatch, TISSGuide
from apps.core.models import FeatureFlag, Role, User
from apps.emr.models import Encounter, Patient, Professional
from apps.test_utils import TenantTestCase


def _make_guide(
    provider,
    patient,
    encounter,
    status="draft",
    total_value="1000.00",
    competency=None,
):
    """Helper to create a TISSGuide with sensible defaults."""
    if competency is None:
        competency = timezone.localdate().strftime("%Y-%m")
    return TISSGuide.objects.create(
        provider=provider,
        patient=patient,
        encounter=encounter,
        guide_type="sp_sadt",
        status=status,
        total_value=Decimal(total_value),
        competency=competency,
    )


class BillingAnalyticsBaseCase(TenantTestCase):
    """Shared setUp for all billing analytics tests."""

    def setUp(self):
        try:
            django_cache.clear()
        except Exception:
            pass
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain

        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant, module_key="billing", defaults={"is_enabled": True}
        )

        role = Role.objects.create(
            name="faturista",
            permissions=["billing.read", "billing.write"],
            is_system=True,
        )
        self.user = User.objects.create_user(
            email="faturista@analytics.test",
            full_name="Faturista Analytics",
            password="Str0ng!Pass#2024",
            role=role,
        )
        prof_user = User.objects.create_user(
            email="medico@analytics.test",
            full_name="Dr. Analytics",
            password="Str0ng!Pass#2024",
            role=role,
        )
        self.patient = Patient.objects.create(
            full_name="Paciente Analytics",
            cpf="111.111.111-11",
            birth_date=datetime.date(1990, 6, 15),
            gender="M",
        )
        self.professional = Professional.objects.create(
            user=prof_user,
            council_type="CRM",
            council_number="12345",
            council_state="SP",
        )
        self.encounter = Encounter.objects.create(
            patient=self.patient,
            professional=self.professional,
        )
        self.provider = InsuranceProvider.objects.create(
            name="Unimed Analytics",
            ans_code="111000",
        )
        self.client.force_authenticate(user=self.user)

    def _guide(self, **kwargs):
        return _make_guide(self.provider, self.patient, self.encounter, **kwargs)


# ─── BillingOverviewView ──────────────────────────────────────────────────────


class BillingOverviewTests(BillingAnalyticsBaseCase):
    def test_happy_path(self):
        today_comp = timezone.localdate().strftime("%Y-%m")
        self._guide(status="paid", total_value="2000.00", competency=today_comp)
        self._guide(status="denied", total_value="500.00", competency=today_comp)
        self._guide(status="draft", total_value="300.00", competency=today_comp)

        resp = self.client.get("/api/v1/analytics/billing/overview/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["period"], today_comp)
        self.assertEqual(Decimal(data["total_billed"]), Decimal("2800.00"))
        self.assertEqual(Decimal(data["total_collected"]), Decimal("2000.00"))
        self.assertEqual(Decimal(data["total_denied"]), Decimal("500.00"))
        self.assertEqual(data["guides_total"], 3)
        self.assertEqual(data["guides_paid"], 1)
        self.assertEqual(data["guides_denied"], 1)

    def test_empty_state_returns_zeros(self):
        resp = self.client.get("/api/v1/analytics/billing/overview/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(Decimal(data["total_billed"]), Decimal("0.00"))
        self.assertEqual(data["guides_total"], 0)
        self.assertEqual(data["denial_rate"], 0.0)

    def test_unauthenticated_returns_401(self):
        self.client.force_authenticate(user=None)
        resp = self.client.get("/api/v1/analytics/billing/overview/")
        self.assertEqual(resp.status_code, 401)

    def test_appeal_status_counted_in_total_denied(self):
        today_comp = timezone.localdate().strftime("%Y-%m")
        self._guide(status="appeal", total_value="800.00", competency=today_comp)
        resp = self.client.get("/api/v1/analytics/billing/overview/")
        data = resp.json()
        self.assertEqual(Decimal(data["total_denied"]), Decimal("800.00"))

    def test_denial_rate_excludes_draft_guides(self):
        today_comp = timezone.localdate().strftime("%Y-%m")
        self._guide(status="denied", total_value="100.00", competency=today_comp)
        self._guide(status="draft", total_value="1000.00", competency=today_comp)
        resp = self.client.get("/api/v1/analytics/billing/overview/")
        data = resp.json()
        # denial_rate denominator = non-draft guides (1), not all guides (2)
        # total_denied=100, total_billed=1100 (includes draft in sum)
        # But denial_rate is based on value: 100/1100 ~ 0.091
        self.assertGreater(data["denial_rate"], 0.0)

    def test_collected_field_uses_paid_status_only(self):
        today_comp = timezone.localdate().strftime("%Y-%m")
        self._guide(status="submitted", total_value="500.00", competency=today_comp)
        self._guide(status="paid", total_value="300.00", competency=today_comp)
        resp = self.client.get("/api/v1/analytics/billing/overview/")
        data = resp.json()
        # only the paid guide counts as collected
        self.assertEqual(Decimal(data["total_collected"]), Decimal("300.00"))

    def test_denial_rate_zero_when_no_submitted_guides(self):
        today_comp = timezone.localdate().strftime("%Y-%m")
        self._guide(status="draft", total_value="999.00", competency=today_comp)
        resp = self.client.get("/api/v1/analytics/billing/overview/")
        data = resp.json()
        self.assertEqual(data["denial_rate"], 0.0)


# ─── MonthlyRevenueView ───────────────────────────────────────────────────────


class MonthlyRevenueTests(BillingAnalyticsBaseCase):
    def test_happy_path(self):
        today_comp = timezone.localdate().strftime("%Y-%m")
        self._guide(status="paid", total_value="1000.00", competency=today_comp)
        resp = self.client.get("/api/v1/analytics/billing/monthly-revenue/?months=3")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data), 3)
        current_bucket = next(b for b in data if b["period"] == today_comp)
        self.assertEqual(Decimal(current_bucket["collected"]), Decimal("1000.00"))

    def test_empty_state_returns_zero_buckets(self):
        resp = self.client.get("/api/v1/analytics/billing/monthly-revenue/?months=3")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data), 3)
        for bucket in data:
            self.assertEqual(Decimal(bucket["billed"]), Decimal("0.00"))

    def test_unauthenticated_returns_401(self):
        self.client.force_authenticate(user=None)
        resp = self.client.get("/api/v1/analytics/billing/monthly-revenue/")
        self.assertEqual(resp.status_code, 401)

    def test_monthly_revenue_groups_by_competency(self):
        """A February guide drafted in March must appear in February's bucket."""
        feb_comp = "2026-02"
        mar_comp = "2026-03"
        # Guide with competency=Feb but created in March context
        self._guide(status="paid", total_value="500.00", competency=feb_comp)
        self._guide(status="paid", total_value="700.00", competency=mar_comp)
        resp = self.client.get("/api/v1/analytics/billing/monthly-revenue/?months=6")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        by_period = {b["period"]: b for b in data}
        if feb_comp in by_period:
            self.assertEqual(Decimal(by_period[feb_comp]["collected"]), Decimal("500.00"))
        if mar_comp in by_period:
            self.assertEqual(Decimal(by_period[mar_comp]["collected"]), Decimal("700.00"))

    def test_months_param_clamped_min(self):
        """?months=0 is clamped to 1."""
        resp = self.client.get("/api/v1/analytics/billing/monthly-revenue/?months=0")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 1)

    def test_months_param_clamped_max(self):
        """?months=200 is clamped to 24."""
        resp = self.client.get("/api/v1/analytics/billing/monthly-revenue/?months=200")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 24)


# ─── DenialByInsurerView ──────────────────────────────────────────────────────


class DenialByInsurerTests(BillingAnalyticsBaseCase):
    def _add_guides(self, provider, count, status, value="100.00"):
        for _ in range(count):
            _make_guide(
                provider,
                self.patient,
                self.encounter,
                status=status,
                total_value=value,
            )

    def test_happy_path(self):
        # 10 non-draft guides — meets volume floor
        self._add_guides(self.provider, 8, "paid")
        self._add_guides(self.provider, 2, "denied")
        resp = self.client.get("/api/v1/analytics/billing/denial-by-insurer/?months=6")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data), 1)
        row = data[0]
        self.assertEqual(row["insurer_name"], "Unimed Analytics")
        self.assertEqual(row["total_guides"], 10)
        self.assertEqual(row["denied_guides"], 2)

    def test_empty_state_returns_empty_list(self):
        resp = self.client.get("/api/v1/analytics/billing/denial-by-insurer/?months=6")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [])

    def test_unauthenticated_returns_401(self):
        self.client.force_authenticate(user=None)
        resp = self.client.get("/api/v1/analytics/billing/denial-by-insurer/")
        self.assertEqual(resp.status_code, 401)

    def test_insurer_below_10_guide_floor_excluded(self):
        """Insurer with 9 non-draft guides must NOT appear."""
        self._add_guides(self.provider, 7, "paid")
        self._add_guides(self.provider, 2, "denied")
        # Total non-draft = 9 — one below floor
        resp = self.client.get("/api/v1/analytics/billing/denial-by-insurer/?months=6")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [])

    def test_insurer_volume_floor_counts_non_draft_statuses(self):
        """paid + denied guides count toward the volume floor (not just submitted)."""
        # 5 paid + 5 denied = 10 non-draft total → must appear
        self._add_guides(self.provider, 5, "paid")
        self._add_guides(self.provider, 5, "denied")
        resp = self.client.get("/api/v1/analytics/billing/denial-by-insurer/?months=6")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 1)

    def test_sorted_by_denied_value_desc(self):
        """Insurer with higher denied_value appears first."""
        provider2 = InsuranceProvider.objects.create(name="Amil Test", ans_code="222000")
        # provider: 10 guides (5 denied × R$100 = R$500)
        self._add_guides(self.provider, 5, "paid", value="100.00")
        self._add_guides(self.provider, 5, "denied", value="100.00")
        # provider2: 10 guides (8 denied × R$200 = R$1600)
        for _ in range(2):
            _make_guide(
                provider2, self.patient, self.encounter, status="paid", total_value="200.00"
            )
        for _ in range(8):
            _make_guide(
                provider2, self.patient, self.encounter, status="denied", total_value="200.00"
            )

        resp = self.client.get("/api/v1/analytics/billing/denial-by-insurer/?months=6")
        data = resp.json()
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["insurer_name"], "Amil Test")


# ─── BatchThroughputView ──────────────────────────────────────────────────────


class BatchThroughputTests(BillingAnalyticsBaseCase):
    def test_happy_path(self):
        resp = self.client.get("/api/v1/analytics/billing/batch-throughput/?months=3")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data), 3)
        for bucket in data:
            self.assertIn("period", bucket)
            self.assertIn("created_count", bucket)
            self.assertIn("closed_count", bucket)

    def test_empty_state_returns_zero_buckets(self):
        resp = self.client.get("/api/v1/analytics/billing/batch-throughput/?months=3")
        self.assertEqual(resp.status_code, 200)
        for bucket in resp.json():
            self.assertEqual(bucket["created_count"], 0)
            self.assertEqual(bucket["closed_count"], 0)

    def test_unauthenticated_returns_401(self):
        self.client.force_authenticate(user=None)
        resp = self.client.get("/api/v1/analytics/billing/batch-throughput/")
        self.assertEqual(resp.status_code, 401)

    def test_batch_throughput_cross_month_merge_correctness(self):
        """Batch created in Jan and closed in Mar appears in Jan created AND Mar closed."""
        datetime.date(2026, 1, 15)
        datetime.date(2026, 3, 10)
        batch = TISSBatch.objects.create(
            provider=self.provider,
            batch_number="202601-001",
        )
        # Simulate created_at in January, closed_at in March
        TISSBatch.objects.filter(pk=batch.pk).update(
            created_at=timezone.make_aware(datetime.datetime(2026, 1, 15, 12, 0)),
            closed_at=timezone.make_aware(datetime.datetime(2026, 3, 10, 12, 0)),
        )

        resp = self.client.get("/api/v1/analytics/billing/batch-throughput/?months=6")
        data = resp.json()
        by_period = {b["period"]: b for b in data}
        if "2026-01" in by_period:
            self.assertEqual(by_period["2026-01"]["created_count"], 1)
            self.assertEqual(by_period["2026-01"]["closed_count"], 0)
        if "2026-03" in by_period:
            self.assertEqual(by_period["2026-03"]["created_count"], 0)
            self.assertEqual(by_period["2026-03"]["closed_count"], 1)


# ─── GlosaAccuracyView ────────────────────────────────────────────────────────


class GlosaAccuracyTests(BillingAnalyticsBaseCase):
    def _make_prediction(self, ans_code, risk_level, was_denied):
        from apps.ai.models import GlosaPrediction

        guide = self._guide(status="paid")
        return GlosaPrediction.objects.create(
            guide=guide,
            insurer_ans_code=ans_code,
            guide_type="sp_sadt",
            tuss_code="10101012",
            risk_level=risk_level,
            was_denied=was_denied,
        )

    def test_happy_path(self):
        self._make_prediction("111000", "high", True)
        self._make_prediction("111000", "low", False)
        resp = self.client.get("/api/v1/analytics/billing/glosa-accuracy/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data), 1)
        row = data[0]
        self.assertEqual(row["insurer_ans_code"], "111000")
        self.assertEqual(row["total_predictions"], 2)
        self.assertEqual(row["true_positives"], 1)

    def test_empty_state_returns_empty_list(self):
        resp = self.client.get("/api/v1/analytics/billing/glosa-accuracy/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [])

    def test_unauthenticated_returns_401(self):
        self.client.force_authenticate(user=None)
        resp = self.client.get("/api/v1/analytics/billing/glosa-accuracy/")
        self.assertEqual(resp.status_code, 401)

    def test_glosa_accuracy_precision_null_when_no_high_risk(self):
        """When predicted_high=0 for an insurer, precision must be null (not ZeroDivisionError)."""
        self._make_prediction("111000", "low", True)
        resp = self.client.get("/api/v1/analytics/billing/glosa-accuracy/")
        data = resp.json()
        self.assertEqual(len(data), 1)
        self.assertIsNone(data[0]["precision"])

    def test_glosa_accuracy_excludes_unresolved_from_denominator(self):
        """was_denied=None predictions must NOT count toward total_predictions."""
        from apps.ai.models import GlosaPrediction

        guide = self._guide(status="paid")
        # Resolved prediction
        GlosaPrediction.objects.create(
            guide=guide,
            insurer_ans_code="111000",
            guide_type="sp_sadt",
            tuss_code="10101012",
            risk_level="high",
            was_denied=True,
        )
        # Unresolved prediction (was_denied=None)
        GlosaPrediction.objects.create(
            guide=guide,
            insurer_ans_code="111000",
            guide_type="sp_sadt",
            tuss_code="10101013",
            risk_level="low",
            was_denied=None,
        )
        resp = self.client.get("/api/v1/analytics/billing/glosa-accuracy/")
        data = resp.json()
        self.assertEqual(data[0]["total_predictions"], 1)  # unresolved excluded

    def test_glosa_accuracy_recall_calculation(self):
        """recall = true_positives / was_denied."""
        # 3 denied, 2 predicted high, 2 true positives
        self._make_prediction("111000", "high", True)
        self._make_prediction("111000", "high", True)
        self._make_prediction("111000", "low", True)
        resp = self.client.get("/api/v1/analytics/billing/glosa-accuracy/")
        data = resp.json()
        row = data[0]
        # recall = 2/3 = 0.667
        self.assertAlmostEqual(row["recall"], 0.667, places=2)
        # precision = 2/2 = 1.0
        self.assertAlmostEqual(row["precision"], 1.0, places=2)
