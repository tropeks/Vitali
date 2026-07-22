"""HR ViewSets — Sprint 18 / E-013 Workflow Intelligence v0.

list/retrieve/update delegate to DRF mixins.
create() is an explicit method that delegates to EmployeeOnboardingService
(locked decision 1A — service-layer, NOT signals due to FK ordering).
destroy() delegates to EmployeeDeactivationService (F-15 soft-delete cascade).
"""

from django.db import transaction
from rest_framework import mixins, viewsets
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Employee, OccupationalHealthExam, TimeEntry, WorkSchedule
from .serializers import (
    EmployeeOnboardingSerializer,
    EmployeeSerializer,
    OccupationalHealthExamSerializer,
    TimeEntrySerializer,
    WorkScheduleSerializer,
)
from .services import AttendanceService, EmployeeOnboardingService

# Actions that mutate the Employee row and must therefore run inside a
# transaction while holding a row lock (F-15 termination atomicity).
_LOCKING_ACTIONS = frozenset({"update", "partial_update", "destroy"})


class EmployeeViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    queryset = Employee.objects.select_related("user__role").all()
    serializer_class = EmployeeSerializer
    permission_classes = [IsAuthenticated]

    def get_permissions(self):
        if self.action == "create":
            from apps.core.permissions import HasPermission

            return [IsAuthenticated(), HasPermission("admin")]
        return super().get_permissions()

    def get_queryset(self):
        qs = Employee.objects.select_related("user__role").all()
        include_terminated = (
            self.request.query_params.get("include_terminated", "").lower() == "true"
        )
        if not include_terminated:
            qs = qs.filter(employment_status="active")
        return qs

    def get_object(self):
        """Resolve the Employee, taking a row lock for mutating actions.

        For update/partial_update/destroy the row is re-fetched with
        ``select_for_update()`` so concurrent termination requests serialize:
        the second request blocks until the first commits, then the pre_save
        signal reads the *committed* status and correctly no-ops instead of
        double-running the F-15 cascade. Requires the surrounding
        ``transaction.atomic`` on those actions (see below).
        """
        employee = super().get_object()
        if self.action in _LOCKING_ACTIONS:
            # No select_related here: FOR UPDATE cannot lock the nullable side
            # of the user__role outer join; lock only the Employee row.
            employee = Employee.objects.select_for_update().get(pk=employee.pk)
        return employee

    def create(self, request):
        """
        POST /api/v1/hr/employees/

        Deserializes payload then delegates to EmployeeOnboardingService which
        atomically creates Employee + User + (optional) Professional and writes
        AuditLog entries sharing a correlation_id (locked decision 2A).

        WhatsApp setup is queued post-commit if opted in (locked decision 1B).
        Invite mode (auth_mode='invite') raises 501 until T6 lands.
        """
        serializer = EmployeeOnboardingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        service = EmployeeOnboardingService(requesting_user=request.user)
        try:
            employee = service.onboard(serializer.validated_data)
        except NotImplementedError as exc:
            return Response({"error": str(exc)}, status=501)
        except DRFValidationError as exc:
            return Response({"error": exc.detail}, status=400)

        validated = serializer.validated_data
        whatsapp_queued = bool(
            validated.get("setup_whatsapp", False) and getattr(employee.user, "phone", "")
        )

        response_data = {
            "employee_id": str(employee.id),
            "user_id": str(employee.user.id),
            "professional_id": (
                str(employee.user.professional.id)
                if hasattr(employee.user, "professional")
                else None
            ),
            "whatsapp_setup_queued": whatsapp_queued,
            "correlation_id": service.correlation_id,
        }
        return Response(response_data, status=201)

    @transaction.atomic
    def destroy(self, request, *args, **kwargs):
        """
        DELETE /api/v1/hr/employees/{id}/

        F-15 soft-delete cascade:
        - Sets employment_status="terminated" + terminated_at
        - Deactivates User.is_active
        - Blacklists all outstanding JWT tokens (idempotent)
        - Deactivates Professional if clinical
        - Writes AuditLog chain with shared correlation_id (decision 2A)

        Returns 200 with updated Employee row (not 204 — soft-delete preserves data).
        """
        from apps.hr.services import EmployeeDeactivationService

        employee = self.get_object()
        service = EmployeeDeactivationService()
        result = service.deactivate(employee, requesting_user=request.user)
        return Response(
            {
                **EmployeeSerializer(result["employee"]).data,
                "tokens_revoked": result["tokens_revoked"],
                "tokens_already_blacklisted": result["tokens_already_blacklisted"],
                "api_keys_revoked": result["api_keys_revoked"],
                "professional_deactivated": result["professional_deactivated"],
                "schedule_deactivated": result["schedule_deactivated"],
                "user_deactivated": result["user_deactivated"],
            },
            status=200,
        )

    @transaction.atomic
    def update(self, request, *args, **kwargs):
        """PUT and PATCH share this path (DRF partial_update delegates here).

        Wrapped in ``transaction.atomic`` so a termination via
        ``employment_status="terminated"`` commits the status flip, the
        post_save signal, and the whole F-15 revocation cascade as ONE unit:
        if any cascade step fails, the flip rolls back too — no "terminated"
        employee left in the DB with live sessions and an active agenda (and no
        silent-no-op retry, since the status never persisted).
        """
        return super().update(request, *args, **kwargs)

    def perform_update(self, serializer):
        """Save + F-15 actor attribution + reactivation hook.

        Actor attribution: ``request.user`` is stashed on the instance before
        saving so the termination post_save signal (apps.hr.signals) forwards
        it as ``requesting_user`` — cascade AuditLog entries then record the
        admin who issued the PATCH instead of ``user=None``.

        Reactivation hook: if employment_status flips back to "active",
        re-enables User.is_active and writes an employee_reactivated AuditLog
        entry. No token un-blacklist — user must set a new password via
        standard flow. Runs here (on the already-saved instance) rather than
        re-resolving get_object() after the update: a just-terminated employee
        drops out of the default active-only queryset, and the resulting 404
        would abort — and, under the atomic update(), roll back — a successful
        termination.
        """
        serializer.instance._f15_acting_user = self.request.user
        employee = serializer.save()
        if employee.employment_status == "active" and not employee.user.is_active:
            employee.user.is_active = True
            employee.user.save(update_fields=["is_active"])
            from apps.core.models import AuditLog

            AuditLog.objects.create(
                user=self.request.user,
                action="employee_reactivated",
                resource_type="employee",
                resource_id=str(employee.id),
                new_data={"user_id": str(employee.user.id)},
            )


