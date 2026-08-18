"""
Tests for Celery tenant-schema propagation (Onda 1, item 1.7).

THE BLIND SPOT THIS FIXES: apps/*/tasks.py enqueue by-ID tasks
(check_prescription_safety, generate_soap_task, cascade_no_show, ...) from
inside a tenant request, passing only the object's id — no schema
information travels with the message. A worker process reuses its DB
connection across many tasks, so the task body observes whatever schema the
connection was last left in, not the tenant that enqueued it. This is
invisible under ``CELERY_TASK_ALWAYS_EAGER=True`` (used by most of the
suite, e.g. apps/emr/tests/test_integration_appointment_failopen.py) because
eager mode runs the task body inline, inside the caller's already-active
schema — no message, no worker, no bug.

These tests deliberately run with ``CELERY_TASK_ALWAYS_EAGER=False`` and
exercise the publish/execute boundary the way a real worker does:
  - publish-side: a real (non-eager) ``apply_async()`` over kombu's in-memory
    transport (``memory://``), inspecting the actual bytes-on-the-wire
    message headers — no broker process required.
  - execution-side: ``task_prerun``/``task_postrun`` are sent directly, with
    ``Task.push_request()`` standing in for the message a real worker would
    have received (this is the supported way to synthesize a task's
    ``self.request`` outside of a full worker loop).

Both signal handlers under test (``vitali.celery._stamp_tenant_schema`` and
``vitali.celery._enter_tenant_schema`` / ``_exit_tenant_schema``) are wired
globally in vitali/celery.py — nothing here imports or patches a specific
app's tasks.py.
"""

import os
import uuid
from unittest import mock

from celery import shared_task
from celery.signals import task_postrun, task_prerun
from django.db import connection
from django.test import SimpleTestCase, override_settings
from django_tenants.utils import schema_context
from kombu import Connection as KombuConnection

from vitali.celery import TENANT_SCHEMA_HEADER
from vitali.celery import _active_schema_contexts as _leak_tracker
from vitali.celery import app as celery_app


@shared_task(name="core.tests.tenant_propagation_probe")
def _probe_task():
    """Minimal task body — only used as a target for apply_async/push_request."""
    return connection.schema_name


def _drain(queue_name: str) -> dict:
    """Pop the single message published to ``queue_name`` on the memory:// broker
    and return its headers (the dict our before_task_publish handler mutates)."""
    with KombuConnection("memory://") as conn:
        with conn.SimpleQueue(queue_name) as q:
            message = q.get(block=False)
            message.ack()
            return message.headers


