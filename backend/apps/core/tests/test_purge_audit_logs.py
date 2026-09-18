"""
purge_audit_logs command (order 020, Capitão's amendment).

Covers the three limits that must be code, not documentation: factory
default retains (never purges) and NAMES why; --dry-run is the default
behaviour, not an opt-in flag; and both settings are required together,
naming whichever is missing. Plus: fixed-clock retention window, per-tenant
isolation via --schema, and that DROP never runs without a verified cold
export (the negative control).
"""

import datetime
import shutil
import tempfile
from io import StringIO
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase, override_settings

from apps.core import cold_storage, partitioning

TEST_KEY = "order-020-purge-test-passphrase"


def _cold_dir():
    d = tempfile.mkdtemp(prefix="auditlog-purge-test-")
    return d


def _seed_row(for_date: datetime.date, schema_name: str, *, dedicated: bool = False):
    if dedicated:
        partitioning.ensure_tenant_partition(for_date, schema_name)
    else:
        partitioning.ensure_month_partition(for_date)
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO core_auditlog (action, resource_type, resource_id, created_at, schema_name) "
            "VALUES ('login', 'user', '1', %s, %s)",
            [
                datetime.datetime(for_date.year, for_date.month, for_date.day, tzinfo=datetime.UTC),
                schema_name,
            ],
        )


class FactoryDefaultRetainsTests(TestCase):
    """The regression nobody reviews: a default that purges. Both settings
    are unset out of the box (see vitali/settings/base.py) — the command
    must refuse, name what's missing, and touch zero rows.
    """

    def test_refuses_with_no_settings_configured_and_names_both(self):
        _seed_row(datetime.date(2000, 1, 15), "acme")
        out, err = StringIO(), StringIO()
        with self.assertRaises(CommandError) as ctx:
            call_command("purge_audit_logs", stdout=out, stderr=err)
        message = str(ctx.exception)
        self.assertIn("AUDIT_LOG_PURGE_ENABLED", message)
        self.assertIn("AUDIT_LOG_RETENTION_DAYS", message)
        self.assertTrue(
            partitioning.partition_exists(
                partitioning.month_partition_name(datetime.date(2000, 1, 15))
            )
        )

    @override_settings(AUDIT_LOG_PURGE_ENABLED=True, AUDIT_LOG_RETENTION_DAYS=None)
    def test_refuses_naming_only_retention_days_when_purge_enabled_alone(self):
        with self.assertRaises(CommandError) as ctx:
            call_command("purge_audit_logs")
        self.assertIn("AUDIT_LOG_RETENTION_DAYS", str(ctx.exception))
        self.assertNotIn("AUDIT_LOG_PURGE_ENABLED", str(ctx.exception))

    @override_settings(AUDIT_LOG_PURGE_ENABLED=False, AUDIT_LOG_RETENTION_DAYS=30)
    def test_refuses_naming_only_purge_enabled_when_retention_alone(self):
        with self.assertRaises(CommandError) as ctx:
            call_command("purge_audit_logs")
        self.assertIn("AUDIT_LOG_PURGE_ENABLED", str(ctx.exception))
        self.assertNotIn("AUDIT_LOG_RETENTION_DAYS", str(ctx.exception))


@override_settings(
    AUDIT_LOG_PURGE_ENABLED=True, AUDIT_LOG_RETENTION_DAYS=90, BACKUP_ENCRYPTION_KEY=TEST_KEY
)
class DryRunIsDefaultTests(TestCase):
    def setUp(self):
        self.cold_dir = _cold_dir()
        self.addCleanup(shutil.rmtree, self.cold_dir, ignore_errors=True)

    def test_dry_run_without_execute_touches_nothing(self):
        with override_settings(AUDIT_LOG_COLD_STORAGE_DIR=self.cold_dir):
            _seed_row(datetime.date(2010, 1, 15), "acme")  # ancient — well past 90 days
            name = partitioning.month_partition_name(datetime.date(2010, 1, 15))

            with mock.patch.object(cold_storage, "export_and_verify_partition") as export_mock:
                out = StringIO()
                call_command("purge_audit_logs", stdout=out)

            export_mock.assert_not_called()
            self.assertTrue(partitioning.partition_exists(name))
            self.assertIn("dry-run", out.getvalue())


@override_settings(
    AUDIT_LOG_PURGE_ENABLED=True, AUDIT_LOG_RETENTION_DAYS=30, BACKUP_ENCRYPTION_KEY=TEST_KEY
)
class FixedClockWindowTests(TestCase):
    def setUp(self):
        self.cold_dir = _cold_dir()
        self.addCleanup(shutil.rmtree, self.cold_dir, ignore_errors=True)

    def test_only_rows_outside_the_window_are_purged(self):
        old_date = datetime.date(2015, 3, 10)  # far outside any 30-day window
        recent_month = datetime.date.today().replace(day=1)

        _seed_row(old_date, "acme")
        _seed_row(recent_month, "acme")
        old_name = partitioning.month_partition_name(old_date)
        recent_name = partitioning.month_partition_name(recent_month)

        with override_settings(AUDIT_LOG_COLD_STORAGE_DIR=self.cold_dir):
            call_command("purge_audit_logs", "--execute")

        self.assertFalse(partitioning.partition_exists(old_name))
        self.assertTrue(partitioning.partition_exists(recent_name))
        self.assertEqual(partitioning.partition_row_count(recent_name), 1)


