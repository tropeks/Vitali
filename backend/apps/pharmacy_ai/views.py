"""REST views for the AI Farmácia demand-forecast module."""

from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import HasPermission, ModuleRequiredPermission
from apps.pharmacy.models import Drug

from .services.forecast import forecast_for_drug

_PHARMACY_AI_MODULE = ModuleRequiredPermission("pharmacy_ai")


class DrugForecastView(APIView):
    """
    GET /api/v1/pharmacy/forecast/?drug=<id>&window_days=30&target_days=60

    Returns a demand forecast for one drug. The payload carries both the
    arithmetic baseline and, when enough history exists, a learned seasonal
    model (Holt-Winters) selected via a hold-out MAPE back-test — see the
    `model` / `*_model` / `accuracy` fields and
    `apps.pharmacy_ai.services.forecast` for details (issue #131).
    """

    def get_permissions(self):
        return [
            IsAuthenticated(),
            _PHARMACY_AI_MODULE,
            HasPermission("pharmacy_ai.read"),
        ]

    def get(self, request):
        drug_id = request.query_params.get("drug")
        if not drug_id:
            return Response(
                {"detail": "`drug` query parameter is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            window_days = int(request.query_params.get("window_days", 30))
            target_days = int(request.query_params.get("target_days", 60))
        except (TypeError, ValueError):
            return Response(
                {"detail": "`window_days` and `target_days` must be integers."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if window_days <= 0 or target_days <= 0:
            return Response(
                {"detail": "`window_days` and `target_days` must be positive."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            drug = Drug.objects.get(pk=drug_id)
        except (Drug.DoesNotExist, ValueError):
            return Response({"detail": "Drug not found."}, status=status.HTTP_404_NOT_FOUND)

        forecast = forecast_for_drug(drug, window_days=window_days, target_days=target_days)
        return Response(forecast.to_dict())
