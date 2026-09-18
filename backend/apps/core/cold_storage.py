"""
Cold export for ``core_auditlog`` partitions (order 020, Capitão's amendment).

Retention purge is no longer just ``DROP PARTITION``. The DROP is the LAST
step of a sequence, and every earlier step must succeed before it is even
attempted:

    export (JSONL) -> sha256 of the plaintext -> encrypt (gpg, reusing the
    SAME key/mechanism as scripts/backup.sh — see apps.core.gpg_crypto)
    -> decrypt + restore-to-scratch-table + compare against the LIVE
    partition, row for row, LOCALLY -> only then hand the encrypted artifact
    + manifest to a storage backend (apps.core.cold_storage_backends)
    -> only then is the caller allowed to DROP the partition.

Verification happens BEFORE anything is stored, not after: an object written
under Object Lock compliance mode (the eventual S3 target — see
cold_storage_backends.py) cannot be taken back if it turns out to be wrong.

Format is JSONL (one audit row per line, explicit column order) rather than
``pg_dump``'s binary/custom format: it must still open in twenty years, in a
Postgres major version that may not exist, possibly with no Postgres at all.
A format coupled to the server version is not a cold archive, it is a time
bomb — the same reasoning scripts/backup.sh already documents for its own
dumps.
"""

from __future__ import annotations

import json
import tempfile
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from django.conf import settings
from django.db import connection
from psycopg2 import sql
from psycopg2.extras import execute_values

from apps.core import gpg_crypto
from apps.core.cold_storage_backends import ColdStorageBackend, LocalDiskColdStorageBackend
from apps.core.file_digest import sha256_file

FORMAT_VERSION = "vitali-auditlog-cold/1"
TOOL_VERSION = "apps.core.cold_storage/1"

# Explicit, fixed column order — used for the SELECT, the JSONL rows, and the
# scratch-table restore, so a positional mismatch can never silently swap two
# columns.
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


class ColdExportError(Exception):
    """Raised when any step of export/encrypt/verify/store fails.

    The message always names the specific step that failed — see the
    Capitão's amendment: "a recusa tem de nomear o motivo".
    """


@dataclass(frozen=True)
class ColdExportReceipt:
    """Proof that *partition_name* was exported, encrypted, verified LOCALLY
    against the still-live partition, and durably stored — in that order —
    before anything was allowed to touch the DROP path.
    ``apps.core.partitioning.drop_partition`` refuses to run without one of
    these, matching this exact partition name.
    """

    partition_name: str
    verified: bool
    manifest: dict[str, Any]
    stored_location: str


def _gpg_key() -> str:
    key = getattr(settings, "BACKUP_ENCRYPTION_KEY", "") or ""
    if not key:
        raise ColdExportError(
            "BACKUP_ENCRYPTION_KEY is not set — the audit-log cold export reuses the "
            "SAME encryption key/mechanism as scripts/backup.sh on purpose (no new key "
            "management); without it there is nothing to encrypt with, and this code "
            "never writes plaintext audit data to disk as a fallback."
        )
    return key


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return str(value)


def _export_jsonl(partition_name: str, out_path: Path, cur) -> dict[str, Any]:
    query = sql.SQL("SELECT {cols} FROM {tbl} ORDER BY id").format(
        cols=sql.SQL(", ").join(sql.Identifier(c) for c in COLUMNS),
        tbl=sql.Identifier("public", partition_name),
    )
    cur.execute(query)
    row_count = 0
    bounds: dict[str, Any] = {"min": None, "max": None}
    schema_names: set[str] = set()
    with open(out_path, "w", encoding="utf-8") as f:
        for row in cur:
            record = dict(zip(COLUMNS, row, strict=True))
            f.write(json.dumps(record, default=_json_default, sort_keys=True, ensure_ascii=False))
            f.write("\n")
            row_count += 1
            created_at = record["created_at"]
            bounds["min"] = created_at if bounds["min"] is None else min(bounds["min"], created_at)
            bounds["max"] = created_at if bounds["max"] is None else max(bounds["max"], created_at)
            schema_names.add(record["schema_name"])
    return {
        "row_count": row_count,
        "created_at_min": bounds["min"].isoformat() if bounds["min"] else None,
        "created_at_max": bounds["max"].isoformat() if bounds["max"] else None,
        "schema_names": sorted(schema_names),
    }


