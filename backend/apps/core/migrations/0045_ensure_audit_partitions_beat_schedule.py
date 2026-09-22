"""Data migration — register the daily Celery Beat schedule for
``core.ensure_audit_partitions`` (ordem 021, Emenda do Imediato).

Mirrors emr migration 0023 / pharmacy migration 0012: DatabaseScheduler
ignores the settings dict unless the PeriodicTask DB row exists, so this
migration creates it reliably (get_or_create -> idempotent).

Runs daily at 00:15 UTC — after midnight, so "this month" already means the
new month on the first day it matters, and (given the task itself pre-creates
BOTH the current and the next month for every tenant) a day's slack either
side of midnight changes nothing. The task wrapper
(apps.core.tasks.ensure_audit_partitions) is a thin, idempotent call into the
``ensure_audit_partitions`` management command — never touches the DB from
CoreConfig.ready() (see that command's docstring for why not).
"""

from django.db import migrations

_TASK_NAME = "core.ensure_audit_partitions"


def register(apps, schema_editor):
    try:
        CrontabSchedule = apps.get_model("django_celery_beat", "CrontabSchedule")
        PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    except LookupError:
        return

    cron, _ = CrontabSchedule.objects.get_or_create(
        minute="15",
        hour="0",
        day_of_week="*",
        day_of_month="*",
        month_of_year="*",
    )
    PeriodicTask.objects.get_or_create(
        name=_TASK_NAME,
        defaults={
            "task": _TASK_NAME,
            "crontab": cron,
            "enabled": True,
            "description": (
                "Ordem 021: pré-cria a partição do mês corrente e do seguinte de "
                "core_auditlog para cada tenant, e alerta se alguma linha estiver "
                "em folha DEFAULT (partição faltando)."
            ),
        },
    )


def unregister(apps, schema_editor):
    try:
        PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    except LookupError:
        return
    PeriodicTask.objects.filter(name=_TASK_NAME).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0044_tenant_audit_retention"),
        ("django_celery_beat", "0018_improve_crontab_helptext"),
    ]

    operations = [
        migrations.RunPython(register, unregister),
    ]
