"""Where a verified cold export ends up (orders 020 and 032).

``ColdStorageBackend`` is the seam: ``apps.core.cold_storage`` exports,
encrypts and verifies LOCALLY before handing the artifact over, and
``apps.core.partitioning.drop_partition`` refuses without the resulting
receipt. Two backends plug into it:

* ``LocalDiskColdStorageBackend`` — the "alvo local para teste" of order 020,
  still the default (``AUDIT_LOG_COLD_STORAGE_BACKEND=local``).
* ``apps.core.cold_storage_s3.S3ColdStorageBackend`` (order 032) — the destination the Capitão chose in
  order 020: S3 Glacier Flexible in São Paulo, one object per partition plus
  its manifest as an object of its own, Object Lock in COMPLIANCE mode for
  ``AUDIT_LOG_COLD_LOCK_MONTHS`` (240, the ADR-0001 retention, in months like
  the ADR), a SHA-256 checksum the service verifies on arrival, and a
  write-only credential (``docs/ops/auditlog-cold-writer-policy.json``).
  Proven against an ephemeral MinIO in the lab
  (``apps/core/tests/test_cold_storage_minio.py``) and, for the Glacier
  restore cycle MinIO does not emulate, with botocore's ``Stubber``.

Both also ``fetch`` a stored copy back for the restore drill
(``apps.core.cold_storage.drill_cold_copy``). Glacier returns objects
asynchronously, so ``fetch`` can answer ``FetchPending`` instead of files.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from django.conf import settings

from apps.core.file_digest import sha256_file


class ColdStorageError(Exception):
    """Raised by a backend when store/verify cannot be trusted."""


PAYLOAD_SUFFIX = ".jsonl.gpg"
MANIFEST_SUFFIX = ".manifest.json"


def manifest_name_for(payload_name: str) -> str:
    """``<prefix>.jsonl.gpg`` -> ``<prefix>.manifest.json`` (the pair ``store`` writes)."""
    if not payload_name.endswith(PAYLOAD_SUFFIX):
        raise ColdStorageError(f"{payload_name!r} is not a cold-export payload ({PAYLOAD_SUFFIX})")
    return payload_name[: -len(PAYLOAD_SUFFIX)] + MANIFEST_SUFFIX


@dataclass(frozen=True)
class FetchedCopy:
    """A stored copy brought back to local files, ready for the drill."""

    payload_path: Path
    manifest_path: Path


@dataclass(frozen=True)
class FetchPending:
    """The copy exists but is not readable yet (Glacier restore not finished)."""

    detail: str


class ColdStorageBackend(Protocol):
    def store(self, *, payload_path: Path, manifest_path: Path, key_prefix: str) -> str:
        """Persist both files durably. Returns an opaque location string."""
        ...

    def verify_stored(self, location: str, expected_sha256_ciphertext: str) -> None:
        """Re-read what was just stored and confirm it matches what was written.

        Must raise ColdStorageError (naming the mismatch); there is no valid
        "keep going" return value — see the Capitão's amendment: verify
        before DROP, always.
        """
        ...

    def fetch(self, location: str, dest_dir: Path) -> FetchedCopy | FetchPending:
        """Bring the payload + manifest at *location* back for the drill."""
        ...


@dataclass
class LocalDiskColdStorageBackend:
    """Copies the artifact + manifest into a local directory
    (``settings.AUDIT_LOG_COLD_STORAGE_DIR``), next to what
    ``scripts/backup.sh`` already writes to disk.
    """

    directory: Path = field(default_factory=lambda: Path(settings.AUDIT_LOG_COLD_STORAGE_DIR))

    def store(self, *, payload_path: Path, manifest_path: Path, key_prefix: str) -> str:
        self.directory.mkdir(parents=True, exist_ok=True)
        dest_payload = self.directory / f"{key_prefix}.jsonl.gpg"
        dest_manifest = self.directory / f"{key_prefix}.manifest.json"
        shutil.copy2(payload_path, dest_payload)
        shutil.copy2(manifest_path, dest_manifest)
        return str(dest_payload)

    def verify_stored(self, location: str, expected_sha256_ciphertext: str) -> None:
        path = Path(location)
        if not path.is_file():
            raise ColdStorageError(f"stored artifact missing at {location!r} after store()")
        actual = sha256_file(path)
        if actual != expected_sha256_ciphertext:
            raise ColdStorageError(
                f"stored artifact at {location!r} does not match what was written "
                f"(sha256 {actual} != {expected_sha256_ciphertext}) — refusing to trust it"
            )

    def fetch(self, location: str, dest_dir: Path) -> FetchedCopy | FetchPending:
        payload = Path(location)
        manifest = payload.with_name(manifest_name_for(payload.name))
        for path in (payload, manifest):
            if not path.is_file():
                raise ColdStorageError(f"cold copy missing at {str(path)!r}")
        return FetchedCopy(payload_path=payload, manifest_path=manifest)


def get_cold_storage_backend() -> ColdStorageBackend:
    """The backend ``AUDIT_LOG_COLD_STORAGE_BACKEND`` names (``local`` by default)."""
    kind = settings.AUDIT_LOG_COLD_STORAGE_BACKEND
    if kind == "local":
        return LocalDiskColdStorageBackend()
    if kind == "s3":
        from apps.core.cold_storage_s3 import S3ColdStorageBackend

        return S3ColdStorageBackend.from_settings()
    raise ColdStorageError(
        f"AUDIT_LOG_COLD_STORAGE_BACKEND={kind!r} is unknown — use 'local' or 's3'"
    )


def backend_for_location(location: str) -> ColdStorageBackend:
    """The backend that can read *location* back (the drill's default)."""
    if location.startswith("s3://"):
        from apps.core.cold_storage_s3 import S3ColdStorageBackend

        return S3ColdStorageBackend.from_settings()
    return LocalDiskColdStorageBackend()
