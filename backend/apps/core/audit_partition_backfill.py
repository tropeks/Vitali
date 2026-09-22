"""
Backfill: move core_auditlog rows already sitting in a DEFAULT leaf into the
real month/tenant partitions (order 021, Emenda do Imediato).

Split out of the management command (apps.core.management.commands.
backfill_audit_partitions) the same way apps.core.migration_support is split
out of migration 0043 — so the two traps the Imediato measured in a clean
database are each a plain function a test can call directly:

Armadilha #1 — the DEFAULT partition BLOCKS creating the partition that
should have caught a row. With a row in ``core_auditlog_default_default``
whose ``created_at`` falls in month M, ``ensure_month_partition(M)`` fails:
``IntegrityError: updated partition constraint for default partition
"core_auditlog_default" would be violated by some row``. The same applies one
level down: a row in month M's own DEFAULT leaf for schema S blocks
``ensure_tenant_partition(M, S)``. So the rows for a target partition must be
moved OUT of whichever DEFAULT holds them BEFORE that partition can be
created — never the other way around.

Armadilha #2 — moving a row out of a DEFAULT leaf is a DELETE against
``core_auditlog`` (even though it is immediately followed by an INSERT that
lands the row correctly), and migration 0019's append-only trigger blocks
ANY delete: ``AuditLog is append-only (CFM 1.821/2007): DELETE blocked``.
There is no way to move a row without that DELETE firing, so the trigger
must be disabled — deliberately at the PARENT table
(``core_auditlog``, not the individual leaf), because the trigger is CLONED
onto every partition by Postgres and disabling it only where the DELETE
physically happens still leaves the table's overall append-only guarantee
depending on which specific partition a row happens to live in, which is
exactly the kind of implicit invariant order 020 was written to eliminate.
Disabling at the parent, for the shortest possible window (one DDL lock +
one DELETE + one re-INSERT, batched per group, never the whole table in one
transaction) is the trade the Imediato asked to have "escrito, não
subentendido" — see docs/adr/ADR-0001-retencao-auditoria-20-anos.md for the
lock-scope discussion for a live clinic.

The move itself: rows are staged into a session-local TEMP table (exact,
id-keyed — never re-evaluating the original predicate a second time, so a row
concurrently written after staging can never be swept up by the DELETE),
deleted from the DEFAULT leaf, then re-inserted into ``core_auditlog`` proper
(preserving ``id`` via ``OVERRIDING SYSTEM VALUE``, same idiom as
``apps.core.migration_support.copy_rows``) — Postgres re-evaluates partition
routing on every INSERT, so once the right partition exists the row lands
there on its own; there is no separate "move" primitive to use here.
"""

from __future__ import annotations

import datetime
import time
from dataclasses import dataclass

from django.db import connection, transaction

from apps.core import partitioning
from apps.core.migration_support import COLUMNS

TOP_DEFAULT_LEAF = f"{partitioning.TABLE}_default_default"
APPEND_ONLY_DELETE_TRIGGER = "core_auditlog_no_delete"
_STAGING_TABLE = "_auditlog_backfill_staging"


@dataclass(frozen=True)
class BackfillResult:
    source_leaf: str
    month: datetime.date
    schema_name: str | None  # None => the top-level (all-schemas) phase for this month
    row_count: int
    elapsed_s: float


def pending_top_level_months(cur=None) -> list[tuple[datetime.date, int]]:
    """Distinct (month_start, row_count) pairs sitting in the top-level
    catch-all leaf — each one blocks ``ensure_month_partition`` for that
    month (Armadilha #1)."""
    own_cur = cur is None
    cur = cur or connection.cursor()
    try:
        if not partitioning.partition_exists(TOP_DEFAULT_LEAF, cur=cur):
            return []
        cur.execute(
            f"SELECT date_trunc('month', created_at)::date, count(*) "
            f'FROM "{TOP_DEFAULT_LEAF}" GROUP BY 1 ORDER BY 1'
        )
        return [(row[0], row[1]) for row in cur.fetchall()]
    finally:
        if own_cur:
            cur.close()


def pending_tenant_leaves(month: partitioning.MonthPartition, cur=None) -> list[tuple[str, int]]:
    """Distinct (schema_name, row_count) pairs sitting in *month*'s own
    DEFAULT leaf — each one blocks ``ensure_tenant_partition`` for that
    schema within this month (Armadilha #1, one level down)."""
    own_cur = cur is None
    cur = cur or connection.cursor()
    try:
        leaf = month.default_leaf
        if not partitioning.partition_exists(leaf, cur=cur):
            return []
        cur.execute(f'SELECT schema_name, count(*) FROM "{leaf}" GROUP BY 1 ORDER BY 1')
        return [(row[0], row[1]) for row in cur.fetchall()]
    finally:
        if own_cur:
            cur.close()


