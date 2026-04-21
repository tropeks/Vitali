import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "vitali.settings.development")

app = Celery("vitali")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

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
}
