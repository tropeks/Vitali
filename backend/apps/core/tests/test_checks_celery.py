from django.core.checks import run_checks
from django.test import SimpleTestCase, override_settings


class CeleryDeliveryChecksTests(SimpleTestCase):
    @override_settings(
        CELERY_BROKER_URL="amqp://vitali:secret@rabbitmq:5672/vitali",
        CELERY_TASK_ACKS_LATE=True,
        CELERY_WORKER_PREFETCH_MULTIPLIER=1,
        CELERY_TASK_SOFT_TIME_LIMIT=270,
        CELERY_TASK_TIME_LIMIT=300,
    )
    def test_safe_amqp_configuration_passes(self):
        ids = {message.id for message in run_checks(tags=["celery"])}
        self.assertFalse(ids & {"core.E005", "core.E006", "core.E007", "core.W005"})

    @override_settings(
        CELERY_BROKER_URL="amqp://rabbitmq:5672",
        CELERY_TASK_SOFT_TIME_LIMIT=300,
        CELERY_TASK_TIME_LIMIT=300,
    )
    def test_missing_credentials_vhost_and_invalid_limits_fail(self):
        ids = {message.id for message in run_checks(tags=["celery"])}
        self.assertIn("core.E006", ids)
        self.assertIn("core.E007", ids)

    @override_settings(CELERY_BROKER_URL="kafka://broker/vitali")
    def test_unsupported_transport_fails(self):
        ids = {message.id for message in run_checks(tags=["celery"])}
        self.assertIn("core.E005", ids)
