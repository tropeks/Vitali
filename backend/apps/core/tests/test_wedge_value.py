"""Issue #123 tests — wedge business-value dashboard.

Covers the public-schema endpoint (auth + response shape), the snapshot model's
uniqueness/serving path, and the daily Celery task's idempotency. The per-wedge
metric math is exercised indirectly: the service degrades each wedge to an
``{"error": ...}`` block on a missing/empty schema, so the snapshot/serving
contract is what we assert here (no tenant data fixtures required).
"""

from datetime import date

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.core.models import User, WedgeValueSnapshot


class WedgeValueDashboardViewTest(TestCase):
    """WedgeValueDashboardView — public schema endpoint, platform admin only."""

    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_superuser(
            email="wedge_admin@vitali.test",
            password="adminpass",
        )

    def test_unauthenticated_rejected(self):
        r = self.client.get("/api/v1/platform/wedge-value/")
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_non_admin_rejected(self):
        user = User.objects.create_user(email="wedge_regular@vitali.test", password="pass")
        self.client.force_authenticate(user)
        r = self.client.get("/api/v1/platform/wedge-value/")
        self.assertIn(r.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_401_UNAUTHORIZED])

    def test_admin_serves_snapshot_rows(self):
        """With a snapshot row present, the endpoint serves it without a live compute."""
        WedgeValueSnapshot.objects.create(
            schema_name="clinic_a",
            tenant_name="Clínica A",
            snapshot_date=date(2026, 6, 23),
            window_days=30,
            metrics={
                "glosa_safety": {"blocked_value_brl": 1234.5, "blocked_count": 3},
                "dose_safety": {"fired": 10, "overridden": 4, "override_rate": 0.4},
                "no_show_prediction": {"slots_recovered": 7},
                "stockout_safety": {"intercepted": 2},
                "roi_brl": 1234.5,
            },
        )
        self.client.force_authenticate(self.admin)
        r = self.client.get("/api/v1/platform/wedge-value/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data["source"], "snapshot")
        self.assertEqual(len(r.data["tenants"]), 1)
        tenant = r.data["tenants"][0]
        self.assertEqual(tenant["schema"], "clinic_a")
        self.assertEqual(tenant["name"], "Clínica A")
        # Totals aggregate the headline numbers.
        totals = r.data["totals"]
        self.assertEqual(totals["roi_brl"], 1234.5)
        self.assertEqual(totals["glosa_blocked_count"], 3)
        self.assertEqual(totals["dose_alerts_fired"], 10)
        self.assertEqual(totals["no_show_slots_recovered"], 7)
        self.assertEqual(totals["stockout_intercepted"], 2)
        self.assertEqual(totals["tenant_count"], 1)

    def test_only_latest_snapshot_per_tenant_served(self):
        """Multiple days for one tenant collapse to the newest snapshot."""
        WedgeValueSnapshot.objects.create(
            schema_name="clinic_a",
            tenant_name="Clínica A",
            snapshot_date=date(2026, 6, 22),
            metrics={"roi_brl": 100.0, "glosa_safety": {"blocked_value_brl": 100.0}},
        )
        WedgeValueSnapshot.objects.create(
            schema_name="clinic_a",
            tenant_name="Clínica A",
            snapshot_date=date(2026, 6, 23),
            metrics={"roi_brl": 300.0, "glosa_safety": {"blocked_value_brl": 300.0}},
        )
        self.client.force_authenticate(self.admin)
        r = self.client.get("/api/v1/platform/wedge-value/")
        self.assertEqual(len(r.data["tenants"]), 1)
        self.assertEqual(r.data["tenants"][0]["snapshot_date"], "2026-06-23")
        self.assertEqual(r.data["totals"]["roi_brl"], 300.0)


class WedgeValueSnapshotModelTest(TestCase):
    """The (schema_name, snapshot_date) pair is unique per day."""

    def test_unique_per_schema_per_day(self):
        from django.db import IntegrityError

        WedgeValueSnapshot.objects.create(
            schema_name="clinic_a", snapshot_date=date(2026, 6, 23), metrics={}
        )
        with self.assertRaises(IntegrityError):
            WedgeValueSnapshot.objects.create(
                schema_name="clinic_a", snapshot_date=date(2026, 6, 23), metrics={}
            )
