"""Sprint C4 — gated read endpoint for the contract P&L.

``GET /api/v1/concession/contracts/<id>/pnl/?start=&end=&unit=`` returns the
contract P&L (or a single unit's, when ``unit`` is given). Gated on
``[IsAuthenticated, ConcessionModule]`` — a tenant without the
``diagnostic_concession`` tier gets 403. Read-only, so nothing is audited.
"""

from django.shortcuts import get_object_or_404
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.organization.models import Facility

from .contract_models import ConcessionContract
from .permissions import ConcessionModule
from .serializers_pnl import PnlQuerySerializer
from .services_pnl import contract_pnl, unit_pnl


class ContractPnlViewSet(viewsets.GenericViewSet):
    """Exposes only the ``pnl`` detail action on a concession contract."""

    permission_classes = [IsAuthenticated, ConcessionModule]
    queryset = ConcessionContract.objects.all()

    @action(detail=True, methods=["get"], url_path="pnl")
    def pnl(self, request, pk=None):
        contract = self.get_object()
        params = PnlQuerySerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        start = params.validated_data.get("start")
        end = params.validated_data.get("end")
        unit_id = params.validated_data.get("unit")
        if unit_id:
            unit = get_object_or_404(Facility, pk=unit_id)
            data = unit_pnl(contract, unit, start, end)
        else:
            data = contract_pnl(contract, start, end)
        return Response(data)
