"""
P1-03 — Make core_auditlog immutable at the database level.

The model already enforces append-only via save()/delete() overrides, but
QuerySet.update()/.delete() and raw SQL bypass those.  This migration installs
three Postgres triggers (BEFORE UPDATE / DELETE / TRUNCATE) that raise a
check_violation (SQLSTATE 23514) for any attempt to mutate existing rows.

The REVOKE at the end is defense-in-depth only: it is inert against the DB
owner / superuser that the app currently uses, but will become meaningful when
P3 introduces a lower-privilege application role.

CFM Res. 1.821/2007 requires an immutable electronic medical record audit trail.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0018_auditlog_schema_name_and_more"),
    ]

    operations = [
        # ── 1. Shared trigger function ────────────────────────────────────────
        migrations.RunSQL(
            sql="""
            CREATE OR REPLACE FUNCTION core_auditlog_block_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION
                    'AuditLog is append-only (CFM 1.821/2007): % blocked', TG_OP
                    USING ERRCODE = 'check_violation';
                RETURN NULL;
            END;
            $$;
            """,
            reverse_sql="""
            DROP FUNCTION IF EXISTS core_auditlog_block_mutation();
            """,
            state_operations=[],
        ),
        # ── 2. BEFORE UPDATE trigger ──────────────────────────────────────────
        migrations.RunSQL(
            sql="""
            CREATE TRIGGER core_auditlog_no_update
            BEFORE UPDATE ON core_auditlog
            FOR EACH ROW
            EXECUTE FUNCTION core_auditlog_block_mutation();
            """,
            reverse_sql="""
            DROP TRIGGER IF EXISTS core_auditlog_no_update ON core_auditlog;
            """,
            state_operations=[],
        ),
        # ── 3. BEFORE DELETE trigger ──────────────────────────────────────────
        migrations.RunSQL(
            sql="""
            CREATE TRIGGER core_auditlog_no_delete
            BEFORE DELETE ON core_auditlog
            FOR EACH ROW
            EXECUTE FUNCTION core_auditlog_block_mutation();
            """,
            reverse_sql="""
            DROP TRIGGER IF EXISTS core_auditlog_no_delete ON core_auditlog;
            """,
            state_operations=[],
        ),
        # ── 4. BEFORE TRUNCATE trigger ────────────────────────────────────────
        migrations.RunSQL(
            sql="""
            CREATE TRIGGER core_auditlog_no_truncate
            BEFORE TRUNCATE ON core_auditlog
            FOR EACH STATEMENT
            EXECUTE FUNCTION core_auditlog_block_mutation();
            """,
            reverse_sql="""
            DROP TRIGGER IF EXISTS core_auditlog_no_truncate ON core_auditlog;
            """,
            state_operations=[],
        ),
        # ── 5. REVOKE (defense-in-depth; inert against owner/superuser today) ─
        # When P3 introduces a least-privilege application role this REVOKE will
        # block mutations even without a trigger for that role.
        migrations.RunSQL(
            sql="""
            -- inert against owner/superuser today; trava roles de menor privilégio do P3
            REVOKE UPDATE, DELETE, TRUNCATE ON core_auditlog FROM PUBLIC;
            """,
            reverse_sql="""
            GRANT UPDATE, DELETE, TRUNCATE ON core_auditlog TO PUBLIC;
            """,
            state_operations=[],
        ),
    ]
