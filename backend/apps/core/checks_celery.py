from urllib.parse import urlparse

from django.conf import settings
from django.core.checks import Error, Warning, register


@register("celery")
def check_celery_delivery_settings(app_configs, **kwargs):
    errors = []
    broker = urlparse(settings.CELERY_BROKER_URL)
    if broker.scheme not in {"redis", "rediss", "amqp", "amqps", "pyamqp"}:
        errors.append(Error("Unsupported Celery broker scheme.", id="core.E005"))
    if broker.scheme in {"amqp", "amqps", "pyamqp"} and (
        not broker.username or not broker.path.strip("/")
    ):
        errors.append(
            Error(
                "AMQP broker URL must contain a username and an explicit vhost.",
                id="core.E006",
            )
        )
    if settings.CELERY_TASK_SOFT_TIME_LIMIT >= settings.CELERY_TASK_TIME_LIMIT:
        errors.append(
            Error("Celery soft time limit must be lower than hard time limit.", id="core.E007")
        )
    if settings.CELERY_WORKER_PREFETCH_MULTIPLIER > 1 and settings.CELERY_TASK_ACKS_LATE:
        errors.append(
            Warning(
                "acks_late with prefetch > 1 may reserve too much work per worker.",
                id="core.W005",
            )
        )
    return errors
