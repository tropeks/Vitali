"""S3 destination for the audit-log cold copy (order 032).

The destination the Capitão chose in order 020 — see the module docstring of
``apps.core.cold_storage_backends`` for the contract and
``docs/SECURITY.md`` §3.6.2 for what each decision became here.
"""

from __future__ import annotations

import base64
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlsplit

from dateutil.relativedelta import relativedelta
from django.conf import settings

from apps.core.cold_storage_backends import (
    MANIFEST_SUFFIX,
    PAYLOAD_SUFFIX,
    ColdStorageError,
    FetchedCopy,
    FetchPending,
    manifest_name_for,
)
from apps.core.file_digest import sha256_file

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

    def _check_locked(self, head: dict[str, Any], what: str) -> None:
        mode = head.get("ObjectLockMode")
        if mode != "COMPLIANCE":
            raise ColdStorageError(
                f"stored {what} has Object Lock mode {mode!r}, not COMPLIANCE — "
                "it could be deleted before the retention ends"
            )
        until = head.get("ObjectLockRetainUntilDate")
        minimum = self._retain_until() - timedelta(days=1)
        if until is None or until < minimum:
            raise ColdStorageError(
                f"stored {what} is locked until {until}, short of the "
                f"{self.lock_months}-month retain-until ({minimum:%Y-%m-%d})"
            )

    def verify_stored(self, location: str, expected_sha256_ciphertext: str) -> None:
        """Re-read the stored objects' metadata — never their bodies: in
        GLACIER the body is not readable without a restore. For the payload:
        checksum, lock mode and lock length of the exact version the receipt
        points to. For the manifest (the drill cannot prove the copy without
        it): that the service holds a SHA-256 for it, and the same lock."""
        key, versions = self._pinned(location)
        head = self._head(key, versions["versionId"], ChecksumMode="ENABLED")
        expected = _b64_of_hex(expected_sha256_ciphertext)
        if head.get("ChecksumSHA256") != expected:
            raise ColdStorageError(
                f"stored object {location!r} does not match what was written "
                f"(sha256 {head.get('ChecksumSHA256')} != {expected}) — refusing to trust it"
            )
        self._check_locked(head, f"object {location!r}")

        manifest_key = str(Path(key).with_name(manifest_name_for(Path(key).name)))
        manifest_head = self._head(
            manifest_key, versions["manifestVersionId"], ChecksumMode="ENABLED"
        )
        if not manifest_head.get("ChecksumSHA256"):
            raise ColdStorageError(
                f"stored manifest s3://{self.bucket}/{manifest_key} has no SHA-256 checksum — "
                "it was not written by this backend"
            )
        self._check_locked(manifest_head, f"manifest s3://{self.bucket}/{manifest_key}")

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

    def _request_restore(self, key: str, version: str, location: str) -> FetchPending:
        from botocore.exceptions import BotoCoreError, ClientError

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

    def _pending_restore(self, key: str, version: str, location: str) -> FetchPending | None:
        """Glacier cycle: None when the body is readable now; otherwise the
        restore is requested (first run) or still running (later runs)."""
        head = self._head(key, version)
        if head.get("StorageClass") not in _ARCHIVE_CLASSES:
            return None
        restore = head.get("Restore")
        if not restore:
            return self._request_restore(key, version, location)
        if 'ongoing-request="true"' in restore:
            return FetchPending(f"restauração em andamento para {location}")
        return None

    def fetch(self, location: str, dest_dir: Path) -> FetchedCopy | FetchPending:
        key, versions = self._pinned(location)
        version = versions["versionId"]
        pending = self._pending_restore(key, version, location)
        if pending is not None:
            return pending
        manifest_key = str(Path(key).with_name(manifest_name_for(Path(key).name)))
        return FetchedCopy(
            payload_path=self._download(key, version, dest_dir / Path(key).name),
            manifest_path=self._download(
                manifest_key, versions["manifestVersionId"], dest_dir / Path(manifest_key).name
            ),
        )
