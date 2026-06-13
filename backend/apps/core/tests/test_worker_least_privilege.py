"""
Tests for P3-03: worker least-privilege — process role label (VITALI_ROLE) and
separate, less-privileged Celery DB DSN (CELERY_DATABASE_URL).

Design choice: base.py exposes DATABASE_URL (raw string, same default as
DATABASES["default"]) and CELERY_DATABASE_URL (raw string, default "") as
settings. The check reads settings.DATABASE_URL and settings.CELERY_DATABASE_URL
to compare them — keeping the check independent of the live DATABASES dict.

Covers:
  - assert_worker_database_separation validator
  - check_worker_least_privilege system check (core.E004, prod-gated + worker-gated)
  - VITALI_ROLE / IS_CELERY_WORKER defaults under dev settings
"""

from __future__ import annotations

from django.test import SimpleTestCase, override_settings


# ─── Validator unit tests ─────────────────────────────────────────────────────


class WorkerDatabaseSeparationValidatorTests(SimpleTestCase):
    """Unit tests for assert_worker_database_separation in _security_checks."""

    _DSN_A = "postgres://vitali:secret@postgres:5432/vitali"
    _DSN_B = "postgres://vitali_worker:w0rker@postgres:5432/vitali"

    def setUp(self):
        from vitali.settings._security_checks import assert_worker_database_separation

        self.assert_sep = assert_worker_database_separation

    # ─── web role — always a no-op ────────────────────────────────────────────

    def test_web_role_empty_celery_dsn_no_raise(self):
        """Web role with empty CELERY_DATABASE_URL must not raise."""
        self.assert_sep("web", self._DSN_A, "")  # must not raise

    def test_web_role_same_dsn_no_raise(self):
        """Web role with identical DSNs must not raise — web is not least-privileged."""
        self.assert_sep("web", self._DSN_A, self._DSN_A)  # must not raise

    def test_web_role_distinct_dsn_no_raise(self):
        """Web role with a distinct CELERY_DATABASE_URL must still not raise."""
        self.assert_sep("web", self._DSN_A, self._DSN_B)  # must not raise

    # ─── worker role — distinct DSN passes ───────────────────────────────────

    def test_worker_role_distinct_celery_dsn_no_raise(self):
        """Worker role with a distinct CELERY_DATABASE_URL must not raise."""
        self.assert_sep("worker", self._DSN_A, self._DSN_B)  # must not raise

    # ─── worker role — missing or same DSN raises ────────────────────────────

    def test_worker_role_empty_celery_dsn_raises(self):
        """Worker role with empty CELERY_DATABASE_URL must raise ImproperlyConfigured."""
        from django.core.exceptions import ImproperlyConfigured

        with self.assertRaises(ImproperlyConfigured):
            self.assert_sep("worker", self._DSN_A, "")

    def test_worker_role_same_dsn_raises(self):
        """Worker role with CELERY_DATABASE_URL == DATABASE_URL must raise ImproperlyConfigured."""
        from django.core.exceptions import ImproperlyConfigured

        with self.assertRaises(ImproperlyConfigured):
            self.assert_sep("worker", self._DSN_A, self._DSN_A)

    # ─── beat role — same gating as worker ───────────────────────────────────

    def test_beat_role_empty_celery_dsn_raises(self):
        """Beat role with empty CELERY_DATABASE_URL must raise ImproperlyConfigured."""
        from django.core.exceptions import ImproperlyConfigured

        with self.assertRaises(ImproperlyConfigured):
            self.assert_sep("beat", self._DSN_A, "")

    def test_beat_role_same_dsn_raises(self):
        """Beat role with CELERY_DATABASE_URL == DATABASE_URL must raise ImproperlyConfigured."""
        from django.core.exceptions import ImproperlyConfigured

        with self.assertRaises(ImproperlyConfigured):
            self.assert_sep("beat", self._DSN_A, self._DSN_A)

    def test_beat_role_distinct_dsn_no_raise(self):
        """Beat role with a distinct CELERY_DATABASE_URL must not raise."""
        self.assert_sep("beat", self._DSN_A, self._DSN_B)  # must not raise

    # ─── error message mentions least-privilege / separate DB user ────────────

    def test_error_message_mentions_separate_db_user(self):
        """ImproperlyConfigured message must mention a separate DB user / least privilege."""
        from django.core.exceptions import ImproperlyConfigured

        with self.assertRaises(ImproperlyConfigured) as ctx:
            self.assert_sep("worker", self._DSN_A, "")
        msg = str(ctx.exception)
        # The message must guide the operator: separate Postgres user, least privilege.
        self.assertTrue(
            "least" in msg.lower() or "separate" in msg.lower() or "CELERY_DATABASE_URL" in msg,
            f"Error message should mention least-privilege or separate DSN: {msg!r}",
        )


