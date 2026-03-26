import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "healthos.settings.development")

app = Celery("healthos")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
