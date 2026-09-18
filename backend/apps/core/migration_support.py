"""
Data-conversion helpers for migration 0043 (core_auditlog -> partitioned).

Split out of the migration file so the row-parity check — the one piece of
this conversion with real "did we lose a row" consequences — is a plain
function that a test can call directly against two ad hoc tables, without
re-running the whole migration. See apps/core/tests/test_auditlog_migration_support.py.
"""

from __future__ import annotations

import datetime

from apps.core import partitioning

OLD_TABLE = "core_auditlog_pre020"
NEW_TABLE = partitioning.TABLE

# Fixed column order shared by the SELECT (from the old table), the INSERT
# (into the new one), and the diff at the end.
COLUMNS = (
    "id",
    "action",
    "resource_type",
    "resource_id",
    "old_data",
    "new_data",
    "ip_address",
    "user_agent",
    "created_at",
    "user_id",
    "schema_name",
)


class ConversionError(Exception):
    """Raised when the old->new row count or content parity check fails.

    Deliberately fatal: this aborts the migration transaction, so a
    conversion that would silently drop or duplicate a row of the audit
    trail never commits — see the order: "perder trilha para instalar
    mecanismo de retenção seria o resultado mais absurdo possível."
    """


def ensure_partitions_for_existing_months(cursor, source_table: str = OLD_TABLE) -> list[str]:
    """Pre-create a month partition for every distinct month present in
    *source_table*'s ``created_at`` — so historical rows land in a real,
    later-purgeable month partition instead of all piling into the top-level
    DEFAULT. Returns the list of month partition names touched (for logging).
    """
    cursor.execute(f"SELECT DISTINCT date_trunc('month', created_at)::date FROM \"{source_table}\"")
    months = [row[0] for row in cursor.fetchall()]
    names = []
    for month_start in months:
        partition = partitioning.ensure_month_partition(month_start, cur=cursor)
        names.append(partition.name)
    return names


def copy_rows(cursor, *, source_table: str = OLD_TABLE, dest_table: str = NEW_TABLE) -> None:
    """INSERT every row of *source_table* into *dest_table*, preserving the
    original ``id`` values (``OVERRIDING SYSTEM VALUE`` — the destination
    column is a Postgres IDENTITY column, which otherwise refuses explicit
    values). Ordered by id so the copy is deterministic and easy to sample.
    """
    cols = ", ".join(f'"{c}"' for c in COLUMNS)
    cursor.execute(
        f'INSERT INTO "{dest_table}" ({cols}) OVERRIDING SYSTEM VALUE '
        f'SELECT {cols} FROM "{source_table}" ORDER BY id'
    )


def verify_row_parity(cursor, *, source_table: str = OLD_TABLE, dest_table: str = NEW_TABLE) -> int:
    """Raise ConversionError unless *source_table* and *dest_table* have the
    exact same row count AND identical content (full row-for-row diff via a
    symmetric EXCEPT, not just a count — a count match alone would miss a
    swapped/corrupted value). Returns the row count on success.
    """
    cursor.execute(f'SELECT count(*) FROM "{source_table}"')
    source_count = cursor.fetchone()[0]
    cursor.execute(f'SELECT count(*) FROM "{dest_table}"')
    dest_count = cursor.fetchone()[0]
    if source_count != dest_count:
        raise ConversionError(
            f"row count mismatch after copy: {source_table} has {source_count}, "
            f"{dest_table} has {dest_count} — refusing to commit the conversion"
        )

    cols = ", ".join(f'"{c}"' for c in COLUMNS)
    cursor.execute(
        f"SELECT count(*) FROM ("
        f'  (SELECT {cols} FROM "{source_table}" EXCEPT SELECT {cols} FROM "{dest_table}")'
        f"  UNION ALL"
        f'  (SELECT {cols} FROM "{dest_table}" EXCEPT SELECT {cols} FROM "{source_table}")'
        f") diff"
    )
    diff_count = cursor.fetchone()[0]
    if diff_count:
        raise ConversionError(
            f"content mismatch after copy: {diff_count} row(s) differ between "
            f"{source_table} and {dest_table} — refusing to commit the conversion"
        )
    return source_count


def advance_identity_sequence(
    cursor, *, dest_table: str = NEW_TABLE, source_table: str = OLD_TABLE
) -> None:
    """Advance dest_table.id's identity sequence past every migrated id, so
    the first new row written after conversion never collides with a
    (frozen) historical id from source_table.
    """
    cursor.execute(f'SELECT COALESCE(MAX(id), 0) FROM "{source_table}"')
    max_id = cursor.fetchone()[0]
    cursor.execute(
        "SELECT setval(pg_get_serial_sequence(%s, 'id'), %s, false)",
        [dest_table, max_id + 1],
    )


def convert(cursor) -> dict[str, object]:
    """Run the full old-table -> partitioned-table data conversion.

    Order: pre-create month partitions for the data's own date range -> copy
    rows (id preserved) -> verify parity (count + full content diff) ->
    advance the identity sequence. Returns a small report dict for logging.
    """
    months = ensure_partitions_for_existing_months(cursor)
    copy_rows(cursor)
    row_count = verify_row_parity(cursor)
    advance_identity_sequence(cursor)
    return {
        "row_count": row_count,
        "months_created": months,
        "converted_at": datetime.datetime.now(datetime.UTC).isoformat(),
    }
