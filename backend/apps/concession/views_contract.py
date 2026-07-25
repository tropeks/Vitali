"""Sprint C2 — gated + audited REST viewsets for contract / price / recipe.

Every viewset gates on ``[IsAuthenticated, ConcessionModule]`` (the tenant must
have the ``diagnostic_concession`` module active) and audits writes via
``log_audit`` into ``core.AuditLog``.
"""

import json

from django.core.serializers.json import DjangoJSONEncoder
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from apps.core.models import AuditLog

from .contract_models import (
    ConcessionContract,
    ContractServicePrice,
    ServiceRecipe,
)
from .permissions import ConcessionModule
from .serializers_contract import (
    ConcessionContractSerializer,
    ContractServicePriceSerializer,
    ServiceRecipeSerializer,
)


def _json_safe(data):
    """Coerce serializer data into JSON-primitive types.

    ``AuditLog.old_data``/``new_data`` are plain ``JSONField``s (default json
    encoder), but DRF serializer data can carry UUIDs (Facility/Material PKs),
    Decimals and datetimes. Round-trip through ``DjangoJSONEncoder`` so the
    audit write never raises on non-primitive values.
    """
    if data is None:
        return None
    return json.loads(json.dumps(data, cls=DjangoJSONEncoder))


def log_audit(request, action, resource_type, resource_id, old_data=None, new_data=None):
    """Append an AuditLog row for a concession write (mirrors pharmacy/emr)."""
    AuditLog.objects.create(
        user=request.user,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id),
        old_data=_json_safe(old_data),
        new_data=_json_safe(new_data),
        ip_address=request.META.get("REMOTE_ADDR", ""),
    )


class ConcessionContractViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, ConcessionModule]
    serializer_class = ConcessionContractSerializer

    def get_queryset(self):
        return ConcessionContract.objects.prefetch_related("units").all()

    def perform_create(self, serializer):
        contract = serializer.save()
        log_audit(
            self.request, "create", "ConcessionContract", contract.pk, new_data=serializer.data
        )

    def perform_update(self, serializer):
        contract = serializer.save()
        log_audit(
            self.request, "update", "ConcessionContract", contract.pk, new_data=serializer.data
        )

    def perform_destroy(self, instance):
        log_audit(self.request, "delete", "ConcessionContract", instance.pk)
        instance.delete()


class ContractServicePriceViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, ConcessionModule]
    serializer_class = ContractServicePriceSerializer

    def get_queryset(self):
        qs = ContractServicePrice.objects.select_related("service", "contract", "unit")
        contract_id = self.request.query_params.get("contract")
        if contract_id:
            qs = qs.filter(contract_id=contract_id)
        unit_id = self.request.query_params.get("unit")
        if unit_id:
            qs = qs.filter(unit_id=unit_id)
        return qs

    def perform_create(self, serializer):
        price = serializer.save()
        log_audit(
            self.request, "create", "ContractServicePrice", price.pk, new_data=serializer.data
        )

    def perform_update(self, serializer):
        price = serializer.save()
        log_audit(
            self.request, "update", "ContractServicePrice", price.pk, new_data=serializer.data
        )

    def perform_destroy(self, instance):
        log_audit(self.request, "delete", "ContractServicePrice", instance.pk)
        instance.delete()


class ServiceRecipeViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, ConcessionModule]
    serializer_class = ServiceRecipeSerializer

    def get_queryset(self):
        qs = ServiceRecipe.objects.select_related("service", "material")
        service_id = self.request.query_params.get("service")
        if service_id:
            qs = qs.filter(service_id=service_id)
        return qs

    def perform_create(self, serializer):
        recipe = serializer.save()
        log_audit(self.request, "create", "ServiceRecipe", recipe.pk, new_data=serializer.data)

    def perform_update(self, serializer):
        recipe = serializer.save()
        log_audit(self.request, "update", "ServiceRecipe", recipe.pk, new_data=serializer.data)

    def perform_destroy(self, instance):
        log_audit(self.request, "delete", "ServiceRecipe", instance.pk)
        instance.delete()
