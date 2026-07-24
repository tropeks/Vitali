"""Sprint M1-S3 — REST surface for reconciliation + order sets.

Two ModelViewSets consistent with the rest of the EMR API:

* permission split — ``emr.read`` for list/retrieve, ``emr.write`` for writes;
* tenant scoping — implicit (django-tenants); optional ``?patient`` / ``?encounter``
  narrowing;
* audit — every state-changing action goes through the shared ``log_audit`` helper.

The order-set viewset adds maker-checker actions: ``submit`` (mint the approval
request) and ``apply`` (instantiate an approved set onto an encounter). Approval
decisions themselves are taken through the governance API.
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.permissions import HasPermission

from .models import Encounter
from .reconciliation_models import MedicationReconciliation, OrderSet
from .serializers_reconciliation import (
    MedicationReconciliationSerializer,
    OrderSetApplicationSerializer,
    OrderSetSerializer,
)
from .services.reconciliation import OrderSetService
from .views import log_audit

_READ_ACTIONS = {"list", "retrieve"}


class MedicationReconciliationViewSet(viewsets.ModelViewSet):
    """Per-encounter medication reconciliation with immutable, audited decisions."""

    serializer_class = MedicationReconciliationSerializer
    http_method_names = ("get", "post", "head", "options")

    def get_queryset(self):
        qs = MedicationReconciliation.objects.select_related(
            "patient", "encounter", "author"
        ).prefetch_related("items")
        patient_id = self.request.query_params.get("patient")
        encounter_id = self.request.query_params.get("encounter")
        if patient_id:
            qs = qs.filter(patient_id=patient_id)
        if encounter_id:
            qs = qs.filter(encounter_id=encounter_id)
        return qs

    def get_permissions(self):
        permission = "emr.read" if self.action in _READ_ACTIONS else "emr.write"
        return [IsAuthenticated(), HasPermission(permission)]

    def perform_create(self, serializer):
        reconciliation = serializer.save(author=self.request.user)
        log_audit(
            self.request,
            "medication_reconciliation_create",
            "MedicationReconciliation",
            reconciliation.id,
            new_data={
                "encounter": str(reconciliation.encounter_id),
                "moment": reconciliation.moment,
                "decisions": [
                    {"medication": i.medication_name, "action": i.action, "reason": i.reason}
                    for i in reconciliation.items.all()
                ],
            },
        )

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        reconciliation = self.get_object()
        try:
            reconciliation.complete()
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages[0]}, status=status.HTTP_409_CONFLICT)
        log_audit(
            request,
            "medication_reconciliation_complete",
            "MedicationReconciliation",
            reconciliation.id,
        )
        return Response(self.get_serializer(reconciliation).data)


class OrderSetViewSet(viewsets.ModelViewSet):
    """Versioned, approval-gated order sets applicable to an encounter."""

    serializer_class = OrderSetSerializer
    http_method_names = ("get", "post", "head", "options")

    def get_queryset(self):
        qs = OrderSet.objects.select_related("created_by", "approval").prefetch_related("items")
        key = self.request.query_params.get("key")
        state = self.request.query_params.get("status")
        if key:
            qs = qs.filter(key=key)
        if state:
            qs = qs.filter(status=state)
        return qs

    def get_permissions(self):
        permission = "emr.read" if self.action in _READ_ACTIONS else "emr.write"
        return [IsAuthenticated(), HasPermission(permission)]

    def perform_create(self, serializer):
        order_set = serializer.save(created_by=self.request.user)
        log_audit(
            self.request,
            "order_set_create",
            "OrderSet",
            order_set.id,
            new_data={"key": order_set.key, "version": order_set.version},
        )

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        order_set = self.get_object()
        step_permissions = request.data.get("step_permissions") or None
        try:
            approval = OrderSetService.submit(
                order_set=order_set,
                requested_by=request.user,
                step_permissions=step_permissions,
            )
        except DjangoValidationError as exc:
            raise ValidationError(exc.messages) from exc
        log_audit(request, "order_set_submit", "OrderSet", order_set.id)
        return Response(
            {"approval": str(approval.pk), "status": order_set.status},
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=True, methods=["post"])
    def apply(self, request, pk=None):
        order_set = self.get_object()
        # Keep the order set's status in sync with any pending approval decision.
        OrderSetService.sync_from_approval(order_set=order_set)
        encounter_id = request.data.get("encounter")
        try:
            encounter = Encounter.objects.get(pk=encounter_id)
        except (Encounter.DoesNotExist, ValueError, TypeError) as exc:
            raise ValidationError({"encounter": "Encontro inválido."}) from exc
        try:
            application = order_set.apply_to_encounter(encounter, request.user)
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages[0]}, status=status.HTTP_409_CONFLICT)
        log_audit(
            request,
            "order_set_apply",
            "OrderSet",
            order_set.id,
            new_data={"encounter": str(encounter.id), "application": str(application.id)},
        )
        return Response(
            OrderSetApplicationSerializer(application).data, status=status.HTTP_201_CREATED
        )
