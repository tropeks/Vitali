"""Sprint E5 — availability computation and encaixe (overbooking) service.

``is_professional_available`` answers whether an interval falls inside a
professional's bookable time, honouring BOTH the weekly ``ScheduleConfig`` grid
and any ``ScheduleException`` (E5-T2).

``AppointmentSchedulingService`` books appointments and blocks any booking that
falls outside availability UNLESS it is an explicitly permitted, reason-bearing
encaixe (overbooking), which is written to the ``AuditLog`` trail (E5-T3).
"""

from __future__ import annotations

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.core.models import AuditLog
from apps.emr.models import Appointment, ScheduleConfig, ScheduleException

# RBAC permission required to authorise an encaixe (overbooking outside grid).
ENCAIXE_PERMISSION = "emr.appointment_encaixe"


def is_professional_available(professional, start, end) -> bool:
    """True if ``[start, end)`` is bookable for ``professional``.

    Requires an active ``ScheduleConfig`` and that the interval:
      * falls on a working weekday,
      * fits within working hours,
      * does not overlap the lunch window, and
      * is not covered by a ``ScheduleException`` (vacation/holiday/block).
    Times are compared in local wall-clock (``timezone.localtime``).
    """
    config = ScheduleConfig.objects.filter(professional=professional, is_active=True).first()
    if config is None:
        return False

    start_l = timezone.localtime(start)
    end_l = timezone.localtime(end)

    working_days = config.working_days if config.working_days else [0, 1, 2, 3, 4]
    if start_l.weekday() not in working_days:
        return False

    if start_l.time() < config.working_hours_start or end_l.time() > config.working_hours_end:
        return False

    if config.lunch_start and config.lunch_end:
        if start_l.time() < config.lunch_end and end_l.time() > config.lunch_start:
            return False

    if ScheduleException.is_blocked(professional, start, end):
        return False

    return True


class AppointmentSchedulingService:
    """Creates appointments, enforcing availability with an audited encaixe escape.

    Normal path: a booking outside the professional's availability is rejected.
    Encaixe path: with ``encaixe=True``, a non-empty reason AND a requesting user
    whose effective role holds :data:`ENCAIXE_PERMISSION`, the booking succeeds and
    an ``appointment_encaixe`` AuditLog row is written.
    """

    def __init__(self, requesting_user=None) -> None:
        self.requesting_user = requesting_user

    def create(
        self,
        *,
        patient,
        professional,
        start_time,
        end_time,
        type="consultation",
        status="scheduled",
        source="receptionist",
        notes="",
        encaixe: bool = False,
        encaixe_reason: str = "",
    ) -> Appointment:
        available = is_professional_available(professional, start_time, end_time)

        if not available:
            if not encaixe:
                raise ValidationError({"start_time": "OUTSIDE_AVAILABILITY"})
            self._authorize_encaixe(encaixe_reason)

        with transaction.atomic():
            appointment = Appointment.objects.create(
                patient=patient,
                professional=professional,
                start_time=start_time,
                end_time=end_time,
                type=type,
                status=status,
                source=source,
                notes=notes,
                created_by=self.requesting_user,
            )
            if not available and encaixe:
                AuditLog.objects.create(
                    user=self.requesting_user,
                    action="appointment_encaixe",
                    resource_type="appointment",
                    resource_id=str(appointment.id),
                    new_data={
                        "reason": encaixe_reason,
                        "professional_id": str(professional.id),
                        "patient_id": str(patient.id),
                        "start_time": start_time.isoformat(),
                        "end_time": end_time.isoformat(),
                    },
                )
        return appointment

    def _authorize_encaixe(self, encaixe_reason: str) -> None:
        role = None
        if self.requesting_user is not None:
            role = self.requesting_user.effective_role()
        if role is None or not role.has_permission(ENCAIXE_PERMISSION):
            raise PermissionDenied("ENCAIXE_NOT_PERMITTED")
        if not (encaixe_reason and encaixe_reason.strip()):
            raise ValidationError({"encaixe_reason": "ENCAIXE_REASON_REQUIRED"})
