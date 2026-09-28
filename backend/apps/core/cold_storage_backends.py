"""Where a verified cold export ends up (orders 020 and 032).

``ColdStorageBackend`` is the seam: ``apps.core.cold_storage`` exports,
encrypts and verifies LOCALLY before handing the artifact over, and
``apps.core.partitioning.drop_partition`` refuses without the resulting
receipt. Two backends plug into it:

* ``LocalDiskColdStorageBackend`` — the "alvo local para teste" of order 020,
  still the default (``AUDIT_LOG_COLD_STORAGE_BACKEND=local``).
* ``S3ColdStorageBackend`` (order 032) — the destination the Capitão chose in
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

import base64
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qs, quote, urlsplit

from dateutil.relativedelta import relativedelta
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


# ─── S3 (order 032) ──────────────────────────────────────────────────────────

#: Largest object a single ``PutObject`` accepts. A month of one tenant's audit
#: trail is ~300 MB in the ADR-0001 worst case; past this, refuse by name rather
#: than silently switch to multipart (whose checksum is a different thing).
MAX_SINGLE_PUT_BYTES = 5 * 1024**3

#: Storage classes whose objects must be restored before they can be read.
_ARCHIVE_CLASSES = frozenset({"GLACIER", "DEEP_ARCHIVE"})


def format_s3_location(bucket: str, key: str, version_id: str, manifest_version_id: str) -> str:
    """The opaque location the receipt carries: exact object VERSIONS, because
    the write-only credential can still put a new version under the same key,
    and only the locked original is the verified one."""
    return (
        f"s3://{bucket}/{key}?versionId={quote(version_id, safe='')}"
        f"&manifestVersionId={quote(manifest_version_id, safe='')}"
    )


def parse_s3_location(location: str) -> tuple[str, str, dict[str, str]]:
    parts = urlsplit(location)
    query = {k: v[0] for k, v in parse_qs(parts.query).items()}
    if parts.scheme != "s3" or not parts.netloc or not parts.path.strip("/"):
        raise ColdStorageError(f"{location!r} is not an s3:// cold-copy location")
    for required in ("versionId", "manifestVersionId"):
        if not query.get(required):
            raise ColdStorageError(f"{location!r} has no {required} — cannot pin the object")
    return parts.netloc, parts.path.lstrip("/"), query


def _b64_of_hex(hex_digest: str) -> str:
    return base64.b64encode(bytes.fromhex(hex_digest)).decode()


def _setting_lock_months() -> int:
    return int(settings.AUDIT_LOG_COLD_LOCK_MONTHS)


def _setting_storage_class() -> str:
    return str(settings.AUDIT_LOG_COLD_S3_STORAGE_CLASS)


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class S3ColdStorageBackend:
    """One locked object per partition, plus its locked manifest.

    ``client`` is a boto3 S3 client holding the WRITE-ONLY credential. The
    payload goes in ``storage_class`` (GLACIER in production); the manifest
    stays in STANDARD so the archive can be identified and checked without a
    restore request.
    """

    bucket: str
    client: Any
    storage_class: str = field(default_factory=_setting_storage_class)
    lock_months: int = field(default_factory=_setting_lock_months)
    prefix: str = "core_auditlog/"
    restore_tier: str = "Standard"
    restore_days: int = 7
    clock: Callable[[], datetime] = _utcnow

    def __post_init__(self) -> None:
        if self.lock_months < 1:
            raise ColdStorageError(
                f"AUDIT_LOG_COLD_LOCK_MONTHS={self.lock_months}: an unlocked or zero-length "
                "lock is not a cold archive (Capitão, order 020: COMPLIANCE for the retention)"
            )

    @classmethod
    def from_settings(cls) -> S3ColdStorageBackend:
        import boto3

        bucket = settings.AUDIT_LOG_COLD_S3_BUCKET
        if not bucket:
            raise ColdStorageError(
                "AUDIT_LOG_COLD_STORAGE_BACKEND=s3 needs AUDIT_LOG_COLD_S3_BUCKET — refusing "
                "to guess where 20 years of audit trail should go"
            )
        client = boto3.client(
            "s3",
            region_name=settings.AUDIT_LOG_COLD_S3_REGION,
            endpoint_url=settings.AUDIT_LOG_COLD_S3_ENDPOINT_URL or None,
        )
        return cls(bucket=bucket, client=client)

    # ── store ────────────────────────────────────────────────────────────────

    def _retain_until(self) -> datetime:
        return self.clock() + relativedelta(months=self.lock_months)

    def _put(self, path: Path, key: str, storage_class: str, until: datetime) -> str:
        from botocore.exceptions import BotoCoreError, ClientError

        size = path.stat().st_size
        if size > MAX_SINGLE_PUT_BYTES:
            raise ColdStorageError(
                f"{path.name} has {size} bytes, over the single-PUT limit — split the "
                "partition; multipart is not implemented"
            )
        with open(path, "rb") as body:
            try:
                resp = self.client.put_object(
                    Bucket=self.bucket,
                    Key=key,
                    Body=body,
                    StorageClass=storage_class,
                    ObjectLockMode="COMPLIANCE",
                    ObjectLockRetainUntilDate=until,
                    ChecksumAlgorithm="SHA256",
                    ChecksumSHA256=_b64_of_hex(sha256_file(path)),
                )
            except (ClientError, BotoCoreError) as exc:
                raise ColdStorageError(
                    f"PutObject s3://{self.bucket}/{key} refused: {exc}"
                ) from exc
        version = resp.get("VersionId")
        if not version:
            raise ColdStorageError(
                f"PutObject s3://{self.bucket}/{key} returned no VersionId — the bucket is not "
                "versioned, so it cannot hold an Object Lock"
            )
        return str(version)

    def store(self, *, payload_path: Path, manifest_path: Path, key_prefix: str) -> str:
        until = self._retain_until()
        key = f"{self.prefix}{key_prefix}{PAYLOAD_SUFFIX}"
        version = self._put(payload_path, key, self.storage_class, until)
        manifest_version = self._put(
            manifest_path, f"{self.prefix}{key_prefix}{MANIFEST_SUFFIX}", "STANDARD", until
        )
        return format_s3_location(self.bucket, key, version, manifest_version)

    # ── verify ───────────────────────────────────────────────────────────────

    def _head(self, key: str, version_id: str, **extra: Any) -> dict[str, Any]:
        from botocore.exceptions import BotoCoreError, ClientError

        try:
            return dict(
                self.client.head_object(Bucket=self.bucket, Key=key, VersionId=version_id, **extra)
            )
        except (ClientError, BotoCoreError) as exc:
            raise ColdStorageError(
                f"HeadObject s3://{self.bucket}/{key} (version {version_id}) failed: {exc}"
            ) from exc

    def _pinned(self, location: str) -> tuple[str, dict[str, str]]:
        bucket, key, versions = parse_s3_location(location)
        if bucket != self.bucket:
            raise ColdStorageError(f"{location!r} is not in bucket {self.bucket!r}")
        return key, versions

    def verify_stored(self, location: str, expected_sha256_ciphertext: str) -> None:
        """Re-read the stored object's metadata — never its body: in GLACIER
        the body is not readable without a restore. The service already
        verified the SHA-256 on arrival; this confirms the checksum, the lock
        mode and the lock length of the exact version the receipt points to."""
        key, versions = self._pinned(location)
        head = self._head(key, versions["versionId"], ChecksumMode="ENABLED")
        expected = _b64_of_hex(expected_sha256_ciphertext)
        if head.get("ChecksumSHA256") != expected:
            raise ColdStorageError(
                f"stored object {location!r} does not match what was written "
                f"(sha256 {head.get('ChecksumSHA256')} != {expected}) — refusing to trust it"
            )
        mode = head.get("ObjectLockMode")
        if mode != "COMPLIANCE":
            raise ColdStorageError(
                f"stored object {location!r} has Object Lock mode {mode!r}, not COMPLIANCE — "
                "it could be deleted before the retention ends"
            )
        until = head.get("ObjectLockRetainUntilDate")
        minimum = self._retain_until() - timedelta(days=1)
        if until is None or until < minimum:
            raise ColdStorageError(
                f"stored object {location!r} is locked until {until}, short of the "
                f"{self.lock_months}-month retain-until ({minimum:%Y-%m-%d})"
            )

    # ── fetch (drill) ────────────────────────────────────────────────────────

    def _download(self, key: str, version_id: str, dest: Path) -> Path:
        from botocore.exceptions import BotoCoreError, ClientError

        try:
            body = self.client.get_object(Bucket=self.bucket, Key=key, VersionId=version_id)["Body"]
            with open(dest, "wb") as f:
                shutil.copyfileobj(body, f, 1024 * 1024)
        except (ClientError, BotoCoreError) as exc:
            raise ColdStorageError(f"GetObject s3://{self.bucket}/{key} failed: {exc}") from exc
        return dest

    def fetch(self, location: str, dest_dir: Path) -> FetchedCopy | FetchPending:
        from botocore.exceptions import BotoCoreError, ClientError

        key, versions = self._pinned(location)
        version = versions["versionId"]
        head = self._head(key, version)
        if head.get("StorageClass") in _ARCHIVE_CLASSES:
            restore = head.get("Restore")
            if not restore:
                try:
                    self.client.restore_object(
                        Bucket=self.bucket,
                        Key=key,
                        VersionId=version,
                        RestoreRequest={
                            "Days": self.restore_days,
                            "GlacierJobParameters": {"Tier": self.restore_tier},
                        },
                    )
                except (ClientError, BotoCoreError) as exc:
                    raise ColdStorageError(f"RestoreObject {location!r} failed: {exc}") from exc
                return FetchPending(
                    f"restauração pedida ({self.restore_tier}, {self.restore_days} dias) para "
                    f"{location}; rode o drill de novo quando ela terminar"
                )
            if 'ongoing-request="true"' in restore:
                return FetchPending(f"restauração em andamento para {location}")
        manifest_key = str(Path(key).with_name(manifest_name_for(Path(key).name)))
        return FetchedCopy(
            payload_path=self._download(key, version, dest_dir / Path(key).name),
            manifest_path=self._download(
                manifest_key, versions["manifestVersionId"], dest_dir / Path(manifest_key).name
            ),
        )


def get_cold_storage_backend() -> ColdStorageBackend:
    """The backend ``AUDIT_LOG_COLD_STORAGE_BACKEND`` names (``local`` by default)."""
    kind = settings.AUDIT_LOG_COLD_STORAGE_BACKEND
    if kind == "local":
        return LocalDiskColdStorageBackend()
    if kind == "s3":
        return S3ColdStorageBackend.from_settings()
    raise ColdStorageError(
        f"AUDIT_LOG_COLD_STORAGE_BACKEND={kind!r} is unknown — use 'local' or 's3'"
    )


def backend_for_location(location: str) -> ColdStorageBackend:
    """The backend that can read *location* back (the drill's default)."""
    if location.startswith("s3://"):
        return S3ColdStorageBackend.from_settings()
    return LocalDiskColdStorageBackend()
