"""Sprint E5 — Agenda multi-recurso.

New scheduling models kept in a dedicated module so the parent worktree merge
touches ``models.py`` by exactly one line (the ``from .scheduling_models import *``
at the end of that file).

Contents:
  * ``Resource`` — bookable room/equipment attached to an ``organization.Facility``.
  * ``AppointmentResource`` — through link reserving a resource for an appointment,
    enforcing anti-double-booking PER RESOURCE (today ``Appointment`` only guards
    per professional).
  * ``ScheduleException`` — date-specific vacation/holiday/block over a
    professional's weekly ``ScheduleConfig`` grid; consumed by the availability
    helper in ``services/scheduling.py``.

Tenant scoping and appointment status semantics mirror ``Appointment``.
"""

from __future__ import annotations

import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

# Statuses that occupy a slot — must stay in sync with Appointment.clean().
ACTIVE_APPOINTMENT_STATUSES = ["scheduled", "confirmed", "waiting", "in_progress"]

__all__ = ["Resource", "AppointmentResource", "ScheduleException"]


class Resource(models.Model):
    """A bookable physical resource (room or equipment) at a facility.

    Anti-double-booking is enforced by :class:`AppointmentResource`, not here:
    the resource is just the catalog row.
    """

    class Kind(models.TextChoices):
        ROOM = "room", "Sala"
        EQUIPMENT = "equipment", "Equipamento"
        OTHER = "other", "Outro"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=160)
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.ROOM, db_index=True)
    facility = models.ForeignKey(
        "organization.Facility", on_delete=models.PROTECT, related_name="resources"
    )
    active = models.BooleanField(default=True, db_index=True)
    # M2M declared here (not on Appointment) so the merge never touches Appointment.
    appointments = models.ManyToManyField(
        "emr.Appointment", through="AppointmentResource", related_name="resources"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Recurso"
        verbose_name_plural = "Recursos"
        indexes = [
            models.Index(fields=["facility", "active"]),
            models.Index(fields=["kind", "active"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.get_kind_display()})"


class AppointmentResource(models.Model):
    """Reserves a :class:`Resource` for an ``Appointment``.

    Enforces anti-double-booking PER RESOURCE: a resource cannot be linked to two
    appointments whose time intervals overlap (considering only slot-occupying
    statuses). This complements ``Appointment.clean()``'s per-professional guard.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    appointment = models.ForeignKey(
        "emr.Appointment", on_delete=models.CASCADE, related_name="resource_links"
    )
    resource = models.ForeignKey(
        Resource, on_delete=models.PROTECT, related_name="appointment_links"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "Recurso do agendamento"
        verbose_name_plural = "Recursos dos agendamentos"
        constraints = [
            models.UniqueConstraint(
                fields=["appointment", "resource"],
                name="emr_unique_appointment_resource",
            )
        ]
        indexes = [models.Index(fields=["resource", "appointment"])]

    def clean(self):
        super().clean()
        appointment = self.appointment
        if appointment is None or appointment.start_time is None or appointment.end_time is None:
            return
        # Only slot-occupying appointments conflict; a cancelled/no_show one frees
        # the resource.
        if appointment.status not in ACTIVE_APPOINTMENT_STATUSES:
            return
        overlapping = (
            AppointmentResource.objects.filter(
                resource=self.resource,
                appointment__status__in=ACTIVE_APPOINTMENT_STATUSES,
                appointment__start_time__lt=appointment.end_time,
                appointment__end_time__gt=appointment.start_time,
            )
            .exclude(pk=self.pk)
            .exclude(appointment=appointment)
        )
        if overlapping.exists():
            raise ValidationError({"resource": "RESOURCE_UNAVAILABLE"})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.resource} @ {self.appointment_id}"


class ScheduleException(models.Model):
    """Date-specific override that removes availability from a weekly grid.

    Covers vacations, holidays and ad-hoc blocks. Applies to an inclusive date
    range ``[start_date, end_date]``. When ``start_time``/``end_time`` are null the
    whole day(s) are blocked; otherwise only that intra-day window is blocked
    (partial-day block). Availability computation (see ``services/scheduling.py``)
    honours these regardless of what the weekly ``ScheduleConfig`` grid allows.
    """

    class Kind(models.TextChoices):
        VACATION = "vacation", "Férias"
        HOLIDAY = "holiday", "Feriado"
        BLOCK = "block", "Bloqueio"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    professional = models.ForeignKey(
        "emr.Professional", on_delete=models.CASCADE, related_name="schedule_exceptions"
    )
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.BLOCK, db_index=True)
    start_date = models.DateField(db_index=True)
    end_date = models.DateField(db_index=True)
    # Null start/end time => whole-day block. Both must be set together for a
    # partial-day window.
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    reason = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(
        "core.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="schedule_exceptions_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["start_date", "start_time"]
        verbose_name = "Exceção de agenda"
        verbose_name_plural = "Exceções de agenda"
        indexes = [
            models.Index(fields=["professional", "start_date", "end_date"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_date__gte=models.F("start_date")),
                name="emr_schedule_exception_date_order",
            ),
        ]

    def clean(self):
        super().clean()
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": "Data final deve ser após a inicial."})
        # start_time / end_time are all-or-nothing.
        if (self.start_time is None) != (self.end_time is None):
            raise ValidationError(
                {"start_time": "Informe início E fim do intervalo, ou nenhum (dia inteiro)."}
            )
        if self.start_time and self.end_time and self.end_time <= self.start_time:
            raise ValidationError({"end_time": "Horário de fim deve ser após o início."})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def blocks(self, start, end) -> bool:
        """True if this exception blocks the aware interval ``[start, end)``."""
        start_l = timezone.localtime(start)
        end_l = timezone.localtime(end)
        day = start_l.date()
        if not (self.start_date <= day <= self.end_date):
            return False
        if self.start_time is None or self.end_time is None:
            return True  # whole-day block
        return start_l.time() < self.end_time and end_l.time() > self.start_time

    @classmethod
    def is_blocked(cls, professional, start, end) -> bool:
        """True if any exception for ``professional`` blocks ``[start, end)``."""
        day = timezone.localtime(start).date()
        candidates = cls.objects.filter(
            professional=professional, start_date__lte=day, end_date__gte=day
        )
        return any(exc.blocks(start, end) for exc in candidates)

    def __str__(self):
        return f"{self.get_kind_display()} {self.professional_id} {self.start_date}→{self.end_date}"
