"""Where a verified cold export ends up (order 020, Capitão's amendment).

Only ``LocalDiskColdStorageBackend`` is implemented here — the "alvo local
para teste" the Capitão asked for while no AWS account exists yet. An S3
Glacier Flexible Retrieval backend (write-only credentials, Object Lock
compliance mode, one object per partition + manifest, async restore-drill) is
real infrastructure work that needs a new Python dependency (boto3 or the
minio client — neither is in requirements/base.txt today) and a MinIO
deployment in the lab to prove the write-only/Object-Lock behaviour before it
ever sees a real bucket. That was intentionally NOT added here without
sign-off — see the order-020 report. ``ColdStorageBackend`` is the seam it
plugs into: nothing in ``apps.core.cold_storage`` or
``apps.core.partitioning`` needs to change to add it.
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