# ─── Production system check tests ───────────────────────────────────────────


class WorkerLeastPrivilegeCheckTests(SimpleTestCase):
    """Direct unit tests — call check_worker_least_privilege with override_settings.

    The check reads: ENVIRONMENT, IS_CELERY_WORKER, DATABASE_URL, CELERY_DATABASE_URL.
    """

    _DSN_WEB = "postgres://vitali:secret@postgres:5432/vitali"
    _DSN_WORKER = "postgres://vitali_worker:w0rker@postgres:5432/vitali"

    def _run(self, **settings_overrides):
        """Apply overrides and call the check function directly."""
        from apps.core.checks import check_worker_least_privilege

        with override_settings(**settings_overrides):
            return check_worker_least_privilege(app_configs=None)

    # ─── production + worker + identical DSNs → core.E004 ────────────────────

    def test_production_worker_empty_celery_dsn_returns_e004(self):
        """Production + IS_CELERY_WORKER=True + empty CELERY_DATABASE_URL → core.E004."""
        errors = self._run(
            ENVIRONMENT="production",
            IS_CELERY_WORKER=True,
            DATABASE_URL=self._DSN_WEB,
            CELERY_DATABASE_URL="",
        )
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].id, "core.E004")

    def test_production_worker_same_dsn_returns_e004(self):
        """Production + IS_CELERY_WORKER=True + CELERY_DATABASE_URL == DATABASE_URL → core.E004."""
        errors = self._run(
            ENVIRONMENT="production",
            IS_CELERY_WORKER=True,
            DATABASE_URL=self._DSN_WEB,
            CELERY_DATABASE_URL=self._DSN_WEB,
        )
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].id, "core.E004")

    # ─── production + worker + distinct CELERY_DATABASE_URL → no errors ──────

    def test_production_worker_distinct_dsn_returns_no_errors(self):
        """Production + IS_CELERY_WORKER=True + distinct CELERY_DATABASE_URL → no errors."""
        errors = self._run(
            ENVIRONMENT="production",
            IS_CELERY_WORKER=True,
            DATABASE_URL=self._DSN_WEB,
            CELERY_DATABASE_URL=self._DSN_WORKER,
        )
        self.assertEqual(errors, [])

    # ─── production + web (IS_CELERY_WORKER=False) → no errors ──────────────

    def test_production_web_returns_no_errors(self):
        """Production + IS_CELERY_WORKER=False (web) must not return errors."""
        errors = self._run(
            ENVIRONMENT="production",
            IS_CELERY_WORKER=False,
            DATABASE_URL=self._DSN_WEB,
            CELERY_DATABASE_URL="",
        )
        self.assertEqual(errors, [])

    # ─── development + worker + identical → no errors (prod-gated) ───────────

    def test_development_worker_identical_dsn_returns_no_errors(self):
        """Development + worker + identical DSNs must return no errors (check is prod-gated)."""
        errors = self._run(
            ENVIRONMENT="development",
            IS_CELERY_WORKER=True,
            DATABASE_URL=self._DSN_WEB,
            CELERY_DATABASE_URL="",
        )
        self.assertEqual(errors, [])

    # ─── error id is exactly core.E004 ───────────────────────────────────────

    def test_error_id_is_core_e004(self):
        """The error id must be exactly 'core.E004'."""
        errors = self._run(
            ENVIRONMENT="production",
            IS_CELERY_WORKER=True,
            DATABASE_URL=self._DSN_WEB,
            CELERY_DATABASE_URL="",
        )
        self.assertEqual(errors[0].id, "core.E004")


