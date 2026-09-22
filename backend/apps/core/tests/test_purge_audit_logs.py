"""
purge_audit_logs command (order 020, Capitão's amendment; order 021, retenção
por tenant).

Covers the limits that must be code, not documentation: factory default
retains (never purges) and NAMES why; --dry-run is the default behaviour, not
an opt-in flag; retention window is now per-tenant (TenantAuditRetention,
240 months / purge off by default) rather than a global setting; a tenant
whose window has not elapsed keeps its partition (not just "the expired one
gets dropped" — the un-expired one must be proven to SURVIVE); tenant
isolation via dedicated LIST leaves; and that DROP never runs without a
verified cold export (the negative control).
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
from apps.core.models import Tenant, TenantAuditRetention

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


def _tenant(
    schema_name: str, *, retention_months: int | None = None, purge_enabled: bool | None = None
) -> Tenant:
    """A Tenant row for *schema_name*, without paying for a real PG schema
    (auto_create_schema=False — same idiom as test_self_serve_signup.py):
    these tests only need the public-schema Tenant/TenantAuditRetention rows
    that ``purge_audit_logs`` resolves against, never the tenant's own schema.

    Pass retention_months/purge_enabled to also create a TenantAuditRetention
    row; leave both None to exercise the factory default (no row at all).
    """
    tenant = Tenant(name=schema_name, slug=schema_name)
    tenant.auto_create_schema = False
    tenant.save()
    if retention_months is not None or purge_enabled is not None:
        TenantAuditRetention.objects.create(
            tenant=tenant,
            retention_months=retention_months if retention_months is not None else 240,
            purge_enabled=purge_enabled if purge_enabled is not None else False,
        )
    return tenant


class FactoryDefaultRetainsTests(TestCase):
    """The regression nobody reviews: a default that purges. A tenant with no
    TenantAuditRetention row (the factory default, order 021) must refuse to
    purge, name why, and touch zero rows — with or without --schema.
    """

    def test_unconfigured_tenant_touches_nothing_and_names_the_reason(self):
        _tenant("acme")
        _seed_row(datetime.date(2000, 1, 15), "acme", dedicated=True)
        out = StringIO()
        call_command("purge_audit_logs", "--execute", "--schema", "acme", stdout=out)

        self.assertTrue(
            partitioning.partition_exists(
                partitioning.tenant_partition_name(
                    partitioning.month_partition_name(datetime.date(2000, 1, 15)), "acme"
                )
            )
        )
        self.assertIn("expurgo desligado", out.getvalue())
        self.assertIn("default de fábrica", out.getvalue())

    def test_sweep_across_unconfigured_tenants_touches_nothing(self):
        _tenant("acme")
        _tenant("beta")
        _seed_row(datetime.date(2000, 1, 15), "acme", dedicated=True)
        _seed_row(datetime.date(2000, 1, 15), "beta", dedicated=True)
        out = StringIO()
        call_command("purge_audit_logs", "--execute", stdout=out)

        month_name = partitioning.month_partition_name(datetime.date(2000, 1, 15))
        self.assertTrue(
            partitioning.partition_exists(partitioning.tenant_partition_name(month_name, "acme"))
        )
        self.assertTrue(
            partitioning.partition_exists(partitioning.tenant_partition_name(month_name, "beta"))
        )
        # Scoped to these two tenants by name — not a raw occurrence count,
        # which would be fragile against any other Tenant row already
        # present in the (possibly --reuse-db) test database.
        self.assertIn("acme: expurgo desligado", out.getvalue())
        self.assertIn("beta: expurgo desligado", out.getvalue())

    def test_explicit_purge_disabled_names_the_configured_reason(self):
        _tenant("acme", retention_months=30, purge_enabled=False)
        _seed_row(datetime.date(2000, 1, 15), "acme", dedicated=True)
        out = StringIO()
        call_command("purge_audit_logs", "--execute", "--schema", "acme", stdout=out)
        self.assertIn("purge_enabled=False", out.getvalue())

    def test_unknown_schema_raises(self):
        with self.assertRaises(CommandError):
            call_command("purge_audit_logs", "--schema", "does-not-exist")


@override_settings(BACKUP_ENCRYPTION_KEY=TEST_KEY)
class DryRunIsDefaultTests(TestCase):
    def setUp(self):
        self.cold_dir = _cold_dir()
        self.addCleanup(shutil.rmtree, self.cold_dir, ignore_errors=True)

    def test_dry_run_without_execute_touches_nothing(self):
        _tenant("acme", retention_months=3, purge_enabled=True)  # plenty expired vs. 2010
        with override_settings(AUDIT_LOG_COLD_STORAGE_DIR=self.cold_dir):
            _seed_row(datetime.date(2010, 1, 15), "acme", dedicated=True)  # ancient
            name = partitioning.tenant_partition_name(
                partitioning.month_partition_name(datetime.date(2010, 1, 15)), "acme"
            )

            with mock.patch.object(cold_storage, "export_and_verify_partition") as export_mock:
                out = StringIO()
                call_command("purge_audit_logs", stdout=out)  # no --execute

            export_mock.assert_not_called()
            self.assertTrue(partitioning.partition_exists(name))
            self.assertIn("dry-run", out.getvalue())
            self.assertIn("[dry-run] removeria", out.getvalue())


@override_settings(BACKUP_ENCRYPTION_KEY=TEST_KEY)
class RetentionWindowTests(TestCase):
    """O prazo é respeitado nos DOIS sentidos: partição além dos meses
    configurados sai; partição DENTRO do prazo permanece — a permanência é
    verificada, não só a remoção.
    """

    def setUp(self):
        self.cold_dir = _cold_dir()
        self.addCleanup(shutil.rmtree, self.cold_dir, ignore_errors=True)

    def test_only_the_month_outside_the_window_is_purged(self):
        _tenant("acme", retention_months=1, purge_enabled=True)
        old_date = datetime.date(2015, 3, 10)  # far outside any 1-month window
        recent_month = datetime.date.today().replace(day=1)

        _seed_row(old_date, "acme", dedicated=True)
        _seed_row(recent_month, "acme", dedicated=True)
        old_name = partitioning.tenant_partition_name(
            partitioning.month_partition_name(old_date), "acme"
        )
        recent_name = partitioning.tenant_partition_name(
            partitioning.month_partition_name(recent_month), "acme"
        )

        with override_settings(AUDIT_LOG_COLD_STORAGE_DIR=self.cold_dir):
            call_command("purge_audit_logs", "--execute")

        self.assertFalse(partitioning.partition_exists(old_name))
        self.assertTrue(partitioning.partition_exists(recent_name))
        self.assertEqual(partitioning.partition_row_count(recent_name), 1)

    def test_a_240_month_tenant_keeps_a_15_year_old_partition(self):
        """The number the order names: 240 meses. A partition well inside
        that window (15 years old) must survive an --execute run untouched.
        """
        _tenant("acme", retention_months=240, purge_enabled=True)
        fifteen_years_ago = (datetime.date.today().replace(day=1)) - datetime.timedelta(
            days=15 * 365
        )
        _seed_row(fifteen_years_ago, "acme", dedicated=True)
        name = partitioning.tenant_partition_name(
            partitioning.month_partition_name(fifteen_years_ago), "acme"
        )

        with override_settings(AUDIT_LOG_COLD_STORAGE_DIR=self.cold_dir):
            out = StringIO()
            call_command("purge_audit_logs", "--execute", "--schema", "acme", stdout=out)

        self.assertTrue(partitioning.partition_exists(name))
        self.assertEqual(partitioning.partition_row_count(name), 1)
        self.assertIn("nada além dos 240 meses", out.getvalue())


@override_settings(BACKUP_ENCRYPTION_KEY=TEST_KEY)
class TenantIsolationTests(TestCase):
    """expurgo de um tenant não toca linha de outro, mesmo no mesmo mês."""

    def setUp(self):
        self.cold_dir = _cold_dir()
        self.addCleanup(shutil.rmtree, self.cold_dir, ignore_errors=True)

    def test_schema_scoped_purge_only_drops_that_tenants_dedicated_leaf(self):
        _tenant("acme", retention_months=1, purge_enabled=True)
        _tenant("beta", retention_months=1, purge_enabled=True)
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

    def test_sweep_only_purges_the_tenant_with_purge_enabled(self):
        """Same month, same partitioning — but only ACME opted in. BETA's
        row must survive a full (no --schema) sweep untouched.
        """
        _tenant("acme", retention_months=1, purge_enabled=True)
        _tenant("beta", retention_months=1, purge_enabled=False)
        expired_date = datetime.date(2016, 6, 1)
        _seed_row(expired_date, "acme", dedicated=True)
        _seed_row(expired_date, "beta", dedicated=True)
        month_name = partitioning.month_partition_name(expired_date)
        acme_leaf = partitioning.tenant_partition_name(month_name, "acme")
        beta_leaf = partitioning.tenant_partition_name(month_name, "beta")

        with override_settings(AUDIT_LOG_COLD_STORAGE_DIR=self.cold_dir):
            call_command("purge_audit_logs", "--execute")

        self.assertFalse(partitioning.partition_exists(acme_leaf))
        self.assertTrue(partitioning.partition_exists(beta_leaf))
        self.assertEqual(partitioning.partition_row_count(beta_leaf), 1)

    def test_schema_scoped_purge_is_a_noop_without_a_dedicated_partition(self):
        _tenant("acme", retention_months=1, purge_enabled=True)
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


@override_settings(BACKUP_ENCRYPTION_KEY=TEST_KEY)
class DropRefusesWithoutProvenExportTests(TestCase):
    """Sem exportação provada, o DROP recusa — the amendment's core trap,
    unaffected by moving retention to per-tenant config.
    """

    def setUp(self):
        self.cold_dir = _cold_dir()
        self.addCleanup(shutil.rmtree, self.cold_dir, ignore_errors=True)

    def test_cold_export_failure_prevents_the_drop(self):
        _tenant("acme", retention_months=1, purge_enabled=True)
        expired_date = datetime.date(2018, 6, 1)
        _seed_row(expired_date, "acme", dedicated=True)
        name = partitioning.tenant_partition_name(
            partitioning.month_partition_name(expired_date), "acme"
        )

        with override_settings(AUDIT_LOG_COLD_STORAGE_DIR=self.cold_dir):
            with mock.patch.object(
                cold_storage,
                "export_and_verify_partition",
                side_effect=cold_storage.ColdExportError(
                    "simulated: sha256 mismatch after decrypt"
                ),
            ):
                err = StringIO()
                call_command("purge_audit_logs", "--execute", "--schema", "acme", stderr=err)

        self.assertTrue(partitioning.partition_exists(name))
        self.assertEqual(partitioning.partition_row_count(name), 1)
        self.assertIn("recusando dropar", err.getvalue())
        self.assertIn("sha256 mismatch", err.getvalue())

    def test_drop_partition_itself_refuses_a_receipt_for_another_partition(self):
        expired_date = datetime.date(2019, 6, 1)
        _seed_row(expired_date, "acme", dedicated=True)
        name = partitioning.tenant_partition_name(
            partitioning.month_partition_name(expired_date), "acme"
        )
        other_date = datetime.date(2019, 7, 1)
        partitioning.ensure_month_partition(other_date)
        other_name = partitioning.month_partition_name(other_date)

        with override_settings(AUDIT_LOG_COLD_STORAGE_DIR=self.cold_dir):
            real_receipt = cold_storage.export_and_verify_partition(other_name)
            with self.assertRaises(partitioning.PartitioningError):
                partitioning.drop_partition(name, cold_export_receipt=real_receipt)
        self.assertTrue(partitioning.partition_exists(name))


@override_settings(BACKUP_ENCRYPTION_KEY=TEST_KEY)
class SuccessfulExecuteTests(TestCase):
    def setUp(self):
        self.cold_dir = _cold_dir()
        self.addCleanup(shutil.rmtree, self.cold_dir, ignore_errors=True)

    def test_execute_drops_and_leaves_a_verifiable_cold_copy(self):
        _tenant("acme", retention_months=1, purge_enabled=True)
        expired_date = datetime.date(2012, 2, 1)
        _seed_row(expired_date, "acme", dedicated=True)
        name = partitioning.tenant_partition_name(
            partitioning.month_partition_name(expired_date), "acme"
        )

        with override_settings(AUDIT_LOG_COLD_STORAGE_DIR=self.cold_dir):
            out = StringIO()
            call_command("purge_audit_logs", "--execute", "--schema", "acme", stdout=out)

        self.assertFalse(partitioning.partition_exists(name))
        artifacts = list(Path(self.cold_dir).glob("*.jsonl.gpg"))
        manifests = list(Path(self.cold_dir).glob("*.manifest.json"))
        self.assertEqual(len(artifacts), 1)
        self.assertEqual(len(manifests), 1)
        self.assertIn("removido", out.getvalue())
