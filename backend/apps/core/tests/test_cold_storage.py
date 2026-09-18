"""
Cold export sequence for core_auditlog partitions (order 020, Capitão's amendment).

Covers: the happy path (export -> encrypt -> local verify -> store -> verify
stored), the missing-key refusal, and the negative controls the amendment
explicitly asks for — a corrupted round trip must be REFUSED, by name,
BEFORE anything is written to the storage backend.
"""

import datetime
from pathlib import Path
from unittest import mock

from django.db import connection
from django.test import TestCase, override_settings

from apps.core import cold_storage, gpg_crypto, partitioning
from apps.core.cold_storage_backends import ColdStorageError, LocalDiskColdStorageBackend

TEST_KEY = "order-020-test-passphrase-do-not-use-in-prod"


def _seed_one_row(schema_name: str = "acme") -> str:
    for_date = datetime.date(2028, 4, 12)
    leaf = partitioning.ensure_tenant_partition(for_date, schema_name)
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO core_auditlog (action, resource_type, resource_id, created_at, schema_name) "
            "VALUES ('login', 'user', '1', %s, %s)",
            [datetime.datetime(2028, 4, 12, tzinfo=datetime.UTC), schema_name],
        )
    return leaf


@override_settings(BACKUP_ENCRYPTION_KEY=TEST_KEY)
class ExportAndVerifyHappyPathTests(TestCase):
    def test_receipt_is_verified_and_manifest_is_complete(self):
        leaf = _seed_one_row()
        with override_settings(AUDIT_LOG_COLD_STORAGE_DIR=self._tmp_dir()):
            receipt = cold_storage.export_and_verify_partition(leaf)

        self.assertTrue(receipt.verified)
        self.assertEqual(receipt.partition_name, leaf)
        self.assertEqual(receipt.manifest["row_count"], 1)
        self.assertEqual(receipt.manifest["schema_names"], ["acme"])
        for key in (
            "format_version",
            "tool_version",
            "exported_at",
            "sha256_plain",
            "sha256_cipher",
            "created_at_min",
            "created_at_max",
        ):
            self.assertIn(key, receipt.manifest)
        self.assertTrue(Path(receipt.stored_location).is_file())

    def _tmp_dir(self):
        import tempfile

        d = tempfile.mkdtemp(prefix="auditlog-cold-test-")
        self.addCleanup(lambda: __import__("shutil").rmtree(d, ignore_errors=True))
        return d


class MissingKeyTests(TestCase):
    @override_settings(BACKUP_ENCRYPTION_KEY="")
    def test_refuses_without_backup_encryption_key(self):
        leaf = _seed_one_row()
        with self.assertRaises(cold_storage.ColdExportError) as ctx:
            cold_storage.export_and_verify_partition(leaf)
        self.assertIn("BACKUP_ENCRYPTION_KEY", str(ctx.exception))


@override_settings(BACKUP_ENCRYPTION_KEY=TEST_KEY)
class NegativeControlTests(TestCase):
    """Prove the verification step can and does say no — a verification that
    never sees red is not a verification (order 020, Capitão's amendment).
    """

    def test_corrupted_decrypt_is_refused_before_anything_is_stored(self):
        leaf = _seed_one_row(schema_name="beta")
        stored = mock.Mock(wraps=LocalDiskColdStorageBackend())

        real_decrypt = gpg_crypto.decrypt_file

        def tampered_decrypt(ciphertext_path, out_path, *, passphrase, gnupg_home):
            # Decrypt for real, then flip a byte — simulates a bit-rotted or
            # tampered artifact making it past encryption but failing the
            # plaintext round trip.
            real_decrypt(ciphertext_path, out_path, passphrase=passphrase, gnupg_home=gnupg_home)
            data = bytearray(Path(out_path).read_bytes())
            data[0:1] = b"X" if data[0:1] != b"X" else b"Y"
            Path(out_path).write_bytes(bytes(data))

        with mock.patch.object(gpg_crypto, "decrypt_file", side_effect=tampered_decrypt):
            with self.assertRaises(cold_storage.ColdExportError) as ctx:
                cold_storage.export_and_verify_partition(leaf, backend=stored)

        self.assertIn("local verification", str(ctx.exception))
        stored.store.assert_not_called()

    def test_gpg_decrypt_failure_is_refused_and_named(self):
        leaf = _seed_one_row(schema_name="gamma")
        stored = mock.Mock(wraps=LocalDiskColdStorageBackend())

        with mock.patch.object(
            gpg_crypto, "decrypt_file", side_effect=gpg_crypto.GpgError("bad session key")
        ):
            with self.assertRaises(cold_storage.ColdExportError) as ctx:
                cold_storage.export_and_verify_partition(leaf, backend=stored)

        self.assertIn("bad session key", str(ctx.exception))
        stored.store.assert_not_called()

    def test_content_divergence_between_live_and_restored_is_refused(self):
        # Simulates a bug upstream of encryption (e.g. the export query
        # dropping/mangling a row): the plaintext round-trips (checksum OK)
        # but what got restored into the scratch table no longer matches the
        # live partition. Patch the restore step to plant one extra,
        # non-matching row after the real restore — same row count trap as
        # test_auditlog_migration_support's content-mismatch case, exercised
        # here through the public export_and_verify_partition entry point.
        leaf = _seed_one_row(schema_name="delta")
        stored = mock.Mock(wraps=LocalDiskColdStorageBackend())
        real_restore = cold_storage._restore_rows_to_scratch

        def poisoned_restore(scratch, plaintext_path, cur):
            real_restore(scratch, plaintext_path, cur)
            cur.execute(
                f'INSERT INTO "{scratch}" (id, action, resource_type, resource_id, created_at, schema_name) '
                "VALUES (999999, 'create', 'patient', 'planted', now(), 'delta')"
            )

        with mock.patch.object(
            cold_storage, "_restore_rows_to_scratch", side_effect=poisoned_restore
        ):
            with self.assertRaises(cold_storage.ColdExportError) as ctx:
                cold_storage.export_and_verify_partition(leaf, backend=stored)

        self.assertIn("restore-and-compare failed", str(ctx.exception))
        stored.store.assert_not_called()


@override_settings(BACKUP_ENCRYPTION_KEY=TEST_KEY)
class LocalDiskBackendVerifyTests(TestCase):
    def test_verify_stored_detects_a_corrupted_copy(self):
        import shutil
        import tempfile

        tmp = tempfile.mkdtemp(prefix="auditlog-cold-verify-test-")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        backend = LocalDiskColdStorageBackend(directory=Path(tmp))

        payload = Path(tmp) / "in.jsonl.gpg"
        payload.write_bytes(b"ciphertext-bytes")
        manifest = Path(tmp) / "in.manifest.json"
        manifest.write_text("{}")

        location = backend.store(payload_path=payload, manifest_path=manifest, key_prefix="p")
        # Corrupt the file that was just stored.
        Path(location).write_bytes(b"corrupted!!")

        from apps.core.file_digest import sha256_file

        expected = sha256_file(payload)  # the ORIGINAL (uncorrupted) checksum
        with self.assertRaises(ColdStorageError):
            backend.verify_stored(location, expected)
