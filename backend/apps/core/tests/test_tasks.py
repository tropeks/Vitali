"""Core task smoke coverage."""

import datetime

from django.test import SimpleTestCase, TestCase

from apps.core import partitioning
from apps.core.models import Tenant
from apps.core.tasks import ensure_audit_partitions, smoke_ping
from vitali.celery import app


class CoreTaskSmokeTest(SimpleTestCase):
    def test_smoke_ping_returns_pong(self):
        self.assertEqual(smoke_ping.run(), "pong")

    def test_waitlist_periodic_task_is_imported_by_worker(self):
        self.assertIn("apps.emr.tasks_waitlist", app.conf.imports)


class EnsureAuditPartitionsTaskTests(TestCase):
    """Order 021, Emenda do Imediato — the daily Celery Beat half of the real
    call path (the other half is the boot-time call in
    scripts/migrate_schemas.sh). A thin call_command wrapper; run for real
    against the test database rather than mocked, since the whole point of
    the amendment is that a mock can't fail the way a forgotten call does.
    """

    def test_run_creates_the_current_months_dedicated_leaf_for_every_tenant(self):
        tenant = Tenant(name="Beat Clinic", slug="beat-clinic")
        tenant.auto_create_schema = False
        tenant.save()

        ensure_audit_partitions.run()

        leaf = partitioning.tenant_partition_name(
            partitioning.month_partition_name(datetime.date.today()), tenant.schema_name
        )
        self.assertTrue(partitioning.partition_exists(leaf))
