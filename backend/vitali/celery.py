import logging
import os
from typing import TYPE_CHECKING

from celery import Celery
from celery.schedules import crontab
from celery.signals import (
    before_task_publish,
    task_postrun,
    task_prerun,
    worker_process_init,
)

if TYPE_CHECKING:
    from django_tenants.utils import schema_context as _SchemaContext

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "vitali.settings.development")

app = Celery("vitali")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.conf.imports = (
    "apps.emr.tasks_waitlist",
    "apps.core.tasks_wedge_value",
)
app.autodiscover_tasks()

logger = logging.getLogger(__name__)

# ─── Tenant-schema propagation (Onda 1, item 1.7) ────────────────────────────
#
# PROBLEM: apps/*/tasks.py enqueue by-ID tasks (check_prescription_safety,
# generate_soap_task, cascade_no_show, ...) from inside a tenant request, but
# .delay()/.apply_async() carries no schema information. A worker process
# reuses its DB connection across many tasks (CONN_MAX_AGE defaults to 0, but
# Celery tasks never go through Django's request/response cycle that closes
# it), so by the time the task body runs it observes whatever schema the
# connection was last left in — "public" for a fresh connection, or a stale
# tenant's schema if a prior task's cleanup didn't run. Both are wrong.
#
# FIX: two signal handlers, wired once here, transparent to every task
# regardless of how it declares itself (@shared_task, no custom base needed):
#   - before_task_publish stamps the *publishing* process's current
#     connection.schema_name onto the outgoing message headers. This covers
#     requests (tenant schema active), Celery beat (schema_name == "public"),
#     and task chains fired from inside a worker (whatever schema the parent
#     task's task_prerun entered).
#   - task_prerun reads that header on the *consuming* side and enters
#     schema_context(schema_name) before the task body runs; task_postrun
#     restores the previous schema afterwards, in a finally-equivalent
#     position (Celery always sends task_postrun, success or failure).
#
# A schema of "public" is a normal, explicit value here — it's what
# for_each_tenant_schema-style scan tasks already run under, so stamping and
# restoring "public" is a no-op relative to today's behaviour.
#
# RETROCOMPATIBILITY: messages enqueued before this deploy carry no header.
# task_prerun logs a WARNING and leaves the connection's schema untouched
# (today's behaviour) instead of raising — the residue is finite (in-flight
# messages only) and this makes it visible in worker logs.
#
# KILL SWITCH: settings.CELERY_TENANT_PROPAGATION (env CELERY_TENANT_PROPAGATION,
# default True). When False, neither handler does anything — publishing skips
# the header and execution skips entering schema_context — which reproduces
# today's (buggy) behaviour exactly, for emergency rollback without a deploy.
TENANT_SCHEMA_HEADER = "vitali_tenant_schema"

# task_id -> the schema_context this task's task_prerun entered, so
# task_postrun can __exit__ the *same* context instance. Keyed by task_id
# (not a simple stack) because a single prefork worker process executes many
# tasks over its lifetime, one at a time, but the pairing must be exact even
# if signal ordering across tasks ever interleaves (e.g. non-prefork pools).
_active_schema_contexts: dict[str, "_SchemaContext"] = {}


def _tenant_propagation_enabled() -> bool:
    from django.conf import settings

    return bool(getattr(settings, "CELERY_TENANT_PROPAGATION", True))


@before_task_publish.connect
def _stamp_tenant_schema(sender=None, headers=None, **kwargs):
    """Carimba o schema do processo que está enfileirando na mensagem."""
    if not _tenant_propagation_enabled():
        return
    if headers is None:
        # Defensive: celery always passes a dict here, but never crash the
        # publish path over an instrumentation detail.
        return

    from django.db import connection

    headers[TENANT_SCHEMA_HEADER] = getattr(connection, "schema_name", "public")


@task_prerun.connect
def _enter_tenant_schema(sender=None, task_id=None, task=None, **kwargs):
    """Reentra no schema carimbado no enfileiramento antes do corpo da tarefa rodar."""
    if not _tenant_propagation_enabled():
        return
    if task is None or task_id is None:
        return

    request_headers = getattr(task.request, "headers", None) or {}
    schema_name = request_headers.get(TENANT_SCHEMA_HEADER)
    if schema_name is None:
        logger.warning(
            "Celery task %s (%s) has no %r header — running without tenant "
            "schema propagation. Expected only for messages enqueued before "
            "this deploy, or while CELERY_TENANT_PROPAGATION was disabled at "
            "publish time.",
            task.name,
            task_id,
            TENANT_SCHEMA_HEADER,
        )
        return

    from django_tenants.utils import schema_context

    ctx = schema_context(schema_name)
    ctx.__enter__()
    _active_schema_contexts[task_id] = ctx


@task_postrun.connect
def _exit_tenant_schema(sender=None, task_id=None, **kwargs):
    """Restaura o schema anterior, sempre — inclusive quando a tarefa levantou exceção.

    task_postrun is sent from a finally block in celery.app.trace.trace_task,
    so this runs for successful, retried, and failed tasks alike.
    """
    ctx = _active_schema_contexts.pop(task_id, None)
    if ctx is not None:
        ctx.__exit__(None, None, None)


@worker_process_init.connect
def _bootstrap_otel(**kwargs):
    from vitali.observability import setup_observability

    setup_observability("worker")


# ─── Periodic tasks (S-055/S-056) ────────────────────────────────────────────
app.conf.beat_schedule = {
    # Expire pending PIX charges every 5 minutes
    "expire-pix-charges": {
        "task": "apps.billing.services.tasks.expire_pix_charges",
        "schedule": crontab(minute="*/5"),
    },
    # Send 24h appointment reminders daily at 08:00 (America/Sao_Paulo)
    "send-appointment-reminders": {
        "task": "apps.billing.services.tasks.send_appointment_reminders",
        "schedule": crontab(hour=8, minute=0),
    },
    # S-066: Check for expired waitlist notifications every 5 minutes
    "expire-waitlist-notifications": {
        "task": "apps.emr.tasks_waitlist.expire_waitlist_notifications",
        "schedule": crontab(minute="*/5"),
    },
    # E-012: Poll Orthanc PACS and backfill DicomStudy.orthanc_study_id.
    # No-ops when ORTHANC_URL is empty (feature inert).
    "sync-orthanc-studies": {
        "task": "imaging.sync_orthanc_studies",
        "schedule": crontab(minute="*/3"),
    },
    # Issue #123: daily per-tenant wedge business-value (ROI) snapshot at 04:20 UTC
    # (quiet hour). Computes metrics inside each tenant schema and writes
    # WedgeValueSnapshot rows the platform dashboard serves without per-request
    # schema fan-out.
    "snapshot-wedge-value": {
        "task": "core.snapshot_wedge_value",
        "schedule": crontab(hour=4, minute=20),
    },
}
