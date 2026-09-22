"""
backfill_audit_partitions command (order 021, Emenda do Imediato) — the
one-time catch-up for rows already sitting in a DEFAULT leaf when
ensure_audit_partitions starts running. --dry-run is the default, same
convention as purge_audit_logs.
"""

import datetime
from io import StringIO

from django.core.management import call_command
from django.db import connection
from django.test import TestCase

from apps.core import partitioning


def _insert_default(resource_id: str, created_at: datetime.datetime, schema_name: str):
    partitioning.ensure_default_partitions()
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO core_auditlog (action, resource_type, resource_id, created_at, schema_name) "
            "VALUES ('login', 'user', %s, %s, %s)",
            [resource_id, created_at, schema_name],
        )


class BackfillAuditPartitionsCommandTests(TestCase):
    def test_dry_run_is_the_default_and_touches_nothing(self):
        _insert_default("cmd-dry-1", datetime.datetime(2051, 3, 10, tzinfo=datetime.UTC), "acme")
        out = StringIO()
        call_command("backfill_audit_partitions", stdout=out)
        self.assertIn("[dry-run]", out.getvalue())
        self.assertIn("dry-run: nada foi tocado", out.getvalue())
        with connection.cursor() as cur:
            cur.execute(
                "SELECT tableoid::regclass::text FROM core_auditlog WHERE resource_id = 'cmd-dry-1'"
            )
            self.assertEqual(cur.fetchone()[0], "core_auditlog_default_default")

    def test_execute_moves_rows_and_reports_count_and_elapsed_time(self):
        _insert_default("cmd-exec-1", datetime.datetime(2052, 7, 4, tzinfo=datetime.UTC), "acme")
        out = StringIO()
        call_command("backfill_audit_partitions", "--execute", stdout=out)
        output = out.getvalue()
        # One originally-orphaned row, moved in TWO measured groups: out of
        # the top-level DEFAULT (all schemas for that month), then out of the
        # month's own DEFAULT into the acme-dedicated leaf.
        self.assertIn("movido 1 linha(s) de core_auditlog_default_default", output)
        self.assertIn("movido 1 linha(s) de core_auditlog_y2052m07_default", output)
        self.assertIn("total: 2 movimentação(ões) de linha movimentadas em 2 grupo(s)", output)
        self.assertRegex(output, r"em \d+\.\d{3}s")

        expected_leaf = partitioning.tenant_partition_name(
            partitioning.month_partition_name(datetime.date(2052, 7, 1)), "acme"
        )
        with connection.cursor() as cur:
            cur.execute(
                "SELECT tableoid::regclass::text FROM core_auditlog WHERE resource_id = 'cmd-exec-1'"
            )
            self.assertEqual(cur.fetchone()[0], expected_leaf)

    def test_nothing_pending_reports_and_exits_clean(self):
        out = StringIO()
        call_command("backfill_audit_partitions", stdout=out)
        self.assertIn("nada em folha DEFAULT", out.getvalue())