@override_settings(
    AUDIT_LOG_PURGE_ENABLED=True, AUDIT_LOG_RETENTION_DAYS=30, BACKUP_ENCRYPTION_KEY=TEST_KEY
)
class TenantIsolationTests(TestCase):
    """expurgo de um tenant não toca linha de outro."""

    def setUp(self):
        self.cold_dir = _cold_dir()
        self.addCleanup(shutil.rmtree, self.cold_dir, ignore_errors=True)

    def test_schema_scoped_purge_only_drops_that_tenants_dedicated_leaf(self):
        expired_date = datetime.date(2016, 6, 1)
        _seed_row(expired_date, "acme", dedicated=True)
        _seed_row(expired_date, "beta", dedicated=True)
        month_name = partitioning.month_partition_name(expired_date)
        acme_leaf = partitioning.tenant_partition_name(month_name, "acme")
        beta_leaf = partitioning.tenant_partition_name(month_name, "beta")

        with override_settings(AUDIT_LOG_COLD_STORAGE_DIR=self.cold_dir):
            call_command("purge_audit_logs", "--execute", "--schema", "acme")

        self.assertFalse(partitioning.partition_exists(acme_leaf))
        self.assertTrue(partitioning.partition_exists(beta_leaf))
        self.assertEqual(partitioning.partition_row_count(beta_leaf), 1)

    def test_schema_scoped_purge_is_a_noop_without_a_dedicated_partition(self):
        expired_date = datetime.date(2017, 6, 1)
        _seed_row(expired_date, "acme", dedicated=False)  # lands in the month DEFAULT leaf
        month_name = partitioning.month_partition_name(expired_date)
        default_leaf = f"{month_name}_default"

        with override_settings(AUDIT_LOG_COLD_STORAGE_DIR=self.cold_dir):
            out = StringIO()
            call_command("purge_audit_logs", "--execute", "--schema", "acme", stdout=out)

        self.assertTrue(partitioning.partition_exists(default_leaf))
        self.assertEqual(partitioning.partition_row_count(default_leaf), 1)
        self.assertIn("sem partição dedicada", out.getvalue())


@override_settings(
    AUDIT_LOG_PURGE_ENABLED=True, AUDIT_LOG_RETENTION_DAYS=30, BACKUP_ENCRYPTION_KEY=TEST_KEY
)
class DropRefusesWithoutProvenExportTests(TestCase):
    """Sem exportação provada, o DROP recusa — the amendment's core trap."""

    def setUp(self):
        self.cold_dir = _cold_dir()
        self.addCleanup(shutil.rmtree, self.cold_dir, ignore_errors=True)

    def test_cold_export_failure_prevents_the_drop(self):
        expired_date = datetime.date(2018, 6, 1)
        _seed_row(expired_date, "acme")
        name = partitioning.month_partition_name(expired_date)

        with override_settings(AUDIT_LOG_COLD_STORAGE_DIR=self.cold_dir):
            with mock.patch.object(
                cold_storage,
                "export_and_verify_partition",
                side_effect=cold_storage.ColdExportError(
                    "simulated: sha256 mismatch after decrypt"
                ),
            ):
                err = StringIO()
                call_command("purge_audit_logs", "--execute", stderr=err)

        self.assertTrue(partitioning.partition_exists(name))
        self.assertEqual(partitioning.partition_row_count(name), 1)
        self.assertIn("recusando dropar", err.getvalue())
        self.assertIn("sha256 mismatch", err.getvalue())

    def test_drop_partition_itself_refuses_a_receipt_for_another_partition(self):
        expired_date = datetime.date(2019, 6, 1)
        _seed_row(expired_date, "acme")
        name = partitioning.month_partition_name(expired_date)
        other_date = datetime.date(2019, 7, 1)
        partitioning.ensure_month_partition(other_date)
        other_name = partitioning.month_partition_name(other_date)

        with override_settings(AUDIT_LOG_COLD_STORAGE_DIR=self.cold_dir):
            real_receipt = cold_storage.export_and_verify_partition(other_name)
            with self.assertRaises(partitioning.PartitioningError):
                partitioning.drop_partition(name, cold_export_receipt=real_receipt)
        self.assertTrue(partitioning.partition_exists(name))


@override_settings(
    AUDIT_LOG_PURGE_ENABLED=True, AUDIT_LOG_RETENTION_DAYS=30, BACKUP_ENCRYPTION_KEY=TEST_KEY
)
class SuccessfulExecuteTests(TestCase):
    def setUp(self):
        self.cold_dir = _cold_dir()
        self.addCleanup(shutil.rmtree, self.cold_dir, ignore_errors=True)

    def test_execute_drops_and_leaves_a_verifiable_cold_copy(self):
        expired_date = datetime.date(2012, 2, 1)
        _seed_row(expired_date, "acme")
        name = partitioning.month_partition_name(expired_date)

        with override_settings(AUDIT_LOG_COLD_STORAGE_DIR=self.cold_dir):
            out = StringIO()
            call_command("purge_audit_logs", "--execute", stdout=out)

        self.assertFalse(partitioning.partition_exists(name))
        artifacts = list(Path(self.cold_dir).glob("*.jsonl.gpg"))
        manifests = list(Path(self.cold_dir).glob("*.manifest.json"))
        self.assertEqual(len(artifacts), 1)
        self.assertEqual(len(manifests), 1)
        self.assertIn("removido", out.getvalue())
