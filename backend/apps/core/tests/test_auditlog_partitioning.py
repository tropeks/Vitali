"""
Partition mechanics for core_auditlog (order 020).

Uses django.test.TestCase (transaction-wrapped, rolled back — see
test_auditlog_immutable.py's module docstring for why that matters with the
TRUNCATE-blocking trigger) so DDL created here (partitions, temp tables)
never survives past the test, and never fights the append-only triggers.
"""

import datetime

from django.db import connection
from django.test import TestCase
from django_tenants.utils import schema_context

from apps.core import partitioning
from apps.core.models import AuditLog, Tenant


class MonthPartitionNamingTests(TestCase):
    def test_name_is_deterministic_by_month(self):
        name = partitioning.month_partition_name(datetime.date(2027, 1, 15))
        self.assertEqual(name, "core_auditlog_y2027m01")

    def test_tenant_leaf_name_folds_unsafe_characters(self):
        leaf = partitioning.tenant_partition_name("core_auditlog_y2027m01", "clinic-A.beta")
        self.assertTrue(leaf.startswith("core_auditlog_y2027m01_t_"))
        self.assertNotIn("-", leaf)
        self.assertNotIn(".", leaf)


class MonthPartitionExpiryTests(TestCase):
    def test_is_expired_true_once_month_fully_past_cutoff(self):
        partition = partitioning.MonthPartition(
            name="core_auditlog_y2025m03",
            year=2025,
            month=3,
            start=datetime.date(2025, 3, 1),
            end=datetime.date(2025, 4, 1),
        )
        self.assertTrue(partition.is_expired(datetime.datetime(2030, 1, 1)))
        self.assertFalse(partition.is_expired(datetime.datetime(2020, 1, 1)))
        # Exactly on the boundary (upper bound is exclusive of the partition
        # itself, but is the earliest instant it is safe to consider gone).
        self.assertTrue(partition.is_expired(datetime.datetime(2025, 4, 1)))
        self.assertFalse(partition.is_expired(datetime.datetime(2025, 3, 31, 23, 59, 59)))


class EnsurePartitionIdempotencyTests(TestCase):
    def test_ensure_month_partition_twice_is_not_an_error(self):
        for_date = datetime.date(2031, 6, 10)
        first = partitioning.ensure_month_partition(for_date)
        second = partitioning.ensure_month_partition(for_date)
        self.assertEqual(first.name, second.name)
        self.assertTrue(partitioning.partition_exists(first.name))
        self.assertTrue(partitioning.partition_exists(first.default_leaf))

    def test_ensure_tenant_partition_twice_is_not_an_error(self):
        for_date = datetime.date(2031, 7, 10)
        leaf1 = partitioning.ensure_tenant_partition(for_date, "acme")
        leaf2 = partitioning.ensure_tenant_partition(for_date, "acme")
        self.assertEqual(leaf1, leaf2)
        self.assertTrue(partitioning.partition_exists(leaf1))

    def test_tenant_partition_isolated_from_default_leaf(self):
        for_date = datetime.date(2031, 8, 5)
        leaf = partitioning.ensure_tenant_partition(for_date, "acme")

        with connection.cursor() as cur:
            cur.execute(
                "INSERT INTO core_auditlog (action, resource_type, resource_id, "
                "created_at, schema_name) VALUES (%s,%s,%s,%s,%s)",
                ["login", "user", "1", datetime.datetime(2031, 8, 3, tzinfo=datetime.UTC), "acme"],
            )
            cur.execute(
                "INSERT INTO core_auditlog (action, resource_type, resource_id, "
                "created_at, schema_name) VALUES (%s,%s,%s,%s,%s)",
                ["login", "user", "2", datetime.datetime(2031, 8, 3, tzinfo=datetime.UTC), "other"],
            )
            cur.execute(
                "SELECT tableoid::regclass::text FROM core_auditlog WHERE resource_id = '1'"
            )
            acme_table = cur.fetchone()[0]
            cur.execute(
                "SELECT tableoid::regclass::text FROM core_auditlog WHERE resource_id = '2'"
            )
            other_table = cur.fetchone()[0]

        self.assertEqual(acme_table, leaf)
        self.assertNotEqual(other_table, leaf)