# ─── Settings smoke tests ─────────────────────────────────────────────────────


class WorkerRoleSettingsDefaults(SimpleTestCase):
    """Smoke-test that VITALI_ROLE and IS_CELERY_WORKER are wired in base.py."""

    def test_vitali_role_defaults_to_web(self):
        """Under dev settings, VITALI_ROLE must default to 'web'."""
        from django.conf import settings

        self.assertEqual(settings.VITALI_ROLE, "web")

    def test_is_celery_worker_defaults_false(self):
        """Under dev settings, IS_CELERY_WORKER must default to False."""
        from django.conf import settings

        self.assertIs(settings.IS_CELERY_WORKER, False)


# ─── Live worker-DSN override tests (exercise base.py, not just the validator) ──


class WorkerDsnOverrideTests(SimpleTestCase):
    """Load base.py in a fresh process with worker env vars set and assert the
    live DATABASES["default"] is what the worker actually runs with.

    The validator/check tests above never execute the base.py override branch
    (`if IS_CELERY_WORKER and CELERY_DATABASE_URL:`). This class does, via a
    subprocess that imports the real settings — the only way to catch a regression
    where env.db() clobbers ENGINE=django_tenants.postgresql_backend (which would
    silently break per-schema search_path switching for every worker/beat).
    """

    _DSN_WORKER = "postgres://vitali_worker:w0rker@postgres:5432/vitali"

    def _load_settings_db(self, **env_overrides):
        """Spawn python, set env, import dev settings, return DATABASES['default']."""
        import json
        import os
        import subprocess
        import sys

        code = (
            "import json; from django.conf import settings; "
            "print(json.dumps(settings.DATABASES['default']))"
        )
        env = os.environ.copy()
        env["DJANGO_SETTINGS_MODULE"] = "vitali.settings.development"
        env.update(env_overrides)
        # Run from the backend dir so `vitali` is importable (cwd of the suite).
        proc = subprocess.run(
            [sys.executable, "-c", "import django; django.setup(); " + code],
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertEqual(
            proc.returncode, 0, f"subprocess failed: {proc.stderr or proc.stdout}"
        )
        return json.loads(proc.stdout.strip().splitlines()[-1])

    def test_worker_override_preserves_tenants_engine(self):
        """Worker + CELERY_DATABASE_URL must keep the django-tenants ENGINE.

        Regression guard: env.db() returns ENGINE=django.db.backends.postgresql;
        the override must re-assert django_tenants.postgresql_backend afterward.
        """
        db = self._load_settings_db(
            VITALI_ROLE="worker", CELERY_DATABASE_URL=self._DSN_WORKER
        )
        self.assertEqual(db["ENGINE"], "django_tenants.postgresql_backend")

    def test_worker_override_applies_worker_dsn(self):
        """The worker DSN actually takes effect (distinct user from the web tier)."""
        db = self._load_settings_db(
            VITALI_ROLE="worker", CELERY_DATABASE_URL=self._DSN_WORKER
        )
        self.assertEqual(db["USER"], "vitali_worker")

    def test_web_role_keeps_default_dsn_and_engine(self):
        """Web tier (no override) keeps the default DATABASE_URL and tenants ENGINE."""
        db = self._load_settings_db(VITALI_ROLE="web", CELERY_DATABASE_URL=self._DSN_WORKER)
        self.assertEqual(db["ENGINE"], "django_tenants.postgresql_backend")
        self.assertNotEqual(db["USER"], "vitali_worker")
