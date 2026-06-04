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

from apps.core.permissions import HasPermission
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
    GET  /emr/prescription-items/{item_id}/safety-check/
    POST /emr/prescription-items/{item_id}/safety-check/

    The route is keyed by item_id alone (the PrescriptionItem pk is globally
    unique within the tenant); the prescription is derivable from the item, so the
    URL no longer carries prescription_id. The earlier signature still required it
    and raised a 500 on every (valid) call — fixed here.
    """

    def get_permissions(self):
        # Per-item safety status is clinical data; exclude non-clinical roles
        # (recepcao has no emr.read). Mirrors the EMR read surface.
        return [IsAuthenticated(), HasPermission("emr.read")]

    def get(self, request, item_id):
        """Return current safety status for a PrescriptionItem."""
        if not PrescriptionItem.objects.filter(id=item_id).exists():
            return Response(
                {"error": "Item de receita não encontrado."},
                status=status.HTTP_404_NOT_FOUND,
            )

        status_key = SAFETY_STATUS_KEY_TEMPLATE.format(item_id=item_id)
        cached = cache.get(status_key)
        if cached is not None:
            return Response(cached, status=status.HTTP_200_OK)

        # Cache miss: build from DB
        result = _get_safety_status_from_db(str(item_id))
        return Response(result, status=status.HTTP_200_OK)

    def post(self, request, item_id):
        """Trigger a fresh safety check by re-queuing the Celery task."""
        if not PrescriptionItem.objects.filter(id=item_id).exists():
            return Response(
                {"error": "Item de receita não encontrado."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Invalidate cache so the next GET shows 'pending'
        status_key = SAFETY_STATUS_KEY_TEMPLATE.format(item_id=item_id)
        cache.set(status_key, {"status": "pending", "alerts": []}, 300)

        # Use on_commit to fire after this request's transaction
        from apps.emr.tasks import check_prescription_safety

        transaction.on_commit(lambda: check_prescription_safety.delay(str(item_id)))

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

    def get_permissions(self):
        # Overriding a dose contraindication is a clinical-write act. emr.write is
        # the floor that excludes non-clinical roles (recepcao, faturista) — mirrors
        # PrescriptionItemViewSet writes.
        return [IsAuthenticated(), HasPermission("emr.write")]

    def post(self, request, alert_id):
        reason = request.data.get("reason", "").strip()

        try:
            alert = AISafetyAlert.objects.get(id=alert_id)
        except AISafetyAlert.DoesNotExist:
            return Response(
                {"error": "Alerta não encontrado."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Only an open (flagged) alert is actionable. Re-acking an already
        # acknowledged/resolved alert would overwrite the original
        # acknowledged_by/at and emit audit noise — reject it.
        if alert.status != "flagged":
            return Response(
                {"error": "Alerta já reconhecido ou resolvido; nada a fazer."},
                status=status.HTTP_409_CONFLICT,
            )

        # A weight-gate block is NON-overridable: you cannot reason away a
        # missing weight, you must record it. Refuse the acknowledgement at the
        # authority so the bypass is closed even if a client tries it directly.
        from apps.emr.services.dose_safety import DoseCheckService

        if (
            alert.source == AISafetyAlert.Source.ENGINE
            and alert.alert_type == "dose"
            and DoseCheckService.classify_blocking_kind(alert) == "weight_gate"
        ):
            return Response(
                {
                    "error": (
                        "Não é possível reconhecer um bloqueio por peso ausente. "
                        "Registre o peso do paciente e reavalie."
                    )
                },
                status=status.HTTP_409_CONFLICT,
            )

        # Reason required for contraindications (min 10 chars)
        if alert.severity == "contraindication":
            if len(reason) < 10:
                return Response(
                    {"error": "Para contraindicações, o motivo deve ter pelo menos 10 caracteres."},
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
