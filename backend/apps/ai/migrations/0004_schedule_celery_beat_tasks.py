"""
Data migration — register Celery Beat PeriodicTask rows (S-038).

Creates two PeriodicTask entries in django_celery_beat:
  1. check_tuss_staleness      — daily at 08:00 UTC
  2. cleanup_orphaned_glosa_predictions — daily at 02:00 UTC

Uses get_or_create for idempotency (safe to run on a DB that already has rows).

Note: DatabaseScheduler ignores CELERY_BEAT_SCHEDULE settings dict if the
PeriodicTask DB record doesn't exist. This migration creates those records
reliably on every deploy (migrate is idempotent).
"""
from django.db import migrations


def register_periodic_tasks(apps, schema_editor):
    # Use the historical model from django_celery_beat via apps registry.
    # django_celery_beat must be in INSTALLED_APPS before this migration runs.
    try:
        IntervalSchedule = apps.get_model("django_celery_beat", "IntervalSchedule")
        CrontabSchedule = apps.get_model("django_celery_beat", "CrontabSchedule")
        PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    except LookupError:
        # django_celery_beat not installed — skip gracefully
        return

    # Daily at 08:00 UTC crontab
    staleness_cron, _ = CrontabSchedule.objects.get_or_create(
        minute="0",
        hour="8",
        day_of_week="*",
        day_of_month="*",
        month_of_year="*",
    )

    # Daily at 02:00 UTC crontab
    cleanup_cron, _ = CrontabSchedule.objects.get_or_create(
        minute="0",
        hour="2",
        day_of_week="*",
        day_of_month="*",
        month_of_year="*",
    )

    PeriodicTask.objects.get_or_create(
        name="check_tuss_staleness",
        defaults={
            "task": "apps.ai.tasks.check_tuss_staleness",
            "crontab": staleness_cron,
            "enabled": True,
            "description": "S-038: Check TUSS sync log age daily at 08:00 UTC.",
        },
    )

    PeriodicTask.objects.get_or_create(
        name="cleanup_orphaned_glosa_predictions",
        defaults={
            "task": "apps.ai.tasks.cleanup_orphaned_glosa_predictions",
            "crontab": cleanup_cron,
            "enabled": True,
            "description": "S-034: Delete orphaned GlosaPrediction rows older than 7 days.",
        },
    )


def unregister_periodic_tasks(apps, schema_editor):
    try:
        PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    except LookupError:
        return
    PeriodicTask.objects.filter(
        name__in=["check_tuss_staleness", "cleanup_orphaned_glosa_predictions"]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("ai", "0003_sprint9_glosaprediction"),
        ("django_celery_beat", "0018_improve_crontab_helptext"),
    ]

    operations = [
        migrations.RunPython(register_periodic_tasks, unregister_periodic_tasks),
    ]
