"""
apps.core.audit_partition_backfill (order 021, Emenda do Imediato).

Measured against a real Postgres database (this suite's `test_vitali`), not
mocked — the whole point of the amendment is that a fixture which builds the
condition by hand ("mede a si mesma") is exactly what let order 020 ship a
mechanism nobody on the real write path ever called. These tests reproduce
BOTH traps measured in a clean database and prove the fix for each:

1. A row sitting in a DEFAULT leaf blocks creating the partition that should
   have caught it (``IntegrityError: updated partition constraint for
   default partition ... would be violated by some row``).
2. Moving that row out is a DELETE, and the append-only trigger
   (migration 0019) blocks every DELETE — the backfill must disable it (at
   the parent, "com a tabela travada") for exactly that step, and hand
   append-only protection right back afterwards.
"""

import datetime

from django.db import connection, transaction
from django.db.utils import IntegrityError
from django.test import TestCase

from apps.core import audit_partition_backfill as backfill
from apps.core import partitioning


def _insert_into_leaf(
    leaf: str, *, resource_id: str, created_at: datetime.datetime, schema_name: str
):
    """Insert through the PARENT table (``core_auditlog``), not the named
    *leaf* directly — Postgres only applies the identity default for ``id``
    (installed on the parent, not inherited by partitions — see migration
    0043) when the INSERT targets the parent and lets routing place the row.
    *leaf* is the caller's assertion of where it expects the row to land
    given the partitions that exist at call time; it is not the SQL target.
    """
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO core_auditlog (action, resource_type, resource_id, created_at, schema_name) "
            "VALUES ('login', 'user', %s, %s, %s)",
            [resource_id, created_at, schema_name],
        )
        cur.execute(
            "SELECT tableoid::regclass::text FROM core_auditlog WHERE resource_id = %s",
            [resource_id],
        )
        actual = cur.fetchone()[0]
    assert actual == leaf, f"expected seed row to land in {leaf!r}, landed in {actual!r}"


def _tableoid_for(resource_id: str) -> str:
    with connection.cursor() as cur:
        cur.execute(
            "SELECT tableoid::regclass::text FROM core_auditlog WHERE resource_id = %s",
            [resource_id],
        )
        return cur.fetchone()[0]


