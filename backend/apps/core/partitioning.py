"""
Partition maintenance for ``core_auditlog`` (order 020).

``core_auditlog`` is RANGE-partitioned by month on ``created_at``; every month
partition is itself LIST-partitioned by ``schema_name``. Both levels carry a
``DEFAULT`` partition, so a row is NEVER rejected for lack of a matching
partition — if ``AuditLog.save()`` raised because no partition existed, the
read/write it was auditing would already have happened, and losing the trail
is worse than any storage cost (see the order).

Everything here is idempotent: creating a partition that already exists is
not an error (Postgres 11+ supports ``CREATE TABLE IF NOT EXISTS ... PARTITION
OF``). Nothing here is wired to a scheduler — see the order's "no migration
schedules a periodic task" constraint; a Celery beat entry or cron is a
follow-up decision for whoever owns that call, not this module.

Naming convention (deterministic, so discovery never needs to parse Postgres'
partition-bound catalog entries):
    core_auditlog_y2026m09              -- month RANGE partition (Sep/2026)
    core_auditlog_y2026m09_default      -- that month's LIST DEFAULT leaf
    core_auditlog_y2026m09_t_<schema>   -- that month's dedicated tenant leaf
    core_auditlog_default               -- top-level RANGE DEFAULT
    core_auditlog_default_default       -- top-level DEFAULT's LIST DEFAULT leaf
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, datetime

from django.db import connection
from django.utils import timezone
from psycopg2 import sql

TABLE = "core_auditlog"
PUBLIC_TABLE = sql.Identifier("public", TABLE)

_MONTH_NAME_RE = re.compile(r"^core_auditlog_y(\d{4})m(\d{2})$")
# Postgres identifiers are case-folded/limited to 63 bytes; schema_name is
# already constrained to that by django-tenants, but a tenant leaf name adds a
# prefix, so we defensively fold anything not [a-z0-9_] rather than trust the
# caller.
_UNSAFE_IDENT_CHARS = re.compile(r"[^a-z0-9_]")


class PartitioningError(Exception):
    """Raised for any partition operation that cannot be completed safely."""


@dataclass(frozen=True)
class MonthPartition:
    """A month RANGE partition of core_auditlog."""

    name: str
    year: int
    month: int
    start: date
    end: date  # exclusive upper bound (first day of the following month)

    @property
    def default_leaf(self) -> str:
        return f"{self.name}_default"

    def is_expired(self, cutoff: datetime) -> bool:
        """True when every possible row in this partition is older than cutoff.

        The partition's own upper bound (exclusive) is the latest instant it
        can hold, so this is only true once that bound is at/before the
        cutoff — never based on the partition's *contents*, which would
        require a scan. Postgres stores ``created_at`` (timestamptz) as UTC
        internally and Django (USE_TZ=True) pins the connection to UTC, so
        comparing naive UTC datetimes here matches what the partition bounds
        actually mean on disk.
        """
        cutoff_naive = cutoff.replace(tzinfo=None) if cutoff.tzinfo else cutoff
        return datetime.combine(self.end, datetime.min.time()) <= cutoff_naive


def retention_cutoff(now: datetime, retention_months: int) -> datetime:
    """*now* minus *retention_months* whole calendar months.

    Order 021: retention is counted in MONTHS, matching the unit of the
    thing actually being expurgated (a month RANGE partition — see
    ``MonthPartition``), not days. A day count drifts against month
    boundaries by a day across leap years (20 years is 7305 or 7306 days
    depending which Februaries fall inside the window); subtracting whole
    months has no such wobble. Deliberately no ``dateutil`` dependency for a
    one-off month subtraction the stdlib already covers via
    ``calendar.monthrange``.
    """
    total_months = now.year * 12 + (now.month - 1) - retention_months
    year, month0 = divmod(total_months, 12)
    month = month0 + 1
    day = min(now.day, calendar.monthrange(year, month)[1])
    return now.replace(year=year, month=month, day=day)


def _month_bounds(for_date: date) -> tuple[date, date]:
    start = for_date.replace(day=1)
    end = date(start.year + 1, 1, 1) if start.month == 12 else date(start.year, start.month + 1, 1)
    return start, end


def month_partition_name(for_date: date) -> str:
    start, _ = _month_bounds(for_date)
    return f"{TABLE}_y{start.year:04d}m{start.month:02d}"


def month_starts(count: int, *, today: date | None = None) -> list[date]:
    """The first day of *today*'s month, plus the next *count - 1* months.

    Shared by ``ensure_audit_partitions`` (the daily Beat/boot sweep over
    every tenant — order 021) and ``services.provisioning.provision_tenant``
    (order 022: pre-creates the same two leaves for the ONE tenant just born,
    so it never has to wait for the sweep to stop falling into DEFAULT).
    """
    today = today or timezone.now().date()
    months = []
    year, month = today.year, today.month
    for _ in range(count):
        months.append(date(year, month, 1))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return months


def _safe_schema_fragment(schema_name: str) -> str:
    return _UNSAFE_IDENT_CHARS.sub("_", schema_name.lower())


def tenant_partition_name(month_name: str, schema_name: str) -> str:
    return f"{month_name}_t_{_safe_schema_fragment(schema_name)}"


def _table_exists(cur, name: str) -> bool:
    cur.execute("SELECT to_regclass(%s) IS NOT NULL", [f"public.{name}"])
    return bool(cur.fetchone()[0])


def _revoke_mutation_grants(cur, name: str) -> None:
    """Mirror migration 0019's defense-in-depth REVOKE onto a new partition.

    GRANT/REVOKE do not propagate from a partitioned parent to its children
    (verified empirically — see order 020 report), unlike indexes and row
    triggers, which Postgres clones automatically. Without this, a partition
    created after the original REVOKE would silently keep PUBLIC's default
    UPDATE/DELETE/TRUNCATE privileges.
    """
    cur.execute(
        sql.SQL("REVOKE UPDATE, DELETE, TRUNCATE ON {} FROM PUBLIC").format(
            sql.Identifier("public", name)
        )
    )


def ensure_month_partition(for_date: date, cur=None) -> MonthPartition:
    """Idempotent: ensure the RANGE partition for *for_date*'s month exists.

    Creates it PARTITION BY LIST (schema_name) with its own DEFAULT leaf so
    the two-level DEFAULT contract holds for every month, not just the
    top-level catch-all. Safe to call repeatedly.
    """
    start, end = _month_bounds(for_date)
    name = f"{TABLE}_y{start.year:04d}m{start.month:02d}"
    default_name = f"{name}_default"
    own_cur = cur is None
    cur = cur or connection.cursor()
    try:
        cur.execute(
            sql.SQL(
                "CREATE TABLE IF NOT EXISTS {name} PARTITION OF {parent} "
                "FOR VALUES FROM (%s) TO (%s) PARTITION BY LIST (schema_name)"
            ).format(name=sql.Identifier("public", name), parent=PUBLIC_TABLE),
            [start, end],
        )
        was_created = _table_exists(cur, default_name) is False
        cur.execute(
            sql.SQL("CREATE TABLE IF NOT EXISTS {n} PARTITION OF {p} DEFAULT").format(
                n=sql.Identifier("public", default_name),
                p=sql.Identifier("public", name),
            )
        )
        if was_created:
            _revoke_mutation_grants(cur, default_name)
            _revoke_mutation_grants(cur, name)
    finally:
        if own_cur:
            cur.close()
    return MonthPartition(name=name, year=start.year, month=start.month, start=start, end=end)


def ensure_tenant_partition(for_date: date, schema_name: str, cur=None) -> str:
    """Idempotent: ensure a dedicated LIST leaf for *schema_name* within the
    month partition covering *for_date*.

    A tenant with a dedicated leaf can later be purged (retention window, or
    offboarding) with a DROP scoped to just that leaf, never touching any
    other tenant's rows in the same month — see
    ``apps.core.management.commands.purge_audit_logs`` ``--schema``.
    Tenants WITHOUT a dedicated leaf simply keep landing in the month's
    DEFAULT leaf alongside everyone else; that is expected, not an error.
    """
    own_cur = cur is None
    cur = cur or connection.cursor()
    try:
        month = ensure_month_partition(for_date, cur=cur)
        leaf_name = tenant_partition_name(month.name, schema_name)
        existed = _table_exists(cur, leaf_name)
        cur.execute(
            sql.SQL("CREATE TABLE IF NOT EXISTS {n} PARTITION OF {p} FOR VALUES IN (%s)").format(
                n=sql.Identifier("public", leaf_name),
                p=sql.Identifier("public", month.name),
            ),
            [schema_name],
        )
        if not existed:
            _revoke_mutation_grants(cur, leaf_name)
    finally:
        if own_cur:
            cur.close()
    return leaf_name


def ensure_default_partitions(cur=None) -> None:
    """Idempotent: ensure the top-level DEFAULT RANGE partition (and its own
    DEFAULT LIST leaf) exist. Installed once by the conversion migration;
    exposed here too so tests/tooling can (re)assert the invariant.
    """
    own_cur = cur is None
    cur = cur or connection.cursor()
    try:
        created = not _table_exists(cur, f"{TABLE}_default")
        cur.execute(
            sql.SQL(
                "CREATE TABLE IF NOT EXISTS {n} PARTITION OF {p} DEFAULT "
                "PARTITION BY LIST (schema_name)"
            ).format(n=sql.Identifier("public", f"{TABLE}_default"), p=PUBLIC_TABLE)
        )
        cur.execute(
            sql.SQL("CREATE TABLE IF NOT EXISTS {n} PARTITION OF {p} DEFAULT").format(
                n=sql.Identifier("public", f"{TABLE}_default_default"),
                p=sql.Identifier("public", f"{TABLE}_default"),
            )
        )
        if created:
            _revoke_mutation_grants(cur, f"{TABLE}_default")
            _revoke_mutation_grants(cur, f"{TABLE}_default_default")
    finally:
        if own_cur:
            cur.close()


def list_month_partitions(cur=None) -> list[MonthPartition]:
    """All month RANGE partitions currently attached to core_auditlog.

    Discovery is name-based (see module docstring), not by parsing
    ``pg_get_expr(relpartbound, ...)`` — we control both the writer
    (``ensure_month_partition``) and the reader, so the name IS the bound.
    """
    own_cur = cur is None
    cur = cur or connection.cursor()
    try:
        cur.execute(
            """
            SELECT c.relname
            FROM pg_inherits i
            JOIN pg_class c ON c.oid = i.inhrelid
            JOIN pg_class p ON p.oid = i.inhparent
            JOIN pg_namespace n ON n.oid = p.relnamespace
            WHERE p.relname = %s AND n.nspname = 'public'
            """,
            [TABLE],
        )
        names = [row[0] for row in cur.fetchall()]
    finally:
        if own_cur:
            cur.close()

    partitions = []
    for name in names:
        m = _MONTH_NAME_RE.match(name)
        if not m:
            continue
        year, month = int(m.group(1)), int(m.group(2))
        start, end = _month_bounds(date(year, month, 1))
        partitions.append(MonthPartition(name=name, year=year, month=month, start=start, end=end))
    return sorted(partitions, key=lambda p: p.start)


def partition_exists(name: str, cur=None) -> bool:
    own_cur = cur is None
    cur = cur or connection.cursor()
    try:
        return _table_exists(cur, name)
    finally:
        if own_cur:
            cur.close()


def partition_row_count(name: str, cur=None) -> int:
    own_cur = cur is None
    cur = cur or connection.cursor()
    try:
        cur.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier("public", name)))
        return cur.fetchone()[0]
    finally:
        if own_cur:
            cur.close()


def default_leaf_row_counts(cur=None) -> dict[str, int]:
    """Row counts of every DEFAULT leaf that currently holds at least one row.

    Order 021, Emenda do Imediato: before ``ensure_audit_partitions`` existed
    and ran on the real write path, a row landing in DEFAULT was the norm
    (nothing else ever pre-created the right partition). Now that something
    does, on the real path (boot + daily beat — see
    ``apps.core.management.commands.ensure_audit_partitions``), a non-zero
    count here means a partition is MISSING for some tenant/month, not
    business as usual — the caller is expected to log/alert on it.

    Checks the top-level catch-all (``core_auditlog_default_default``) and
    every month's own DEFAULT leaf; never the dedicated tenant leaves
    (those are supposed to hold rows).
    """
    own_cur = cur is None
    cur = cur or connection.cursor()
    try:
        leaves = [f"{TABLE}_default_default"]
        leaves.extend(month.default_leaf for month in list_month_partitions(cur=cur))
        counts: dict[str, int] = {}
        for leaf in leaves:
            if not _table_exists(cur, leaf):
                continue
            n = partition_row_count(leaf, cur=cur)
            if n:
                counts[leaf] = n
        return counts
    finally:
        if own_cur:
            cur.close()


def drop_partition(name: str, *, cold_export_receipt) -> None:
    """DROP a partition — the ONLY way this module ever removes audit rows.

    Never DELETE: a bulk DELETE on a table with 8 indexes generates bloat and
    a long vacuum on precisely the table that must stay available for
    writes. DROP is DDL: milliseconds, no dead space.

    ``cold_export_receipt`` is mandatory and must be the object returned by a
    *successful* ``apps.core.cold_storage.export_and_verify_partition(name,
    ...)`` call for THIS exact partition — see that module. This is not a
    formality: it is the code-level enforcement of the Capitão's amendment
    that no partition may disappear without a verified cold copy existing
    first. There is no parameter that lets a caller skip straight to DROP.
    """
    from apps.core.cold_storage import ColdExportReceipt  # local import: avoid cycle

    if not isinstance(cold_export_receipt, ColdExportReceipt):
        raise PartitioningError(
            f"refusing to DROP {name!r}: no verified cold-export receipt was provided "
            "(expected apps.core.cold_storage.ColdExportReceipt)"
        )
    if cold_export_receipt.partition_name != name:
        raise PartitioningError(
            f"refusing to DROP {name!r}: cold-export receipt is for a different "
            f"partition ({cold_export_receipt.partition_name!r})"
        )
    if not cold_export_receipt.verified:
        raise PartitioningError(
            f"refusing to DROP {name!r}: cold-export receipt is not marked verified"
        )

    with connection.cursor() as cur:
        # Bound how long this DDL will queue behind other lock holders. A DROP
        # of a month partition takes AccessExclusiveLock on the *whole*
        # core_auditlog parent (measured — see report); a DROP of a tenant
        # leaf only locks its immediate month parent. Either way this must
        # not be allowed to sit and accumulate a waiter queue indefinitely.
        cur.execute("SET LOCAL lock_timeout = '5s'")
        # user_id's FK to core_user is DEFERRABLE INITIALLY DEFERRED (see
        # migration 0043): any INSERT into this exact partition earlier in
        # the SAME transaction queues a deferred referential-integrity check
        # against it — even when user_id is NULL, since Postgres schedules
        # the check trigger unconditionally and only skips the NULL case
        # inside it. Postgres refuses to DROP a table with a pending
        # (unfired) trigger event ("cannot DROP TABLE ... because it has
        # pending trigger events"). Forcing the check now — harmless, it was
        # always going to pass or fail on its own merits at commit — clears
        # that state before the DROP.
        cur.execute("SET CONSTRAINTS ALL IMMEDIATE")
        cur.execute(sql.SQL("DROP TABLE {}").format(sql.Identifier("public", name)))
