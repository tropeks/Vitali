"""
Tests for TUSSSyncLog model and TUSSSyncStatusView (S-032).
"""

from django.test import TestCase
from rest_framework.test import APIClient

from apps.core.models import Role, TUSSSyncLog, User

SYNC_STATUS_URL = "/api/v1/ai/tuss-sync-status/"


def _make_admin():
    role, _ = Role.objects.get_or_create(
        name="admin_sync",
        defaults={"permissions": ["users.read", "billing.full", "ai.use"]},
    )
    return User.objects.create_user(email="admin_sync@test.com", password="pw", role=role)


class TUSSSyncLogModelTest(TestCase):
    """Basic model-level tests — uses public schema (TestCase, not TenantTestCase)."""

    def test_create_sync_log(self):
        log = TUSSSyncLog.objects.create(
            source=TUSSSyncLog.Source.MANAGEMENT_COMMAND,
            row_count_total=5000,
            row_count_added=50,
            row_count_updated=200,
            status=TUSSSyncLog.Status.SUCCESS,
            duration_ms=1200,
        )
        self.assertEqual(log.status, "success")
        self.assertEqual(log.row_count_total, 5000)
        self.assertIsNotNone(log.ran_at)

    def test_error_message_stored(self):
        log = TUSSSyncLog.objects.create(
            status=TUSSSyncLog.Status.ERROR,
            error_message="Connection refused",
        )
        self.assertEqual(log.error_message, "Connection refused")

    def test_ordering_newest_first(self):
        for _i in range(3):
            TUSSSyncLog.objects.create(status=TUSSSyncLog.Status.SUCCESS)
        logs = list(TUSSSyncLog.objects.all())
        # Default ordering is -ran_at; IDs increase so first should be newest
        self.assertGreaterEqual(logs[0].ran_at, logs[-1].ran_at)


class TUSSSyncStatusViewTest(TestCase):
    """GET /api/v1/ai/tuss-sync-status/ — requires users.read."""

    def setUp(self):
        # This view lives in apps.core and is served from the public schema
        self.client = APIClient()
        self.user = _make_admin()
        self.client.force_authenticate(user=self.user)
        TUSSSyncLog.objects.all().delete()

    def test_returns_last_5_syncs(self):
        for i in range(7):
            TUSSSyncLog.objects.create(status=TUSSSyncLog.Status.SUCCESS, row_count_total=i * 100)

        resp = self.client.get(SYNC_STATUS_URL)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data["last_syncs"]), 5)

    def test_returns_empty_when_no_syncs(self):
        resp = self.client.get(SYNC_STATUS_URL)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["last_syncs"], [])
        self.assertIsNone(resp.data["last_sync_age_days"])

    def test_unauthenticated_returns_401(self):
        self.client.logout()
        resp = self.client.get(SYNC_STATUS_URL)
        self.assertIn(resp.status_code, [401, 403])

    def test_table_row_count_present(self):
        TUSSSyncLog.objects.create(status=TUSSSyncLog.Status.SUCCESS, row_count_total=3000)
        resp = self.client.get(SYNC_STATUS_URL)
        self.assertIn("table_row_count", resp.data)