def _move_rows(cur, *, source_leaf: str, predicate_sql: str, params: list) -> int:
    """Stage the matching rows out of *source_leaf*, id-keyed, disabling the
    append-only DELETE trigger at the parent table for the DELETE only.
    Leaves the staged rows in ``_STAGING_TABLE`` for the caller to create the
    destination partition and re-insert (see backfill_month/
    backfill_tenant_leaf) — the caller, not this function, owns that
    ordering, because the destination partition MUST be created strictly
    between the DELETE and the re-INSERT (Armadilha #1).
    """
    cur.execute(f"DROP TABLE IF EXISTS {_STAGING_TABLE}")
    cur.execute(
        f'CREATE TEMP TABLE {_STAGING_TABLE} AS SELECT * FROM "{source_leaf}" WHERE {predicate_sql}',
        params,
    )
    cur.execute(f"SELECT count(*) FROM {_STAGING_TABLE}")
    moved = cur.fetchone()[0]
    if moved == 0:
        cur.execute(f"DROP TABLE {_STAGING_TABLE}")
        return 0

    cur.execute(f"ALTER TABLE {partitioning.TABLE} DISABLE TRIGGER {APPEND_ONLY_DELETE_TRIGGER}")
    try:
        cur.execute(f'DELETE FROM "{source_leaf}" WHERE id IN (SELECT id FROM {_STAGING_TABLE})')
    finally:
        cur.execute(f"ALTER TABLE {partitioning.TABLE} ENABLE TRIGGER {APPEND_ONLY_DELETE_TRIGGER}")
    return moved


def _reinsert_staged(cur) -> None:
    cols = ", ".join(f'"{c}"' for c in COLUMNS)
    cur.execute(
        f"INSERT INTO {partitioning.TABLE} ({cols}) OVERRIDING SYSTEM VALUE "
        f"SELECT {cols} FROM {_STAGING_TABLE}"
    )
    cur.execute(f"DROP TABLE {_STAGING_TABLE}")


def backfill_month(cur, month_start: datetime.date) -> BackfillResult | None:
    """Move every row for *month_start* out of the top-level DEFAULT so
    ``ensure_month_partition(month_start)`` can succeed, then re-insert —
    landing, for now, in that month's own DEFAULT leaf.
    ``backfill_tenant_leaf`` handles moving them on into dedicated tenant
    leaves in a second pass. Returns ``None`` if there was nothing to move
    (idempotent — safe to call on a month already clear of the top-level
    DEFAULT).
    """
    t0 = time.perf_counter()
    moved = _move_rows(
        cur,
        source_leaf=TOP_DEFAULT_LEAF,
        predicate_sql="date_trunc('month', created_at) = %s",
        params=[month_start],
    )
    if moved == 0:
        return None
    partitioning.ensure_month_partition(month_start, cur=cur)
    _reinsert_staged(cur)
    return BackfillResult(TOP_DEFAULT_LEAF, month_start, None, moved, time.perf_counter() - t0)


def backfill_tenant_leaf(
    cur, month: partitioning.MonthPartition, schema_name: str
) -> BackfillResult | None:
    """Move every row for *schema_name* out of *month*'s own DEFAULT leaf so
    ``ensure_tenant_partition(month.start, schema_name)`` can succeed, then
    re-insert — now landing in that dedicated leaf. Idempotent, same
    contract as ``backfill_month``.
    """
    t0 = time.perf_counter()
    leaf = month.default_leaf
    moved = _move_rows(
        cur, source_leaf=leaf, predicate_sql="schema_name = %s", params=[schema_name]
    )
    if moved == 0:
        return None
    partitioning.ensure_tenant_partition(month.start, schema_name, cur=cur)
    _reinsert_staged(cur)
    return BackfillResult(leaf, month.start, schema_name, moved, time.perf_counter() - t0)


def backfill_all(*, execute: bool) -> list[BackfillResult]:
    """Run (``execute=True``) or just report (``execute=False``) the full
    backfill: every month still stuck in the top-level DEFAULT, then every
    tenant still stuck in each of those months' own DEFAULT leaf.

    One transaction PER GROUP (one month, or one month+tenant pair) — never
    one giant transaction for the whole table. See the ADR for why: on a
    live clinic, the DISABLE TRIGGER inside ``_move_rows`` takes a lock on
    the whole partitioned table for the group's DELETE, and bounding that to
    one group at a time (with ``lock_timeout`` set) is the difference between
    a brief, bounded stall and an outage.
    """
    results: list[BackfillResult] = []

    with connection.cursor() as cur:
        top_level = pending_top_level_months(cur)

    for month_start, row_count in top_level:
        if not execute:
            results.append(BackfillResult(TOP_DEFAULT_LEAF, month_start, None, row_count, 0.0))
            continue
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute("SET LOCAL lock_timeout = '5s'")
            result = backfill_month(cur, month_start)
        if result:
            results.append(result)

    with connection.cursor() as cur:
        months = partitioning.list_month_partitions(cur=cur)

    for month in months:
        with connection.cursor() as cur:
            pending = pending_tenant_leaves(month, cur=cur)
        for schema_name, row_count in pending:
            if not execute:
                results.append(
                    BackfillResult(month.default_leaf, month.start, schema_name, row_count, 0.0)
                )
                continue
            with transaction.atomic(), connection.cursor() as cur:
                cur.execute("SET LOCAL lock_timeout = '5s'")
                result = backfill_tenant_leaf(cur, month, schema_name)
            if result:
                results.append(result)

    return results
