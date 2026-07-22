from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from apps.core.permissions import HasPermission

from .models import CostCenter, Facility, LegalEntity, OrganizationalUnit
from .serializers import (
    CostCenterSerializer,
    FacilitySerializer,
    LegalEntitySerializer,
    OrganizationalUnitSerializer,
)


class OrganizationPermissionMixin:
    def get_permissions(self):
        permission = "organization.read"
        if self.action in {"create", "update", "partial_update"}:
            permission = "organization.write"
        elif self.action == "destroy":
            permission = "organization.delete"
        return [IsAuthenticated(), HasPermission(permission)]


class LegalEntityViewSet(OrganizationPermissionMixin, viewsets.ModelViewSet):
    queryset = LegalEntity.objects.all()
    serializer_class = LegalEntitySerializer


class FacilityViewSet(OrganizationPermissionMixin, viewsets.ModelViewSet):
    queryset = Facility.objects.select_related("legal_entity").all()
    serializer_class = FacilitySerializer


class OrganizationalUnitViewSet(OrganizationPermissionMixin, viewsets.ModelViewSet):
    queryset = OrganizationalUnit.objects.select_related("facility", "parent").all()
    serializer_class = OrganizationalUnitSerializer


class CostCenterViewSet(OrganizationPermissionMixin, viewsets.ModelViewSet):
    queryset = CostCenter.objects.select_related("legal_entity", "facility", "parent").all()
    serializer_class = CostCenterSerializer
