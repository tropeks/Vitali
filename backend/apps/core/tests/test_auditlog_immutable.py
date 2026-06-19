"""
P1-03: AuditLog database-level immutability tests.

The AuditLog table must be immutable AT THE DATABASE LAYER, not just at the
Python/ORM layer.  QuerySet.update()/.delete() and raw SQL bypass the model's
save()/delete() overrides, so a DB-level trigger is the primary enforcement
mechanism (CFM Res. 1.821/2007).

Uses django.test.TestCase (NOT TransactionTestCase) so that each test is
wrapped in a transaction that is rolled back at the end — no TRUNCATE/flush is
ever issued, which means the immutability trigger on TRUNCATE never fires during
teardown.  This makes the suite-level behaviour identical to running the file in
isolation, eliminating the fragile _BypassTriggers / session_replication_role
hack that was needed when using TransactionTestCase.

For the individual assertions that expect a trigger error: each operation is
wrapped in ``transaction.atomic()`` which creates a savepoint.  When the trigger
raises, only the savepoint is rolled back; the outer TestCase transaction
survives and is reused by subsequent assertions.

Postgres maps the trigger's RAISE EXCEPTION (ERRCODE='check_violation') via
psycopg2 to one of IntegrityError / InternalError / ProgrammingError depending
on the execution path — we catch all three for robustness.
"""

from django.db import IntegrityError, InternalError, ProgrammingError, connection, transaction
from django.test import TestCase

from apps.core.models import AuditLog


def _make_audit_log(**kwargs):
    """Create a minimal valid AuditLog row."""
    defaults = {
        "action": "create",
        "resource_type": "patient",
        "resource_id": "test-001",
        "schema_name": "test_tenant",
    }
    defaults.update(kwargs)
    return AuditLog.objects.create(**defaults)


class AuditLogDbImmutableTests(TestCase):
    """Verify that UPDATE/DELETE on core_auditlog raise a DB-level error."""

    def _assert_trigger_blocks(self, fn):
        """
        Run *fn* inside a savepoint; assert that it raises a DB-level error.

        Postgres RAISE EXCEPTION with ERRCODE='check_violation' is mapped by
        Django/psycopg2 as follows:
          - In raw queries:  django.db.IntegrityError (check_violation -> 23514)
          - In other paths:  InternalError or ProgrammingError
        We catch all three so the assertion is robust regardless of how Django
        wraps the underlying psycopg2 error.  The transaction.atomic() context
        creates a savepoint; the exception aborts only the sub-transaction and
        rolls back to the savepoint, leaving the outer TestCase transaction
        intact for subsequent tests.
        """
        raised = False
        try:
            with transaction.atomic():
                fn()
        except (IntegrityError, InternalError, ProgrammingError):
            raised = True
        self.assertTrue(
            raised,
            "Expected a DB-level error from the immutability trigger, but no exception was raised.",
        )

    # ------------------------------------------------------------------
    # INSERT must still work
    # ------------------------------------------------------------------

    def test_insert_still_works(self):
        """Sanity-check: the trigger must NOT block INSERTs."""
        log = _make_audit_log(action="login", resource_type="user", resource_id="ins-001")
        self.assertIsNotNone(log.pk)

    # ------------------------------------------------------------------
    # UPDATE blocked
    # ------------------------------------------------------------------

    def test_db_update_raises(self):
        """QuerySet.update() must be rejected by the DB trigger."""
        log = _make_audit_log(
            action="view_record", resource_type="encounter", resource_id="upd-001"
        )
        pk = log.pk

        def do_update():
            AuditLog.objects.filter(pk=pk).update(action="tampered")

        self._assert_trigger_blocks(do_update)

    # ------------------------------------------------------------------
    # DELETE blocked
    # ------------------------------------------------------------------

    def test_db_delete_raises(self):
        """QuerySet.delete() must be rejected by the DB trigger."""
        log = _make_audit_log(action="delete", resource_type="patient", resource_id="del-001")
        pk = log.pk

        def do_delete():
            AuditLog.objects.filter(pk=pk).delete()

        self._assert_trigger_blocks(do_delete)

    # ------------------------------------------------------------------
    # Raw SQL UPDATE blocked
    # ------------------------------------------------------------------

    def test_raw_sql_update_raises(self):
        """A raw cursor UPDATE must be rejected by the DB trigger."""
        log = _make_audit_log(action="create", resource_type="prescription", resource_id="raw-001")
        pk = log.pk

        def do_raw_update():
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE core_auditlog SET action = %s WHERE id = %s",
                    ["tampered", pk],
                )

        self._assert_trigger_blocks(do_raw_update)
