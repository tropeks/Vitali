"""Restore drill for a cold copy of ``core_auditlog`` (order 020 decision,
built in order 032): download, decrypt and check against the manifest.

The drill runs WITHOUT the source database — after the purge DROPs the
partition, the cold copy and its manifest are all there is. It reuses the
export's own format constants and the same gpg mechanism as
``scripts/backup.sh`` (``apps.core.gpg_crypto``), and it must be able to
REPROVE: a copy that differs from its manifest is refused, naming the check.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from apps.core import gpg_crypto
from apps.core.cold_storage import COLUMNS, FORMAT_VERSION, ColdExportError, _gpg_key
from apps.core.cold_storage_backends import (
    ColdStorageBackend,
    ColdStorageError,
    FetchPending,
    backend_for_location,
)
from apps.core.file_digest import sha256_file


class ColdDrillError(ColdExportError):
    """The stored copy could not be proven readable and whole. Names the check."""


@dataclass(frozen=True)
class DrillResult:
    """``status`` is ``"ok"`` (downloaded, decrypted, matched the manifest) or
    ``"pending"`` (Glacier restore requested or still running: run again)."""

    status: str
    detail: str
    row_count: int | None = None
    manifest: dict[str, Any] | None = None


def _count_rows(plaintext_path: Path) -> int:
    rows = 0
    with open(plaintext_path, encoding="utf-8") as f:
        for number, line in enumerate(f, start=1):
            if not line.strip():
                continue
            record = json.loads(line)
            if set(record) != set(COLUMNS):
                raise ColdDrillError(
                    f"line {number} does not carry the {FORMAT_VERSION} columns: {sorted(record)}"
                )
            rows += 1
    return rows


def _check_against_manifest(payload: Path, manifest: dict[str, Any], plain: Path, key: str) -> int:
    if manifest.get("format_version") != FORMAT_VERSION:
        raise ColdDrillError(
            f"manifest format_version {manifest.get('format_version')!r} != {FORMAT_VERSION!r}"
        )
    actual_cipher = sha256_file(payload)
    if actual_cipher != manifest.get("sha256_cipher"):
        raise ColdDrillError(
            f"sha256_cipher mismatch: stored payload {actual_cipher} != manifest "
            f"{manifest.get('sha256_cipher')}"
        )
    try:
        gpg_crypto.decrypt_file(payload, plain, passphrase=key, gnupg_home=plain.parent / "gnupg")
    except gpg_crypto.GpgError as exc:
        raise ColdDrillError(f"decrypt failed: {exc}") from exc
    actual_plain = sha256_file(plain)
    if actual_plain != manifest.get("sha256_plain"):
        raise ColdDrillError(
            f"sha256_plain mismatch: decrypted {actual_plain} != manifest "
            f"{manifest.get('sha256_plain')}"
        )
    rows = _count_rows(plain)
    if rows != manifest.get("row_count"):
        raise ColdDrillError(
            f"row_count mismatch: decrypted copy has {rows} rows, manifest says "
            f"{manifest.get('row_count')}"
        )
    return rows


def drill_cold_copy(location: str, *, backend: ColdStorageBackend | None = None) -> DrillResult:
    """Download the cold copy at *location*, decrypt it and check it against
    its own manifest — without the source database, which after the DROP no
    longer has the partition. Raises ColdDrillError naming the failed check.

    Glacier objects come back asynchronously (Expedited 1–5 min, Standard
    3–5 h): the first run requests the restore and answers ``pending``; later
    runs answer ``pending`` while it is in progress, then check the copy.
    """
    key = _gpg_key()
    try:
        backend = backend or backend_for_location(location)
    except ColdStorageError as exc:
        raise ColdDrillError(f"no backend for {location!r}: {exc}") from exc
    with tempfile.TemporaryDirectory(prefix="auditlog-drill-") as tmp:
        tmp_dir = Path(tmp)
        try:
            fetched = backend.fetch(location, tmp_dir)
        except ColdStorageError as exc:
            raise ColdDrillError(f"fetch failed: {exc}") from exc
        if isinstance(fetched, FetchPending):
            return DrillResult(status="pending", detail=fetched.detail)
        try:
            manifest = json.loads(fetched.manifest_path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise ColdDrillError(f"manifest is not JSON: {exc}") from exc
        rows = _check_against_manifest(
            fetched.payload_path, manifest, tmp_dir / "drill-plain.jsonl", key
        )
    return DrillResult(
        status="ok",
        detail=f"{location}: {rows} linha(s), sha256 do cifrado e do claro conferem com o manifesto",
        row_count=rows,
        manifest=manifest,
    )
