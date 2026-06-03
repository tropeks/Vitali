"""Data migration — register the nightly flywheel Celery Beat task (wedge S4).

Creates one PeriodicTask in django_celery_beat:
  * pharmacy.grade_stockout_predictions — daily at 03:00 UTC

Mirrors apps/ai/migration 0004: DatabaseScheduler ignores the
``CELERY_BEAT_SCHEDULE`` settings dict unless the PeriodicTask DB row exists, so
this migration creates it reliably (get_or_create → idempotent). The task wrapper
(``apps.pharmacy.tasks.grade_stockout_predictions``) fans out across every tenant
via ``tenant_context``.
"""

from django.db import migrations


def register_periodic_task(apps, schema_editor):
    try:
        CrontabSchedule = apps.get_model("django_celery_beat", "CrontabSchedule")
        PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    except LookupError:
        # django_celery_beat not installed — skip gracefully.
        return

    nightly_cron, _ = CrontabSchedule.objects.get_or_create(
        minute="0",
        hour="3",
        day_of_week="*",
        day_of_month="*",
        month_of_year="*",
    )

    PeriodicTask.objects.get_or_create(
        name="pharmacy.grade_stockout_predictions",
        defaults={
            "task": "pharmacy.grade_stockout_predictions",
            "crontab": nightly_cron,
            "enabled": True,
            "description": (
                "Stockout wedge S4: grade past-due stockout_risk predictions "
                "(flywheel) across all tenants, nightly at 03:00 UTC."
            ),
        },
    )


def unregister_periodic_task(apps, schema_editor):
    try:
        PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    except LookupError:
        return
    PeriodicTask.objects.filter(name="pharmacy.grade_stockout_predictions").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("pharmacy", "0011_stockalert_flywheel_outcome"),
        ("django_celery_beat", "0018_improve_crontab_helptext"),
    ]

    operations = [
        migrations.RunPython(register_periodic_task, unregister_periodic_task),
    ]