class HRManagePermissionMixin:
    permission_classes = [IsAuthenticated]

    def get_permissions(self):
        from apps.core.permissions import HasPermission

        return [IsAuthenticated(), HasPermission("hr.manage")]


class WorkScheduleViewSet(HRManagePermissionMixin, viewsets.ModelViewSet):
    queryset = WorkSchedule.objects.select_related("employee__user").all()
    serializer_class = WorkScheduleSerializer

    def perform_create(self, serializer):
        from apps.core.models import AuditLog

        schedule = serializer.save()
        AuditLog.objects.create(
            user=self.request.user,
            action="work_schedule_created",
            resource_type="work_schedule",
            resource_id=str(schedule.id),
            new_data={
                "employee_id": str(schedule.employee_id),
                "weekly_hours": str(schedule.weekly_hours),
                "effective_from": schedule.effective_from.isoformat(),
            },
        )


class OccupationalHealthExamViewSet(HRManagePermissionMixin, viewsets.ModelViewSet):
    queryset = OccupationalHealthExam.objects.select_related("employee__user").all()
    serializer_class = OccupationalHealthExamSerializer

    def perform_create(self, serializer):
        from apps.core.models import AuditLog

        exam = serializer.save(recorded_by=self.request.user)
        AuditLog.objects.create(
            user=self.request.user,
            action="occupational_health_exam_recorded",
            resource_type="occupational_health_exam",
            resource_id=str(exam.id),
            new_data={
                "employee_id": str(exam.employee_id),
                "exam_type": exam.exam_type,
                "result": exam.result,
                "expires_on": exam.expires_on.isoformat() if exam.expires_on else None,
            },
        )


class TimeEntryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = TimeEntry.objects.select_related("employee__user", "recorded_by").all()
    serializer_class = TimeEntrySerializer
    permission_classes = [IsAuthenticated]

    def _can_manage(self):
        role = self.request.user.effective_role()
        return self.request.user.is_superuser or bool(role and "hr.manage" in role.permissions)

    def get_queryset(self):
        queryset = super().get_queryset()
        if self._can_manage():
            employee_id = self.request.query_params.get("employee")
            return queryset.filter(employee_id=employee_id) if employee_id else queryset
        return queryset.filter(employee__user=self.request.user)

    def create(self, request, *args, **kwargs):
        serializer = TimeEntrySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        employee = serializer.validated_data["employee"]
        if not self._can_manage() and employee.user_id != request.user.id:
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("Só é permitido registrar o próprio ponto.")
        entry, created = AttendanceService.record(
            employee=employee,
            actor=request.user,
            event_type=serializer.validated_data["event_type"],
            occurred_at=serializer.validated_data["occurred_at"],
            source=serializer.validated_data.get("source", "web"),
            external_id=serializer.validated_data.get("external_id"),
        )
        return Response(TimeEntrySerializer(entry).data, status=201 if created else 200)
