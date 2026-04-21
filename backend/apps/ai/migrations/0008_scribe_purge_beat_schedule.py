"""
S-071: Register purge_old_scribe_sessions Celery Beat PeriodicTask.

Runs daily at 03:00 UTC. Deletes non-completed AIScribeSession rows older
than SCRIBE_SESSION_RETENTION_DAYS days across all tenant schemas.
"""
from django.db import migrations


def register_periodic_task(apps, schema_editor):
    try:
        CrontabSchedule = apps.get_model("django_celery_beat", "CrontabSchedule")
        PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    except LookupError:
        return

    purge_cron, _ = CrontabSchedule.objects.get_or_create(
        minute="0",
        hour="3",
        day_of_week="*",
        day_of_month="*",
        month_of_year="*",
    )

    PeriodicTask.objects.get_or_create(
        name="purge_old_scribe_sessions",
        defaults={
            "task": "apps.ai.tasks.purge_old_scribe_sessions",
            "crontab": purge_cron,
            "enabled": True,
            "description": "S-071: Delete non-completed AIScribeSession rows older than SCRIBE_SESSION_RETENTION_DAYS days.",
        },
    )


def unregister_periodic_task(apps, schema_editor):
    try:
        PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    except LookupError:
        return
    PeriodicTask.objects.filter(name="purge_old_scribe_sessions").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("ai", "0007_encrypt_scribe_raw_transcription"),
        ("django_celery_beat", "0018_improve_crontab_helptext"),
    ]

    operations = [
        migrations.RunPython(register_periodic_task, unregister_periodic_task),
    ]