class ArmadilhaOneIsRealTests(TestCase):
    """The exact failure the Imediato measured — documented so nobody has to
    rediscover it: a row in the DEFAULT for month M blocks creating M."""

    def test_ensure_month_partition_fails_while_default_holds_a_conflicting_row(self):
        month = datetime.date(2041, 3, 1)
        partitioning.ensure_default_partitions()
        _insert_into_leaf(
            "core_auditlog_default_default",
            resource_id="trap-1",
            created_at=datetime.datetime(2041, 3, 15, tzinfo=datetime.UTC),
            schema_name="acme",
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                partitioning.ensure_month_partition(month)


class BackfillMonthTests(TestCase):
    def test_moves_rows_out_of_top_level_default_into_the_months_own_default_leaf(self):
        month = datetime.date(2042, 6, 1)
        partitioning.ensure_default_partitions()
        _insert_into_leaf(
            "core_auditlog_default_default",
            resource_id="bf-month-1",
            created_at=datetime.datetime(2042, 6, 10, tzinfo=datetime.UTC),
            schema_name="acme",
        )
        self.assertEqual(_tableoid_for("bf-month-1"), "core_auditlog_default_default")

        with connection.cursor() as cur:
            result = backfill.backfill_month(cur, month)

        self.assertIsNotNone(result)
        self.assertEqual(result.row_count, 1)
        self.assertEqual(result.month, month)
        self.assertIsNone(result.schema_name)
        self.assertGreaterEqual(result.elapsed_s, 0.0)

        month_default_leaf = f"{partitioning.month_partition_name(month)}_default"
        self.assertEqual(_tableoid_for("bf-month-1"), month_default_leaf)

        # The month partition now exists and creating it again is a no-op —
        # armadilha #1 is gone for this month.
        partitioning.ensure_month_partition(month)

    def test_is_a_noop_when_nothing_is_pending(self):
        month = datetime.date(2043, 1, 1)
        with connection.cursor() as cur:
            result = backfill.backfill_month(cur, month)
        self.assertIsNone(result)

    def test_append_only_trigger_is_restored_after_the_move(self):
        month = datetime.date(2044, 8, 1)
        partitioning.ensure_default_partitions()
        _insert_into_leaf(
            "core_auditlog_default_default",
            resource_id="bf-trigger-1",
            created_at=datetime.datetime(2044, 8, 5, tzinfo=datetime.UTC),
            schema_name="acme",
        )
        with connection.cursor() as cur:
            backfill.backfill_month(cur, month)

        with self.assertRaises(Exception) as ctx:
            with transaction.atomic(), connection.cursor() as cur:
                cur.execute("DELETE FROM core_auditlog WHERE resource_id = 'bf-trigger-1'")
        self.assertIn("append-only", str(ctx.exception))


class BackfillTenantLeafTests(TestCase):
    """The second pass: out of a month's own DEFAULT, into that tenant's
    dedicated leaf — isolation proof mirrors purge's (same-month, only the
    named tenant's rows move)."""

    def test_moves_rows_into_the_dedicated_leaf_and_leaves_other_tenants_alone(self):
        month_date = datetime.date(2045, 4, 1)
        partitioning.ensure_month_partition(month_date)
        month = next(m for m in partitioning.list_month_partitions() if m.start == month_date)

        _insert_into_leaf(
            month.default_leaf,
            resource_id="bf-tenant-acme",
            created_at=datetime.datetime(2045, 4, 12, tzinfo=datetime.UTC),
            schema_name="acme",
        )
        _insert_into_leaf(
            month.default_leaf,
            resource_id="bf-tenant-beta",
            created_at=datetime.datetime(2045, 4, 12, tzinfo=datetime.UTC),
            schema_name="beta",
        )

        with connection.cursor() as cur:
            result = backfill.backfill_tenant_leaf(cur, month, "acme")

        self.assertEqual(result.row_count, 1)
        self.assertEqual(result.schema_name, "acme")

        acme_leaf = partitioning.tenant_partition_name(month.name, "acme")
        self.assertEqual(_tableoid_for("bf-tenant-acme"), acme_leaf)
        # beta was never named — stays exactly where it was, untouched.
        self.assertEqual(_tableoid_for("bf-tenant-beta"), month.default_leaf)


class PendingDiscoveryTests(TestCase):
    def test_pending_top_level_months_reports_distinct_months_and_counts(self):
        partitioning.ensure_default_partitions()
        _insert_into_leaf(
            "core_auditlog_default_default",
            resource_id="pend-1",
            created_at=datetime.datetime(2046, 2, 1, tzinfo=datetime.UTC),
            schema_name="acme",
        )
        _insert_into_leaf(
            "core_auditlog_default_default",
            resource_id="pend-2",
            created_at=datetime.datetime(2046, 2, 20, tzinfo=datetime.UTC),
            schema_name="beta",
        )
        pending = dict(backfill.pending_top_level_months())
        self.assertEqual(pending.get(datetime.date(2046, 2, 1)), 2)

    def test_pending_tenant_leaves_reports_distinct_schemas_and_counts(self):
        month_date = datetime.date(2047, 5, 1)
        partitioning.ensure_month_partition(month_date)
        month = next(m for m in partitioning.list_month_partitions() if m.start == month_date)
        _insert_into_leaf(
            month.default_leaf,
            resource_id="pend-t-1",
            created_at=datetime.datetime(2047, 5, 3, tzinfo=datetime.UTC),
            schema_name="acme",
        )
        pending = dict(backfill.pending_tenant_leaves(month))
        self.assertEqual(pending.get("acme"), 1)


class BackfillAllTests(TestCase):
    def test_dry_run_reports_without_touching_anything(self):
        partitioning.ensure_default_partitions()
        _insert_into_leaf(
            "core_auditlog_default_default",
            resource_id="all-dry-1",
            created_at=datetime.datetime(2048, 9, 9, tzinfo=datetime.UTC),
            schema_name="acme",
        )
        results = backfill.backfill_all(execute=False)
        self.assertTrue(
            any(r.row_count == 1 and r.month == datetime.date(2048, 9, 1) for r in results)
        )
        self.assertEqual(_tableoid_for("all-dry-1"), "core_auditlog_default_default")

    def test_execute_moves_everything_and_a_second_pass_is_a_noop(self):
        partitioning.ensure_default_partitions()
        _insert_into_leaf(
            "core_auditlog_default_default",
            resource_id="all-exec-1",
            created_at=datetime.datetime(2049, 11, 3, tzinfo=datetime.UTC),
            schema_name="acme",
        )
        results = backfill.backfill_all(execute=True)
        self.assertTrue(results)

        month_date = datetime.date(2049, 11, 1)
        month = next(m for m in partitioning.list_month_partitions() if m.start == month_date)
        acme_leaf = partitioning.tenant_partition_name(month.name, "acme")
        self.assertEqual(_tableoid_for("all-exec-1"), acme_leaf)

        second_pass = backfill.backfill_all(execute=True)
        self.assertEqual(second_pass, [])
