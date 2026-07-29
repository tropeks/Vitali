"""B0-T1 — gated + audited CRUD for the ConcessionService catalog.

The catalog drives imaging-modality matching (an asset enables services, a
recipe consumes for a service, a price tariffs a service). Gated on
``[IsAuthenticated, ConcessionModule]`` like the rest of the module.
"""

import json

from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from apps.core.models import AuditLog

from .models import ConcessionService
from .permissions import ConcessionModule, HasConcessionAccess
from .serializers_catalog import ConcessionServiceSerializer


def _json_safe(data):
    if data is None:
        return None
    return json.loads(json.dumps(data, default=str))


def log_audit(request, action, resource_type, resource_id, old_data=None, new_data=None):
    AuditLog.objects.create(
        user=request.user,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id),
        old_data=_json_safe(old_data),
        new_data=_json_safe(new_data),
        ip_address=request.META.get("REMOTE_ADDR", ""),
    )


@extend_schema_view(
    list=extend_schema(responses=ConcessionServiceSerializer(many=True)),
    retrieve=extend_schema(responses=ConcessionServiceSerializer),
    create=extend_schema(
        request=ConcessionServiceSerializer, responses=ConcessionServiceSerializer
    ),
    update=extend_schema(
        request=ConcessionServiceSerializer, responses=ConcessionServiceSerializer
    ),
    partial_update=extend_schema(
        request=ConcessionServiceSerializer, responses=ConcessionServiceSerializer
    ),
    destroy=extend_schema(responses={204: None}),
)
class ConcessionServiceViewSet(viewsets.ModelViewSet):
    """CRUD for the local service/exam catalog."""

    queryset = ConcessionService.objects.all()
    serializer_class = ConcessionServiceSerializer
    permission_classes = [IsAuthenticated, ConcessionModule, HasConcessionAccess]

    def get_queryset(self):
        qs = ConcessionService.objects.all()
        active = self.request.query_params.get("active")
        if active in ("true", "false"):
            qs = qs.filter(active=(active == "true"))
        return qs

    def perform_create(self, serializer):
        svc = serializer.save()
        log_audit(self.request, "create", "ConcessionService", svc.pk, new_data=serializer.data)

    def perform_update(self, serializer):
        old = ConcessionServiceSerializer(serializer.instance).data
        svc = serializer.save()
        log_audit(
            self.request,
            "update",
            "ConcessionService",
            svc.pk,
            old_data=old,
            new_data=serializer.data,
        )

    def perform_destroy(self, instance):
        log_audit(self.request, "delete", "ConcessionService", instance.pk)
        instance.delete()
