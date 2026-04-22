"""
Tests for AI Celery tasks — S-038 check_tuss_staleness.

Run: python manage.py test apps.ai.tests.test_tasks
"""

import logging
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.ai.tasks import check_tuss_staleness
from apps.core.models import TUSSSyncLog


class CheckTUSSStatenessTests(TestCase):
    """Tests for check_tuss_staleness task (public schema, TestCase)."""

    def _make_sync(self, days_ago: int, status: str = "success"):
        obj = TUSSSyncLog.objects.create(
            source=TUSSSyncLog.Source.MANAGEMENT_COMMAND,
            status=status,
            row_count_total=5000,
            row_count_added=0,
        )
        ran_at = timezone.now() - timedelta(days=days_ago)
        TUSSSyncLog.objects.filter(pk=obj.pk).update(ran_at=ran_at)
        return obj

    def test_fresh_sync_no_log(self):
        """Sync < 14 days old: no warning/info logged, status='fresh'."""
        self._make_sync(days_ago=5)
        with self.assertLogs("apps.ai.tasks", level="DEBUG") as cm:
            # Inject a dummy DEBUG so assertLogs doesn't raise if no logs emitted
            logging.getLogger("apps.ai.tasks").debug("probe")
            result = check_tuss_staleness()
        self.assertEqual(result["status"], "fresh")
        # Must NOT have a WARNING or INFO about staleness/ageing
        for record in cm.output:
            self.assertNotIn("stale", record)
            self.assertNotIn("ageing", record)

    def test_ageing_sync_logs_info(self):
        """Sync 14–29 days old: logs INFO about ageing."""
        self._make_sync(days_ago=20)
        with self.assertLogs("apps.ai.tasks", level="INFO") as cm:
            result = check_tuss_staleness()
        self.assertEqual(result["status"], "ageing")
        self.assertTrue(any("ageing" in line for line in cm.output))

    def test_stale_sync_logs_warning(self):
        """Sync ≥ 30 days old: logs WARNING about staleness."""
        self._make_sync(days_ago=35)
        with self.assertLogs("apps.ai.tasks", level="WARNING") as cm:
            result = check_tuss_staleness()
        self.assertEqual(result["status"], "stale")
        self.assertTrue(any("stale" in line for line in cm.output))

    def test_no_syncs_ever_logs_warning(self):
        """No TUSSSyncLog rows at all: logs WARNING."""
        # Ensure table is clean
        TUSSSyncLog.objects.all().delete()
        with self.assertLogs("apps.ai.tasks", level="WARNING") as cm:
            result = check_tuss_staleness()
        self.assertEqual(result["status"], "stale")
        self.assertIsNone(result["last_sync"])
        self.assertTrue(any("stale" in line for line in cm.output))

    def test_failed_sync_not_counted(self):
        """Only status='success' syncs count; a failed sync should not prevent staleness log."""
        TUSSSyncLog.objects.all().delete()
        self._make_sync(days_ago=2, status="error")
        with self.assertLogs("apps.ai.tasks", level="WARNING"):
            result = check_tuss_staleness()
        # No successful sync → stale
        self.assertEqual(result["status"], "stale")

    def test_db_error_does_not_raise(self):
        """Any DB exception must be caught; task returns error dict, never raises."""
        with patch(
            "apps.core.models.TUSSSyncLog.objects.using",
            side_effect=Exception("DB down"),
        ):
            try:
                result = check_tuss_staleness()
            except Exception as exc:
                self.fail(f"check_tuss_staleness raised an exception: {exc}")
        self.assertEqual(result["status"], "error")
