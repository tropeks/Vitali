"""
Data migration — register WhatsApp Celery Beat PeriodicTask rows (Sprint 12, S-034).

Creates four PeriodicTask entries:
  1. send_appointment_reminders  — every 15 minutes
  2. mark_no_shows               — every hour
  3. send_satisfaction_surveys   — every hour
  4. cleanup_expired_sessions    — every 15 minutes

Follows the same pattern as apps/ai/migrations/0004_schedule_celery_beat_tasks.py.
Uses get_or_create for idempotency (safe to run on a DB that already has rows).
"""

from django.db import migrations


def register_periodic_tasks(apps, schema_editor):
    try:
        IntervalSchedule = apps.get_model("django_celery_beat", "IntervalSchedule")
        PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    except LookupError:
        return

    every_15min, _ = IntervalSchedule.objects.get_or_create(
        every=15,
        period="minutes",
    )
    every_1hour, _ = IntervalSchedule.objects.get_or_create(
        every=1,
        period="hours",
    )

    PeriodicTask.objects.get_or_create(
        name="send_appointment_reminders",
        defaults={
            "task": "apps.whatsapp.tasks.send_appointment_reminders",
            "interval": every_15min,
            "enabled": True,
            "description": "S-034: Send WhatsApp 24h/2h appointment reminders every 15 min.",
        },
    )

    PeriodicTask.objects.get_or_create(
        name="mark_no_shows",
        defaults={
            "task": "apps.whatsapp.tasks.mark_no_shows",
            "interval": every_1hour,
            "enabled": True,
            "description": "S-034: Mark appointments as no_show after reminder sent but not confirmed.",
        },
    )

    PeriodicTask.objects.get_or_create(
        name="send_satisfaction_surveys",
        defaults={
            "task": "apps.whatsapp.tasks.send_satisfaction_surveys",
            "interval": every_1hour,
            "enabled": True,
            "description": "S-034b: Send post-visit satisfaction survey 2h after appointment completion.",
        },
    )

    PeriodicTask.objects.get_or_create(
        name="cleanup_expired_whatsapp_sessions",
        defaults={
            "task": "apps.whatsapp.tasks.cleanup_expired_sessions",
            "interval": every_15min,
            "enabled": True,
            "description": "S-033/S-035: Delete expired ConversationSession rows (LGPD).",
        },
    )


def unregister_periodic_tasks(apps, schema_editor):
    try:
        PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    except LookupError:
        return
    PeriodicTask.objects.filter(
        name__in=[
            "send_appointment_reminders",
            "mark_no_shows",
            "send_satisfaction_surveys",
            "cleanup_expired_whatsapp_sessions",
        ]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("whatsapp", "0001_initial"),
        ("django_celery_beat", "0018_improve_crontab_helptext"),
    ]

    operations = [
        migrations.RunPython(register_periodic_tasks, unregister_periodic_tasks),
    ]