def _restore_rows_to_scratch(scratch: str, plaintext_path: Path, cur) -> None:
    # No "ON COMMIT DROP": this runs under Django's default autocommit, where
    # each cur.execute() is its own implicit transaction — an ON-COMMIT-DROP
    # temp table would vanish the instant its own CREATE statement committed,
    # before the INSERT below ever ran. Session-scoped TEMP is dropped
    # explicitly in the caller's `finally` instead (see
    # ``_restore_and_compare_locally``), which works regardless of autocommit.
    cur.execute(
        sql.SQL(
            """
            CREATE TEMP TABLE {scratch} (
                id bigint, action text, resource_type text, resource_id text,
                old_data jsonb, new_data jsonb, ip_address inet, user_agent text,
                created_at timestamptz, user_id uuid, schema_name text
            )
            """
        ).format(scratch=sql.Identifier(scratch))
    )
    rows = []
    with open(plaintext_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                record = json.loads(line)
                rows.append(tuple(record[c] for c in COLUMNS))
    if rows:
        # scratch is our own uuid4-derived identifier and COLUMNS is the fixed
        # tuple above — both are internally controlled, not user input — so a
        # plain string template is safe here. (execute_values' template
        # splitting wants a plain str; psycopg2.sql.Composed.as_string()
        # requires a raw psycopg2 cursor, which Django's CursorWrapper is not.)
        col_list = ", ".join(COLUMNS)
        execute_values(cur, f'INSERT INTO "{scratch}" ({col_list}) VALUES %s', rows)


def _diff_scratch_vs_live(partition_name: str, scratch: str, cur) -> tuple[int, int, int]:
    live = sql.Identifier("public", partition_name)
    scratch_id = sql.Identifier(scratch)
    cols = sql.SQL(", ").join(map(sql.Identifier, COLUMNS))
    cur.execute(sql.SQL("SELECT count(*) FROM {live}").format(live=live))
    live_count = cur.fetchone()[0]
    cur.execute(sql.SQL("SELECT count(*) FROM {s}").format(s=scratch_id))
    scratch_count = cur.fetchone()[0]
    cur.execute(
        sql.SQL(
            "SELECT count(*) FROM ((SELECT {c} FROM {live} EXCEPT SELECT {c} FROM {s}) "
            "UNION ALL (SELECT {c} FROM {s} EXCEPT SELECT {c} FROM {live})) diff"
        ).format(c=cols, live=live, s=scratch_id)
    )
    diff_count = cur.fetchone()[0]
    return live_count, scratch_count, diff_count


def _restore_and_compare_locally(partition_name: str, plaintext_path: Path, cur) -> None:
    """Restore the decrypted JSONL into a scratch temp table and diff it
    against the LIVE partition, row for row. Raises ColdExportError (naming
    the mismatch) on any discrepancy — this IS the "restauração provada"
    step, run locally, before anything is stored or dropped.
    """
    scratch = f"auditlog_cold_verify_{uuid.uuid4().hex[:12]}"
    try:
        _restore_rows_to_scratch(scratch, plaintext_path, cur)
        live_count, scratch_count, diff_count = _diff_scratch_vs_live(partition_name, scratch, cur)
    finally:
        cur.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(scratch)))
    if live_count != scratch_count:
        raise ColdExportError(
            f"restore-and-compare failed for {partition_name!r}: live partition has "
            f"{live_count} rows, restored scratch table has {scratch_count} — refusing to DROP"
        )
    if diff_count:
        raise ColdExportError(
            f"restore-and-compare failed for {partition_name!r}: {diff_count} row(s) differ "
            "in content between the live partition and the decrypted cold export — refusing to DROP"
        )


def _build_manifest(
    partition_name: str, exported_at: datetime, sha256_plain: str, stats: dict
) -> dict:
    return {
        "format_version": FORMAT_VERSION,
        "tool_version": TOOL_VERSION,
        "exported_at": exported_at.isoformat(),
        "partition_name": partition_name,
        "sha256_plain": sha256_plain,
        **stats,
    }


def _verify_locally_or_raise(
    ciphertext_path: Path, decrypted_path: Path, sha256_plain: str, key: str, gnupg_home: Path
) -> None:
    try:
        gpg_crypto.decrypt_file(
            ciphertext_path, decrypted_path, passphrase=key, gnupg_home=gnupg_home
        )
    except gpg_crypto.GpgError as exc:
        raise ColdExportError(f"local verification refused to proceed to DROP: {exc}") from exc
    actual = sha256_file(decrypted_path)
    if actual != sha256_plain:
        raise ColdExportError(
            f"cold export failed local verification: sha256 after decrypt ({actual}) != "
            f"sha256 before encrypt ({sha256_plain}) — refusing to store or DROP"
        )


def export_and_verify_partition(
    partition_name: str,
    *,
    backend: ColdStorageBackend | None = None,
) -> ColdExportReceipt:
    """Run the full sequence for *partition_name* and return a receipt.

    Order matches the Capitão's amendment: export -> checksum -> encrypt ->
    decrypt + restore-and-compare LOCALLY -> store -> confirm what was
    stored. Raises ColdExportError, naming the failing step, otherwise.
    """
    backend = backend or LocalDiskColdStorageBackend()
    key = _gpg_key()
    exported_at = datetime.now(UTC)
    key_prefix = f"core_auditlog_{partition_name}_{exported_at.strftime('%Y%m%dT%H%M%SZ')}"

    with tempfile.TemporaryDirectory(prefix="auditlog-cold-") as tmp:
        tmp_dir = Path(tmp)
        plaintext_path = tmp_dir / f"{key_prefix}.jsonl"
        ciphertext_path = tmp_dir / f"{key_prefix}.jsonl.gpg"
        manifest_path = tmp_dir / f"{key_prefix}.manifest.json"
        decrypted_check_path = tmp_dir / f"{key_prefix}.decrypted-check.jsonl"
        gnupg_home = tmp_dir / "gnupg"

        with connection.cursor() as cur:
            stats = _export_jsonl(partition_name, plaintext_path, cur)
            sha256_plain = sha256_file(plaintext_path)
            gpg_crypto.encrypt_file(
                plaintext_path, ciphertext_path, passphrase=key, gnupg_home=gnupg_home
            )
            sha256_cipher = sha256_file(ciphertext_path)

            manifest = _build_manifest(partition_name, exported_at, sha256_plain, stats)
            manifest["sha256_cipher"] = sha256_cipher
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True))

            _verify_locally_or_raise(
                ciphertext_path, decrypted_check_path, sha256_plain, key, gnupg_home
            )
            _restore_and_compare_locally(partition_name, decrypted_check_path, cur)

        location = backend.store(
            payload_path=ciphertext_path, manifest_path=manifest_path, key_prefix=key_prefix
        )
        backend.verify_stored(location, sha256_cipher)

    return ColdExportReceipt(
        partition_name=partition_name, verified=True, manifest=manifest, stored_location=location
    )
