"""Data migration — register the no-show wedge nightly Celery Beat tasks (N2).

Creates two PeriodicTasks in django_celery_beat:
  * emr.evaluate_no_show           — daily 02:00 UTC (score upcoming window)
  * emr.grade_no_show_predictions  — daily 03:30 UTC (flywheel grading)

Mirrors pharmacy migration 0012: DatabaseScheduler ignores the settings dict
unless the PeriodicTask DB row exists, so this migration creates them reliably
(get_or_create → idempotent). The task wrappers (apps.emr.tasks) fan out across
every tenant via tenant_context. Both are no-ops when no_show_prediction is OFF
(evaluate) / when there are no pending predictions (grade).
"""

from django.db import migrations

_TASKS = [
    ("emr.evaluate_no_show", "0", "2", "No-show wedge N2: score upcoming appointments nightly."),
    (
        "emr.grade_no_show_predictions",
        "30",
        "3",
        "No-show wedge N2: grade past-due no-show predictions (flywheel) nightly.",
    ),
]


def register(apps, schema_editor):
    try:
        CrontabSchedule = apps.get_model("django_celery_beat", "CrontabSchedule")
        PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    except LookupError:
        return

    for task_name, minute, hour, description in _TASKS:
        cron, _ = CrontabSchedule.objects.get_or_create(
            minute=minute,
            hour=hour,
            day_of_week="*",
            day_of_month="*",
            month_of_year="*",
        )
        PeriodicTask.objects.get_or_create(
            name=task_name,
            defaults={
                "task": task_name,
                "crontab": cron,
                "enabled": True,
                "description": description,
            },
        )


def unregister(apps, schema_editor):
    try:
        PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    except LookupError:
        return
    PeriodicTask.objects.filter(
        name__in=("emr.evaluate_no_show", "emr.grade_no_show_predictions")
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("emr", "0022_noshowrisk"),
        ("django_celery_beat", "0018_improve_crontab_helptext"),
    ]

    operations = [
        migrations.RunPython(register, unregister),
    ]
