"""Pharmacy signals.

Controlled-diversion wedge (C2): after a Dispensation commits, run the
deterministic diversion monitor on_commit — AFTER the dispensation is durable and
after the DispenseView's 201, so the advisory can never delay or roll back the
dispensation (it is advise/compliance only, never blocks). No-op when the
``controlled_safety`` flag is OFF and fail-safe on any error.
"""

import logging

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)


@receiver(post_save, sender="pharmacy.Dispensation")
def trigger_controlled_diversion_check(sender, instance, created, **kwargs):
    """Schedule the controlled-diversion monitor on_commit after a dispensation.

    Fires on creation only (a dispensation is immutable once made). Deferred via
    transaction.on_commit so the StockMovement/lot writes in the same transaction
    are visible and the dispense response is never blocked.
    """
    if not created:
        return

    dispensation_id = instance.pk

    def _run():
        from apps.pharmacy.services.controlled_safety import ControlledSafetyService

        ControlledSafetyService().evaluate(dispensation_id)

    transaction.on_commit(_run)
