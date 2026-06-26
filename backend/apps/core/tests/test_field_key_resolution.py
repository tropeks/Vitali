"""
Tests for resolve_field_encryption_key() — the runtime-secret-file resolver
(P3-02) and the KMS/envelope seam introduced in vitali/settings/_secrets.py.

Covers:
  - env var is used when FIELD_ENCRYPTION_KEY_FILE is not set
  - file takes precedence over the env var when FIELD_ENCRYPTION_KEY_FILE is set
  - trailing whitespace/newlines are stripped (Fernet is whitespace-sensitive)
  - a non-existent file path raises ImproperlyConfigured (never silently falls back)
  - an empty or whitespace-only file raises ImproperlyConfigured
  - when neither env var nor file is set, the all-zero _FERNET_ZERO_KEY placeholder
    is returned so dev/CI/migrations still boot
  - settings.FIELD_ENCRYPTION_KEY is a non-empty string under dev settings
"""

from __future__ import annotations

import os
import tempfile

from django.test import SimpleTestCase

from vitali.settings._security_checks import _FERNET_ZERO_KEY

# ─── Fake env shim ───────────────────────────────────────────────────────────
# Mirrors the subset of environ.Env that resolve_field_encryption_key() calls.
# Avoids touching os.environ in any test.

_REAL_KEY_A = "dGVzdGtleXRlc3RrZXl0ZXN0a2V5dGVzdGtleXRlc3Q="  # K1 — 32-byte base64
_REAL_KEY_B = "YWx0ZXJuYXRlS2V5YWx0ZXJuYXRlS2V5YWx0ZXJuYQ=="  # K2 — different key


class _FakeEnv:
    """Minimal shim that implements env.str(name, default='') used by the resolver."""

    def __init__(self, mapping: dict[str, str]):
        self._mapping = mapping

    def str(self, name: str, default: str = "") -> str:  # noqa: A003
        return self._mapping.get(name, default)


# ─── Unit tests for resolve_field_encryption_key ─────────────────────────────


class FieldKeyResolutionTests(SimpleTestCase):
    """Unit tests for resolve_field_encryption_key using the fake env shim."""

    def _resolve(self, mapping: dict[str, str]) -> str:
        from vitali.settings._secrets import resolve_field_encryption_key

        return resolve_field_encryption_key(_FakeEnv(mapping))

    # ─── Env var path ─────────────────────────────────────────────────────────

    def test_env_var_used_when_no_file(self):
        """When FIELD_ENCRYPTION_KEY_FILE is empty, resolver returns the env var key."""
        result = self._resolve(
            {
                "FIELD_ENCRYPTION_KEY": _REAL_KEY_A,
                "FIELD_ENCRYPTION_KEY_FILE": "",
            }
        )
        self.assertEqual(result, _REAL_KEY_A)

    # ─── File-takes-precedence path ───────────────────────────────────────────

    def test_file_takes_precedence_over_env(self):
        """When FIELD_ENCRYPTION_KEY_FILE is set, the file value wins over the env var."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".key", delete=False) as f:
            f.write(_REAL_KEY_A)
            path = f.name
        try:
            result = self._resolve(
                {
                    "FIELD_ENCRYPTION_KEY_FILE": path,
                    "FIELD_ENCRYPTION_KEY": _REAL_KEY_B,  # different — must be ignored
                }
            )
            self.assertEqual(result, _REAL_KEY_A)
        finally:
            os.unlink(path)

    def test_file_contents_are_stripped(self):
        """Trailing whitespace and newlines are stripped before returning."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".key", delete=False) as f:
            f.write(_REAL_KEY_A + "\n")
            path = f.name
        try:
            result = self._resolve({"FIELD_ENCRYPTION_KEY_FILE": path})
            self.assertEqual(result, _REAL_KEY_A)
            self.assertNotIn("\n", result)
        finally:
            os.unlink(path)

    # ─── Error paths ──────────────────────────────────────────────────────────

    def test_missing_file_path_raises(self):
        """A non-existent file path must raise ImproperlyConfigured — no silent fallback."""
        from django.core.exceptions import ImproperlyConfigured

        with self.assertRaises(ImproperlyConfigured):
            self._resolve(
                {
                    "FIELD_ENCRYPTION_KEY_FILE": "/nonexistent/path/to/field.key",
                    "FIELD_ENCRYPTION_KEY": _REAL_KEY_A,  # must NOT fall back to this
                }
            )

    def test_missing_file_error_mentions_path(self):
        """The ImproperlyConfigured message must include the missing path so operators can debug."""
        from django.core.exceptions import ImproperlyConfigured

        bad_path = "/nonexistent/path/to/field.key"
        with self.assertRaises(ImproperlyConfigured) as ctx:
            self._resolve({"FIELD_ENCRYPTION_KEY_FILE": bad_path})
        self.assertIn(bad_path, str(ctx.exception))

    def test_empty_file_raises(self):
        """An empty (or whitespace-only) secret file must raise ImproperlyConfigured."""
        from django.core.exceptions import ImproperlyConfigured

        with tempfile.NamedTemporaryFile(mode="w", suffix=".key", delete=False) as f:
            f.write("   \n")  # whitespace only — strips to ""
            path = f.name
        try:
            with self.assertRaises(ImproperlyConfigured):
                self._resolve({"FIELD_ENCRYPTION_KEY_FILE": path})
        finally:
            os.unlink(path)

    # ─── Default/placeholder path ─────────────────────────────────────────────

    def test_returns_default_when_neither_set(self):
        """When neither env var nor file is set, resolver returns _FERNET_ZERO_KEY (dev/CI boot)."""
        result = self._resolve({})
        self.assertEqual(result, _FERNET_ZERO_KEY)

    # ─── Settings smoke test ──────────────────────────────────────────────────


class FieldKeySettingsSmokeTest(SimpleTestCase):
    """Verify settings.FIELD_ENCRYPTION_KEY is wired through the resolver in base.py."""

    def test_settings_field_encryption_key_present(self):
        """settings.FIELD_ENCRYPTION_KEY must be a non-empty string under dev settings."""
        from django.conf import settings

        self.assertIsInstance(settings.FIELD_ENCRYPTION_KEY, str)
        self.assertTrue(
            len(settings.FIELD_ENCRYPTION_KEY) > 0,
            "settings.FIELD_ENCRYPTION_KEY must not be empty",
        )
