"""Escalation router — S30-03 (clinical-deterioration wedge, escalation routing).

Routes escalation-severity DeteriorationAlerts to the configured recipients
(via AuditLog + email task stub). Per-tenant EscalationConfig drives who is
notified and at which severity threshold.

POSTURE — ALWAYS FAIL-SAFE. Any routing error is logged and swallowed. The
clinical DeteriorationAlert is already committed before routing runs; a failure
here never affects the alert row or the vitals record.
"""

from __future__ import annotations

import logging

from apps.core.models import AuditLog
from apps.emr.models import DeteriorationAlert, EscalationConfig

logger = logging.getLogger(__name__)

# Severity ranking for threshold comparison.
_SEVERITY_ORDER = {
    DeteriorationAlert.Severity.ADVISE: 0,
    DeteriorationAlert.Severity.ESCALATION: 1,
}


class EscalationRouter:
    """Route one DeteriorationAlert to the tenant's escalation contacts."""

    def route(self, alert: DeteriorationAlert, *, requesting_user=None) -> None:
        """Evaluate and deliver escalation notification.

        No-op when: no config, config inactive, or alert severity is below the
        configured threshold. Any exception is swallowed (fail-safe).
        """
        try:
            self._route(alert, requesting_user=requesting_user)
        except Exception:
            logger.exception(
                "EscalationRouter.route failed for DeteriorationAlert %s; failing safe.",
                getattr(alert, "pk", None),
            )

    def _route(self, alert: DeteriorationAlert, *, requesting_user=None) -> None:
        config = EscalationConfig.objects.filter(is_active=True).order_by("-created_at").first()
        if config is None:
            return

        alert_sev = _SEVERITY_ORDER.get(alert.severity, -1)
        min_sev = _SEVERITY_ORDER.get(config.min_severity, 1)
        if alert_sev < min_sev:
            return

        self._notify(alert, config)

        AuditLog.objects.create(
            user=requesting_user,
            action="deterioration_escalation_routed",
            resource_type="deterioration_alert",
            resource_id=str(alert.pk),
            new_data={
                "alert_id": str(alert.pk),
                "severity": alert.severity,
                "band": alert.band,
                "score": alert.score,
                "notify_emails": config.notify_emails,
                "notify_role": config.notify_role or None,
            },
        )

    def _notify(self, alert: DeteriorationAlert, config: EscalationConfig) -> None:
        """Stub: enqueue email notification task. Extend in S31+ for real delivery."""
        if not config.notify_emails:
            return
        try:
            from apps.emr.tasks import send_escalation_notification
            send_escalation_notification.delay(
                alert_id=str(alert.pk),
                notify_emails=config.notify_emails,
            )
        except Exception:
            logger.warning(
                "Could not enqueue send_escalation_notification for alert %s; "
                "routing audit is already written.",
                alert.pk,
            )
