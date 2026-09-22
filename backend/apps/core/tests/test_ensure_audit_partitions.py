"""
ensure_audit_partitions command (order 021, Emenda do Imediato).

This is the piece that makes the retention window non-decorative: called on
the real path (entrypoint after migrate — scripts/migrate_schemas.sh /
docs/DEPLOY.md — and a daily Celery Beat task), it pre-creates the current
and next month's dedicated leaf for every tenant, and alerts if any row is
still landing in a DEFAULT leaf (which, once this runs on schedule, means a
partition is missing, not normal operation).
"""

import datetime
from io import StringIO

from django.core.management import call_command
from django.db import connection
from django.test import TestCase

from apps.core import partitioning
from apps.core.models import AuditLog, Tenant


def _tenant(schema_name: str) -> Tenant:
    tenant = Tenant(name=schema_name, slug=schema_name)
    tenant.auto_create_schema = False
    tenant.save()
    return tenant


class EnsureAuditPartitionsTests(TestCase):
    def test_creates_current_and_next_month_leaf_for_every_tenant(self):
        _tenant("acme")
        _tenant("beta")

        out = StringIO()
        call_command("ensure_audit_partitions", stdout=out)

        today = datetime.date.today()
        next_month = (
            datetime.date(today.year + 1, 1, 1)
            if today.month == 12
            else datetime.date(today.year, today.month + 1, 1)
        )
        for schema in ("acme", "beta"):
            for month_date in (today, next_month):
                leaf = partitioning.tenant_partition_name(
                    partitioning.month_partition_name(month_date), schema
                )
                self.assertTrue(partitioning.partition_exists(leaf), f"missing {leaf}")

        self.assertIn("partições garantidas", out.getvalue())

    def test_is_idempotent(self):
        _tenant("acme")
        call_command("ensure_audit_partitions")
        # Second call must not raise (CREATE ... IF NOT EXISTS underneath).
        call_command("ensure_audit_partitions")

    def test_alerts_when_a_row_is_in_a_default_leaf(self):
        partitioning.ensure_default_partitions()
        with connection.cursor() as cur:
            cur.execute(
                "INSERT INTO core_auditlog (action, resource_type, resource_id, created_at, schema_name) "
                "VALUES ('login', 'user', 'ensure-alarm-1', %s, %s)",
                [datetime.datetime(2050, 1, 15, tzinfo=datetime.UTC), "orphan-tenant"],
            )
        out = StringIO()
        call_command("ensure_audit_partitions", stdout=out)
        self.assertIn("ALERTA", out.getvalue())
        self.assertIn("core_auditlog_default_default", out.getvalue())

    def test_no_alarm_on_a_clean_install(self):
        out = StringIO()
        call_command("ensure_audit_partitions", stdout=out)
        self.assertIn("nenhuma linha em folha DEFAULT", out.getvalue())

    def test_a_real_orm_write_after_running_lands_in_the_dedicated_leaf(self):
        """Closes the loop: run the command, then write through the ORM (no
        explicit schema_name=) exactly like a real request would, and prove
        it lands in the leaf the command just created — not DEFAULT.
        """
        from django_tenants.utils import schema_context

        tenant = _tenant("realwrite")
        call_command("ensure_audit_partitions")

        with schema_context(tenant.schema_name):
            log = AuditLog.objects.create(
                action="login", resource_type="user", resource_id="ensure-real-write-1"
            )

        today = datetime.date.today()
        expected_leaf = partitioning.tenant_partition_name(
            partitioning.month_partition_name(today), tenant.schema_name
        )
        with connection.cursor() as cur:
            cur.execute(
                "SELECT tableoid::regclass::text FROM core_auditlog WHERE id = %s", [log.id]
            )
            self.assertEqual(cur.fetchone()[0], expected_leaf)
