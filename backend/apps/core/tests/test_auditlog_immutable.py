"""
P1-03: AuditLog database-level immutability tests.

The AuditLog table must be immutable AT THE DATABASE LAYER, not just at the
Python/ORM layer.  QuerySet.update()/.delete() and raw SQL bypass the model's
save()/delete() overrides, so a DB-level trigger is the primary enforcement
mechanism (CFM Res. 1.821/2007).

Uses TransactionTestCase because a RAISE EXCEPTION inside a trigger aborts the
current transaction; a regular TestCase wraps everything in a single transaction
and the whole test would become unrunnable after the first trigger fires.
Each test that expects a trigger-raised exception wraps its DB call in
transaction.atomic() to create a savepoint-backed sub-transaction, lets the
exception abort only that sub-transaction, then rolls back to the savepoint —
keeping the outer connection clean for subsequent tests.

GOTCHA — TransactionTestCase teardown vs. TRUNCATE trigger:
    Django's TransactionTestCase._post_teardown calls ``manage.py flush`` which
    issues a single TRUNCATE covering all tables (including core_auditlog). Our
    TRUNCATE trigger would block that.  We work around it by temporarily setting
    the session replication role to 'replica' before the flush; that suppresses
    all user-defined triggers for the duration of the flush, then restores the
    role to 'origin'.  This is test-harness plumbing only — it has no effect on
    the production database or on the trigger's enforcement in any real session.
"""

from django.db import IntegrityError, InternalError, ProgrammingError, connection, transaction
from django.test import TransactionTestCase

from apps.core.models import AuditLog


class _BypassTriggers:
    """Context manager: set session_replication_role=replica for the duration.

    Postgres 'replica' role suppresses all user-defined triggers.  This is used
    only in the test teardown (and pre-test cleanup) so that Django's TRUNCATE
    flush can run without being blocked by the immutability trigger.  It has no
    effect on production sessions, which always run as 'origin'.
    """

    def __enter__(self):
        with connection.cursor() as cur:
            cur.execute("SET session_replication_role = replica")
        return self

    def __exit__(self, *_):
        with connection.cursor() as cur:
            cur.execute("SET session_replication_role = origin")


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


class AuditLogDbImmutableTests(TransactionTestCase):
    """Verify that UPDATE/DELETE on core_auditlog raise a DB-level error."""

    # TransactionTestCase flushes the DB between tests (no transaction wrapping).
    reset_sequences = True

    # ------------------------------------------------------------------
    # Setup/Teardown: bypass triggers so Django's flush (TRUNCATE) can run.
    #
    # Django's TransactionTestCase flushes the DB via TRUNCATE between tests.
    # Our TRUNCATE trigger blocks that.  We work around it by:
    #   1. In _pre_setup: delete any stale core_auditlog rows left over from a
    #      previous interrupted run (trigger bypassed via session_replication_role).
    #   2. In _post_teardown: set session_replication_role = replica (suppresses
    #      all user triggers), call Django's normal flush, then restore.
    # This is test-harness plumbing only; the trigger is fully active in all
    # real (non-replica-role) sessions.
    # ------------------------------------------------------------------

    @classmethod
    def _bypass_triggers(cls):
        """Return a context manager that disables user triggers for the session."""
        return _BypassTriggers()

    def setUp(self):
        # Delete any stale core_auditlog rows left from a previous run where
        # _post_teardown failed (e.g. first run with --create-db).
        with self._bypass_triggers():
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM core_auditlog")

    def _post_teardown(self):
        # Django's TransactionTestCase flushes the DB via TRUNCATE between tests.
        # Our TRUNCATE trigger would block that.  Disable user triggers for this
        # session before the flush, restore immediately after.
        # session_replication_role = replica suppresses all user-defined triggers.
        with self._bypass_triggers():
            super()._post_teardown()

    def _assert_trigger_blocks(self, fn):
        """
        Run *fn* inside a savepoint; assert that it raises a DB-level error.

        Postgres RAISE EXCEPTION with ERRCODE='check_violation' is mapped by
        Django/psycopg2 as follows:
          - In raw queries:  django.db.IntegrityError (check_violation → 23514)
          - In other paths:  InternalError or ProgrammingError
        We catch all three so the assertion is robust regardless of how Django
        wraps the underlying psycopg2 error.  The transaction.atomic() context
        creates a savepoint; the exception aborts only the sub-transaction and
        rolls back to the savepoint, leaving the outer connection usable.
        """
        raised = False
        try:
            with transaction.atomic():
                fn()
        except (IntegrityError, InternalError, ProgrammingError):
            raised = True
        self.assertTrue(
            raised,
            "Expected a DB-level error from the immutability trigger, but no "
            "exception was raised.",
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
        log = _make_audit_log(action="view_record", resource_type="encounter", resource_id="upd-001")
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
