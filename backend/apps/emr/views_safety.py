"""
S-063: DRF views for AI prescription safety.

Endpoints:
  GET  /emr/prescriptions/{id}/items/{item_id}/safety-check/
       Returns current safety status (from cache or DB).

  POST /emr/prescriptions/{id}/items/{item_id}/safety-check/
       Triggers a fresh safety check (re-queues Celery task).

  POST /emr/prescriptions/{id}/items/{item_id}/acknowledge-alert/
       Acknowledges a specific AISafetyAlert (with reason for contraindications).

Design: polling only, no WebSocket (DX-01 decision).
"""
import logging

from django.core.cache import cache
from django.db import transaction
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.emr.models import AISafetyAlert, PrescriptionItem

logger = logging.getLogger(__name__)

SAFETY_STATUS_KEY_TEMPLATE = "ai:safety_status:{item_id}"


def _get_safety_status_from_db(item_id: str) -> dict:
    """
    Fallback: build safety status dict from AISafetyAlert DB records.
    """
    try:
        item = PrescriptionItem.objects.get(id=item_id)
        alerts = item.safety_alerts.all()
        if not alerts.exists():
            return {"status": "pending", "alerts": []}

        alert_list = [
            {
                "id": str(a.id),
                "alert_type": a.alert_type,
                "severity": a.severity,
                "message": a.message,
                "recommendation": a.recommendation,
                "status": a.status,
                "acknowledged_at": a.acknowledged_at.isoformat() if a.acknowledged_at else None,
            }
            for a in alerts
        ]

        has_flagged = any(a["status"] == "flagged" for a in alert_list)
        status_value = "flagged" if has_flagged else "safe"
        return {"status": status_value, "alerts": alert_list}
    except PrescriptionItem.DoesNotExist:
        return {"status": "error", "alerts": []}
    except Exception:
        logger.warning("Failed to build safety status from DB", exc_info=True)
        return {"status": "error", "alerts": []}


class PrescriptionItemSafetyCheckView(APIView):
    """
    GET  /emr/prescriptions/{prescription_id}/items/{item_id}/safety-check/
    POST /emr/prescriptions/{prescription_id}/items/{item_id}/safety-check/
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, prescription_id, item_id):
        """Return current safety status for a PrescriptionItem."""
        # Verify item belongs to prescription
        if not PrescriptionItem.objects.filter(
            id=item_id, prescription_id=prescription_id
        ).exists():
            return Response(
                {"error": "Item não encontrado nesta receita."},
                status=status.HTTP_404_NOT_FOUND,
            )

        status_key = SAFETY_STATUS_KEY_TEMPLATE.format(item_id=item_id)
        cached = cache.get(status_key)
        if cached is not None:
            return Response(cached, status=status.HTTP_200_OK)

        # Cache miss: build from DB
        result = _get_safety_status_from_db(str(item_id))
        return Response(result, status=status.HTTP_200_OK)

    def post(self, request, prescription_id, item_id):
        """Trigger a fresh safety check by re-queuing the Celery task."""
        if not PrescriptionItem.objects.filter(
            id=item_id, prescription_id=prescription_id
        ).exists():
            return Response(
                {"error": "Item não encontrado nesta receita."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Invalidate cache so the next GET shows 'pending'
        status_key = SAFETY_STATUS_KEY_TEMPLATE.format(item_id=item_id)
        cache.set(status_key, {"status": "pending", "alerts": []}, 300)

        # Use on_commit to fire after this request's transaction
        from apps.emr.tasks import check_prescription_safety
        transaction.on_commit(
            lambda: check_prescription_safety.delay(str(item_id))
        )

        return Response(
            {"message": "Verificação de segurança re-agendada.", "status": "pending"},
            status=status.HTTP_202_ACCEPTED,
        )


class AcknowledgeSafetyAlertView(APIView):
    """
    POST /emr/prescriptions/{prescription_id}/items/{item_id}/acknowledge-alert/

    Body: {alert_id: uuid, reason: str}

    For severity=contraindication: reason is required (min 10 chars).
    Calls alert.acknowledge(user, reason).
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, alert_id):
        reason = request.data.get("reason", "").strip()

        try:
            alert = AISafetyAlert.objects.get(id=alert_id)
        except AISafetyAlert.DoesNotExist:
            return Response(
                {"error": "Alerta não encontrado."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Reason required for contraindications (min 10 chars)
        if alert.severity == "contraindication":
            if len(reason) < 10:
                return Response(
                    {
                        "error": "Para contraindicações, o motivo deve ter pelo menos 10 caracteres."
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        alert.acknowledge(request.user, reason)

        logger.info(
            "Safety alert %s acknowledged by user %s (severity=%s)",
            alert.id,
            request.user.id,
            alert.severity,
        )

        return Response(
            {
                "message": "Alerta reconhecido com sucesso.",
                "alert_id": str(alert.id),
                "acknowledged_at": alert.acknowledged_at.isoformat(),
            },
            status=status.HTTP_200_OK,
        )
