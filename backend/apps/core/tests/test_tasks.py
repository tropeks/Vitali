"""Core task smoke coverage."""

from django.test import SimpleTestCase

from apps.core.tasks import smoke_ping
from vitali.celery import app


class CoreTaskSmokeTest(SimpleTestCase):
    def test_smoke_ping_returns_pong(self):
        self.assertEqual(smoke_ping.run(), "pong")

    def test_waitlist_periodic_task_is_imported_by_worker(self):
        self.assertIn("apps.emr.tasks_waitlist", app.conf.imports)
