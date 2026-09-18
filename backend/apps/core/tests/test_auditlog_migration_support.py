"""
Row-parity conversion logic used by migration 0043 (order 020).

Exercises apps.core.migration_support directly against the REAL leftover
``core_auditlog_pre020`` table — migration 0043 unconditionally renames the
original flat table to that name before creating the new partitioned
``core_auditlog``, so every test database already has an (empty)
``core_auditlog_pre020`` to seed here. TestCase's per-test rollback (see
test_auditlog_immutable.py's docstring) means whatever we INSERT into it is
gone by the next test, and the append-only triggers on the LIVE table don't
apply to plain INSERTs anyway.
"""

import datetime
import uuid

from django.db import connection
from django.test import TestCase

from apps.core import migration_support


def _insert_old_row(
    cur, *, resource_id: str, created_at: datetime.datetime, schema_name: str = "acme"
):
    cur.execute(
        """
        INSERT INTO core_auditlog_pre020
            (action, resource_type, resource_id, old_data, new_data, ip_address,
             user_agent, created_at, user_id, schema_name)
        VALUES ('create', 'patient', %s, NULL, %s, NULL, '', %s, NULL, %s)
        RETURNING id
        """,
        [resource_id, '{"k": "v"}', created_at, schema_name],
    )
    return cur.fetchone()[0]


class ConvertRowParityTests(TestCase):
    def test_copy_and_verify_succeeds_for_matching_data(self):
        with connection.cursor() as cur:
            _insert_old_row(
                cur, resource_id="p1", created_at=datetime.datetime(2020, 5, 1, tzinfo=datetime.UTC)
            )
            _insert_old_row(
                cur, resource_id="p2", created_at=datetime.datetime(2020, 6, 1, tzinfo=datetime.UTC)
            )

            months = migration_support.ensure_partitions_for_existing_months(cur)
            self.assertEqual(sorted(months), ["core_auditlog_y2020m05", "core_auditlog_y2020m06"])

            migration_support.copy_rows(cur)
            row_count = migration_support.verify_row_parity(cur)
            self.assertEqual(row_count, 2)

            cur.execute("SELECT resource_id FROM core_auditlog ORDER BY resource_id")
            self.assertEqual([r[0] for r in cur.fetchall()], ["p1", "p2"])

    def test_verify_row_parity_raises_on_count_mismatch(self):
        with connection.cursor() as cur:
            _insert_old_row(
                cur, resource_id="p1", created_at=datetime.datetime(2021, 1, 1, tzinfo=datetime.UTC)
            )
            migration_support.ensure_partitions_for_existing_months(cur)
            migration_support.copy_rows(cur)
            # Sabotage: insert one more row into the OLD table after the copy,
            # so counts diverge — must be caught, not silently accepted.
            _insert_old_row(
                cur, resource_id="p2", created_at=datetime.datetime(2021, 1, 2, tzinfo=datetime.UTC)
            )
            with self.assertRaises(migration_support.ConversionError):
                migration_support.verify_row_parity(cur)

    def test_verify_row_parity_raises_on_content_mismatch_with_equal_counts(self):
        # core_auditlog blocks UPDATE (append-only trigger), so we can't
        # sabotage a copied row in place. Instead: one row in the OLD table,
        # and a DIFFERENT single row inserted directly into the NEW table
        # (never through copy_rows) — same count (1 vs 1), different
        # content. A count-only check would miss this; the EXCEPT-based
        # content diff in verify_row_parity must not.
        with connection.cursor() as cur:
            _insert_old_row(
                cur,
                resource_id="original",
                created_at=datetime.datetime(2022, 1, 1, tzinfo=datetime.UTC),
            )
            migration_support.ensure_partitions_for_existing_months(cur)
            cur.execute(
                "INSERT INTO core_auditlog "
                "(action, resource_type, resource_id, created_at, schema_name) "
                "VALUES ('create', 'patient', 'not-the-same-row', %s, 'acme')",
                [datetime.datetime(2022, 1, 1, tzinfo=datetime.UTC)],
            )
            with self.assertRaises(migration_support.ConversionError):
                migration_support.verify_row_parity(cur)

    def test_advance_identity_sequence_skips_past_migrated_ids(self):
        with connection.cursor() as cur:
            old_id = _insert_old_row(
                cur, resource_id="p1", created_at=datetime.datetime(2023, 1, 1, tzinfo=datetime.UTC)
            )
            migration_support.ensure_partitions_for_existing_months(cur)
            migration_support.copy_rows(cur)
            migration_support.verify_row_parity(cur)
            migration_support.advance_identity_sequence(cur)

            cur.execute(
                "INSERT INTO core_auditlog (action, resource_type, resource_id, created_at, schema_name) "
                "VALUES ('create', 'patient', 'new-row', now(), 'acme') RETURNING id"
            )
            new_id = cur.fetchone()[0]
            self.assertGreater(new_id, old_id)

    def test_convert_reports_row_count_and_months(self):
        with connection.cursor() as cur:
            _insert_old_row(
                cur,
                resource_id=str(uuid.uuid4()),
                created_at=datetime.datetime(2024, 8, 15, tzinfo=datetime.UTC),
            )
            report = migration_support.convert(cur)
            self.assertEqual(report["row_count"], 1)
            self.assertEqual(report["months_created"], ["core_auditlog_y2024m08"])