@override_settings(CELERY_TENANT_PROPAGATION=True)
class CeleryTenantPropagationTests(SimpleTestCase):
    """CELERY_TASK_ALWAYS_EAGER=False throughout — see module docstring."""

    def setUp(self):
        super().setUp()
        # Settings.broker_url special-cases os.environ["CELERY_BROKER_URL"]
        # ahead of any app.conf value (see celery.app.utils.Settings.broker_url),
        # so the broker must be swapped via the environment, not app.conf.
        self._env_patch = mock.patch.dict(os.environ, {"CELERY_BROKER_URL": "memory://"})
        self._env_patch.start()
        self._orig_eager = celery_app.conf.task_always_eager
        celery_app.conf.task_always_eager = False

    def tearDown(self):
        celery_app.conf.task_always_eager = self._orig_eager
        self._env_patch.stop()
        # Defensive: never let one test's unpaired prerun leak a schema
        # context into the next test via the module-level tracking dict.
        _leak_tracker.clear()
        super().tearDown()

    def _unique_queue(self) -> str:
        return f"test-tenant-propagation-{uuid.uuid4()}"

    # ── (a) publish stamps the enqueuing schema ───────────────────────────

    def test_publish_from_tenant_schema_stamps_header(self):
        queue = self._unique_queue()
        with schema_context("tenant_alpha"):
            _probe_task.apply_async(queue=queue)

        headers = _drain(queue)
        self.assertEqual(headers.get(TENANT_SCHEMA_HEADER), "tenant_alpha")

    # ── (b) execution observes the enqueuing schema — fails without the fix ─

    def test_execution_enters_schema_from_published_header(self):
        task_id = str(uuid.uuid4())
        _probe_task.push_request(headers={TENANT_SCHEMA_HEADER: "tenant_beta"})
        try:
            with schema_context("public"):
                task_prerun.send(
                    sender=_probe_task, task_id=task_id, task=_probe_task, args=(), kwargs={}
                )
                try:
                    # This is the assertion that fails on unmodified
                    # celery.py: without task_prerun entering
                    # schema_context, the connection stays on "public".
                    self.assertEqual(connection.schema_name, "tenant_beta")
                finally:
                    task_postrun.send(
                        sender=_probe_task,
                        task_id=task_id,
                        task=_probe_task,
                        args=(),
                        kwargs={},
                        retval=None,
                        state="SUCCESS",
                    )
        finally:
            _probe_task.pop_request()

    # ── (c) schema is restored even when the task body raises ────────────

    def test_schema_restored_after_task_exception(self):
        task_id = str(uuid.uuid4())
        _probe_task.push_request(headers={TENANT_SCHEMA_HEADER: "tenant_gamma"})
        try:
            with schema_context("public"):
                baseline = connection.schema_name
                task_prerun.send(
                    sender=_probe_task, task_id=task_id, task=_probe_task, args=(), kwargs={}
                )
                self.assertEqual(connection.schema_name, "tenant_gamma")
                try:
                    raise ValueError("simulated task body failure")
                except ValueError:
                    pass
                finally:
                    # task_postrun is sent from a finally block in
                    # celery.app.trace.trace_task — always fires, success
                    # or failure. Mirrored here.
                    task_postrun.send(
                        sender=_probe_task,
                        task_id=task_id,
                        task=_probe_task,
                        args=(),
                        kwargs={},
                        retval=None,
                        state="FAILURE",
                    )
                self.assertEqual(connection.schema_name, baseline)
        finally:
            _probe_task.pop_request()

    # ── (d) legacy message (no header) does not explode ───────────────────

    def test_legacy_message_without_header_logs_warning_and_noops(self):
        task_id = str(uuid.uuid4())
        _probe_task.push_request()  # no headers at all — pre-deploy message
        try:
            with schema_context("tenant_delta"):
                baseline = connection.schema_name
                with self.assertLogs("vitali.celery", level="WARNING") as logs:
                    task_prerun.send(
                        sender=_probe_task, task_id=task_id, task=_probe_task, args=(), kwargs={}
                    )
                self.assertTrue(
                    any(TENANT_SCHEMA_HEADER in line for line in logs.output),
                    logs.output,
                )
                # No header -> no schema_context entered -> connection
                # untouched (today's behaviour, preserved on purpose).
                self.assertEqual(connection.schema_name, baseline)

                task_postrun.send(
                    sender=_probe_task,
                    task_id=task_id,
                    task=_probe_task,
                    args=(),
                    kwargs={},
                    retval=None,
                    state="SUCCESS",
                )
                self.assertEqual(connection.schema_name, baseline)
        finally:
            _probe_task.pop_request()

    # ── (e) public-schema enqueue keeps running in public ─────────────────

    def test_public_schema_publish_and_execution_stay_public(self):
        queue = self._unique_queue()
        with schema_context("public"):
            _probe_task.apply_async(queue=queue)
        headers = _drain(queue)
        self.assertEqual(headers.get(TENANT_SCHEMA_HEADER), "public")

        task_id = str(uuid.uuid4())
        _probe_task.push_request(headers={TENANT_SCHEMA_HEADER: "public"})
        try:
            with schema_context("public"):
                task_prerun.send(
                    sender=_probe_task, task_id=task_id, task=_probe_task, args=(), kwargs={}
                )
                self.assertEqual(connection.schema_name, "public")
                task_postrun.send(
                    sender=_probe_task,
                    task_id=task_id,
                    task=_probe_task,
                    args=(),
                    kwargs={},
                    retval=None,
                    state="SUCCESS",
                )
                self.assertEqual(connection.schema_name, "public")
        finally:
            _probe_task.pop_request()

    # ── (f) CELERY_TENANT_PROPAGATION=False restores old behaviour fully ──

    @override_settings(CELERY_TENANT_PROPAGATION=False)
    def test_flag_disabled_restores_legacy_behavior_on_both_sides(self):
        queue = self._unique_queue()
        with schema_context("tenant_epsilon"):
            _probe_task.apply_async(queue=queue)
        headers = _drain(queue)
        # Publish side: no header stamped at all when the flag is off.
        self.assertNotIn(TENANT_SCHEMA_HEADER, headers)

        # Execution side: even a message that *does* carry the header
        # (e.g. stamped before the flag was flipped off) is ignored —
        # the connection's schema is left exactly as the worker had it.
        task_id = str(uuid.uuid4())
        _probe_task.push_request(headers={TENANT_SCHEMA_HEADER: "tenant_epsilon"})
        try:
            with schema_context("tenant_baseline"):
                baseline = connection.schema_name
                task_prerun.send(
                    sender=_probe_task, task_id=task_id, task=_probe_task, args=(), kwargs={}
                )
                self.assertEqual(connection.schema_name, baseline)
                task_postrun.send(
                    sender=_probe_task,
                    task_id=task_id,
                    task=_probe_task,
                    args=(),
                    kwargs={},
                    retval=None,
                    state="SUCCESS",
                )
                self.assertEqual(connection.schema_name, baseline)
        finally:
            _probe_task.pop_request()
