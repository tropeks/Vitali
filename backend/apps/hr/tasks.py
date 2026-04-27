"""HR Celery tasks — Sprint 18 / E-013 Workflow Intelligence v0.

setup_staff_whatsapp_channel is a stub here; T7 implements the real cascade.
T3 only needs the symbol to import + enqueue via .delay().
"""

from celery import shared_task


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def setup_staff_whatsapp_channel(self, user_id: str):
    """T7 implements the real cascade. T3 just needs the symbol to import + enqueue."""
    pass
