"""Data migration — register nightly evaluate_stockout Celery Beat task (wedge S2).

Creates one PeriodicTask in django_celery_beat:
  * pharmacy.evaluate_stockout — daily at 02:30 UTC (before grade at 03:00)

Mirrors pharmacy/0012_grade_stockout_beat_schedule: DatabaseScheduler ignores
the CELERY_BEAT_SCHEDULE settings dict unless the PeriodicTask DB row exists, so
this migration creates it reliably (get_or_create → idempotent). The task wrapper
(apps.pharmacy.tasks.evaluate_stockout) fans out across every tenant via
tenant_context. The job is a no-op per tenant when the stockout_safety flag is OFF.
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
        minute="30",
        hour="2",
        day_of_week="*",
        day_of_month="*",
        month_of_year="*",
    )

    PeriodicTask.objects.get_or_create(
        name="pharmacy.evaluate_stockout",
        defaults={
            "task": "pharmacy.evaluate_stockout",
            "crontab": nightly_cron,
            "enabled": True,
            "description": (
                "Stockout wedge S2: proactively evaluate stockout risk for all "
                "products with lead_time_days set, across all tenants, nightly at "
                "02:30 UTC (before grade job at 03:00)."
            ),
        },
    )


def unregister_periodic_task(apps, schema_editor):
    try:
        PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    except LookupError:
        return
    PeriodicTask.objects.filter(name="pharmacy.evaluate_stockout").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("pharmacy", "0019_doserule_natural_key_constraint"),
        ("django_celery_beat", "0018_improve_crontab_helptext"),
    ]

    operations = [
        migrations.RunPython(register_periodic_task, unregister_periodic_task),
    ]
