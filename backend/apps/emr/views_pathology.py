from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from apps.core.permissions import HasPermission

from .models import PathologyReport, PathologySpecimen
from .serializers_pathology import (
    PathologyReportSerializer,
    PathologySpecimenSerializer,
)


class PathologyPermissionsMixin:
    """Mirror of the LIS/MB1 RBAC: read for list/retrieve, write else."""

    def get_permissions(self):
        permission = "emr.read" if self.action in {"list", "retrieve"} else "emr.write"
        return [IsAuthenticated(), HasPermission(permission)]


class PathologyReportViewSet(PathologyPermissionsMixin, viewsets.ModelViewSet):
    serializer_class = PathologyReportSerializer

    def get_queryset(self):
        qs = PathologyReport.objects.select_related(
            "order_item", "surgical_case", "pathologist", "created_by"
        ).prefetch_related("specimens")
        order_item = self.request.query_params.get("order_item")
        if order_item:
            qs = qs.filter(order_item_id=order_item)
        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)
        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class PathologySpecimenViewSet(PathologyPermissionsMixin, viewsets.ModelViewSet):
    serializer_class = PathologySpecimenSerializer

    def get_queryset(self):
        qs = PathologySpecimen.objects.select_related("report")
        report = self.request.query_params.get("report")
        if report:
            qs = qs.filter(report_id=report)
        return qs