class RealOrmWriteLandsInDedicatedLeafTests(TestCase):
    """Order 021, Emenda do Imediato: the proof that matters. Every other test
    in this module seeds rows with a hand-crafted ``cursor.execute(INSERT
    ...)`` — legitimate for testing the partitioning primitives themselves,
    but exactly the kind of fixture that "mede a si mesma" if used to prove
    the END-TO-END mechanism works, because it can never fail the way a
    forgotten ``ensure_tenant_partition`` call fails. This test writes
    through the ORM (``AuditLog.objects.create`` — no explicit
    ``schema_name=`` kwarg, so the model's own ``save()`` stamps it from
    ``connection.schema_name``, the exact mechanism every real call site
    uses) and asserts via ``tableoid::regclass`` where it actually landed.
    """

    def test_orm_create_lands_in_the_tenant_dedicated_leaf_not_default(self):
        tenant = Tenant(name="Leaf Proof Clinic", slug="leaf-proof-clinic")
        tenant.auto_create_schema = False
        tenant.save()

        today = datetime.date.today()
        partitioning.ensure_tenant_partition(today, tenant.schema_name)
        expected_leaf = partitioning.tenant_partition_name(
            partitioning.month_partition_name(today), tenant.schema_name
        )

        with schema_context(tenant.schema_name):
            log = AuditLog.objects.create(
                action="login", resource_type="user", resource_id="orm-proof-1"
            )
            self.assertEqual(log.schema_name, tenant.schema_name)

        with connection.cursor() as cur:
            cur.execute(
                "SELECT tableoid::regclass::text FROM core_auditlog WHERE id = %s",
                [log.id],
            )
            actual_leaf = cur.fetchone()[0]

        self.assertEqual(actual_leaf, expected_leaf)
        self.assertNotEqual(actual_leaf, "core_auditlog_default_default")
        self.assertNotEqual(actual_leaf, f"{partitioning.month_partition_name(today)}_default")

    def test_orm_create_without_a_dedicated_partition_still_falls_through_to_default(self):
        # The inverse control: same ORM write path, no ensure_tenant_partition
        # call this time — must land in DEFAULT, never be rejected (the
        # order-020 invariant this whole mechanism must never violate).
        tenant = Tenant(name="No Partition Clinic", slug="no-partition-clinic")
        tenant.auto_create_schema = False
        tenant.save()

        with schema_context(tenant.schema_name):
            log = AuditLog.objects.create(
                action="login", resource_type="user", resource_id="orm-proof-2"
            )

        with connection.cursor() as cur:
            cur.execute(
                "SELECT tableoid::regclass::text FROM core_auditlog WHERE id = %s",
                [log.id],
            )
            actual_leaf = cur.fetchone()[0]

        self.assertIn("default", actual_leaf)


class ListMonthPartitionsTests(TestCase):
    def test_discovers_created_months_sorted(self):
        partitioning.ensure_month_partition(datetime.date(2032, 3, 1))
        partitioning.ensure_month_partition(datetime.date(2032, 1, 1))
        months = [m for m in partitioning.list_month_partitions() if m.year == 2032]
        self.assertEqual([m.month for m in months], [1, 3])


class DefaultPartitionAcceptsAnythingTests(TestCase):
    """The DEFAULT partition (both levels) must accept rows that match no
    explicit month/tenant partition — a row must never be rejected for lack
    of a partition (order 020's central invariant).
    """

    def test_ordinary_create_lands_in_default_leaf_when_no_month_partition_exists(self):
        # A fresh test database only has the top-level DEFAULT scaffold
        # (migration 0043 creates no month partitions when there is no
        # historical data) — so *any* plain .create() call, for "now", must
        # fall through DEFAULT -> DEFAULT rather than being rejected.
        log = AuditLog.objects.create(action="login", resource_type="user", resource_id="default-1")
        with connection.cursor() as cur:
            cur.execute(
                "SELECT tableoid::regclass::text FROM core_auditlog WHERE id = %s AND created_at = %s",
                [log.id, log.created_at],
            )
            table = cur.fetchone()[0]
        self.assertEqual(table, "core_auditlog_default_default")

    def test_insert_far_outside_any_month_partition_is_accepted(self):
        partitioning.ensure_month_partition(datetime.date(2033, 5, 1))
        with connection.cursor() as cur:
            cur.execute(
                "INSERT INTO core_auditlog (action, resource_type, resource_id, "
                "created_at, schema_name) VALUES (%s,%s,%s,%s,%s) RETURNING tableoid::regclass::text",
                [
                    "login",
                    "user",
                    "far-future",
                    datetime.datetime(2099, 1, 1, tzinfo=datetime.UTC),
                    "acme",
                ],
            )
            table = cur.fetchone()[0]
        self.assertEqual(table, "core_auditlog_default_default")


class DropPartitionRequiresReceiptTests(TestCase):
    def test_refuses_without_any_receipt(self):
        partitioning.ensure_month_partition(datetime.date(2034, 2, 1))
        name = partitioning.month_partition_name(datetime.date(2034, 2, 1))
        with self.assertRaises(partitioning.PartitioningError):
            partitioning.drop_partition(name, cold_export_receipt=None)
        self.assertTrue(partitioning.partition_exists(name))

    def test_refuses_receipt_for_a_different_partition(self):
        from apps.core.cold_storage import ColdExportReceipt

        partitioning.ensure_month_partition(datetime.date(2034, 3, 1))
        name = partitioning.month_partition_name(datetime.date(2034, 3, 1))
        wrong_receipt = ColdExportReceipt(
            partition_name="some_other_partition",
            verified=True,
            manifest={},
            stored_location="/dev/null",
        )
        with self.assertRaises(partitioning.PartitioningError):
            partitioning.drop_partition(name, cold_export_receipt=wrong_receipt)
        self.assertTrue(partitioning.partition_exists(name))

    def test_refuses_unverified_receipt(self):
        from apps.core.cold_storage import ColdExportReceipt

        partitioning.ensure_month_partition(datetime.date(2034, 4, 1))
        name = partitioning.month_partition_name(datetime.date(2034, 4, 1))
        unverified = ColdExportReceipt(
            partition_name=name, verified=False, manifest={}, stored_location="/dev/null"
        )
        with self.assertRaises(partitioning.PartitioningError):
            partitioning.drop_partition(name, cold_export_receipt=unverified)
        self.assertTrue(partitioning.partition_exists(name))
