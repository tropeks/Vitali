"""Sprint M2-S2 — RH operacional: cargo, lotação, férias/afastamento e escala.

Kept in a dedicated module so the parent worktree merge touches ``models.py`` by
exactly one line (the ``from .rh_models import *`` at the end of that file).

Contents:
  * ``Position`` — cargo (title + CBO). ``cbo`` is a plain ``CharField`` FOR NOW;
    a parallel sprint S1 builds ``core.CBOCode`` and the parent converts this to a
    FK at integration. Do NOT reference ``core.CBOCode`` here — it does not exist.
  * ``EmployeeAssignment`` — lotação: binds an ``Employee`` to an
    ``organization.OrganizationalUnit`` (and optional ``CostCenter``) for a
    vigência ``[start_date, end_date]``. At most ONE active assignment per
    employee (partial unique constraint; ``AssignmentService.assign`` closes the
    prior one).
  * ``Dependent`` — dependentes de um funcionário.
  * ``LeaveRequest`` — férias/afastamento aprovado via governance maker-checker.
  * ``DutyRoster`` / ``RosterSlot`` — escala assistencial; ``RosterSlot.on_duty``
    feeds the emr availability read-side (see ``hr.roster_integration``).
"""

from __future__ import annotations

import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from .models import Employee


class Position(models.Model):
    """Cargo — a named role/function with an (eventual) CBO classification."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField("Título", max_length=160)
    # NOTE: plain CharField for now. Parallel sprint S1 builds core.CBOCode; the
    # parent converts this to a FK at integration. Do NOT reference core.CBOCode.
    cbo = models.CharField("CBO", max_length=16, blank=True, default="", db_index=True)
    active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["title"]
        verbose_name = "Cargo"
        verbose_name_plural = "Cargos"

    def __str__(self):
        return f"{self.title} ({self.cbo})" if self.cbo else self.title


class EmployeeAssignment(models.Model):
    """Lotação — an employee's posting to an organizational unit for a vigência."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="assignments")
    unit = models.ForeignKey(
        "organization.OrganizationalUnit",
        on_delete=models.PROTECT,
        related_name="employee_assignments",
    )
    cost_center = models.ForeignKey(
        "organization.CostCenter",
        on_delete=models.PROTECT,
        related_name="employee_assignments",
        null=True,
        blank=True,
    )
    position = models.ForeignKey(
        Position,
        on_delete=models.PROTECT,
        related_name="assignments",
        null=True,
        blank=True,
    )
    role = models.CharField("Função", max_length=160, blank=True, default="")
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-start_date"]
        verbose_name = "Lotação"
        verbose_name_plural = "Lotações"
        constraints = [
            models.UniqueConstraint(
                fields=["employee"],
                condition=models.Q(active=True),
                name="hr_one_active_assignment_per_employee",
            ),
            models.CheckConstraint(
                condition=models.Q(end_date__isnull=True)
                | models.Q(end_date__gte=models.F("start_date")),
                name="hr_assignment_valid_vigency",
            ),
        ]

    def __str__(self):
        return f"{self.employee} @ {self.unit} ({self.start_date})"


class Dependent(models.Model):
    """Dependente de um funcionário (RH/benefícios)."""

    RELATIONSHIP_CHOICES = [
        ("spouse", "Cônjuge/companheiro(a)"),
        ("child", "Filho(a)"),
        ("parent", "Pai/Mãe"),
        ("other", "Outro"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="dependents")
    full_name = models.CharField("Nome", max_length=255)
    relationship = models.CharField(max_length=16, choices=RELATIONSHIP_CHOICES)
    birth_date = models.DateField(null=True, blank=True)
    cpf = models.CharField(max_length=14, blank=True, default="")
    is_income_tax_dependent = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["full_name"]
        verbose_name = "Dependente"
        verbose_name_plural = "Dependentes"

    def __str__(self):
        return f"{self.full_name} ({self.get_relationship_display()})"


class LeaveRequest(models.Model):
    """Férias/afastamento — approved through the governance maker-checker.

    ``LeaveService.request_leave`` opens a ``governance.ApprovalRequest`` and links
    it here. Self-approval (requester == approver) is blocked by
    ``ApprovalService.decide`` itself. Once ``status == 'approved'`` the leave is
    active for ``[start_date, end_date]`` (see :meth:`is_active_on`).
    """

    class Type(models.TextChoices):
        VACATION = "vacation", "Férias"
        SICK = "sick", "Afastamento médico"
        MATERNITY = "maternity", "Licença-maternidade"
        PATERNITY = "paternity", "Licença-paternidade"
        UNPAID = "unpaid", "Licença não remunerada"
        OTHER = "other", "Outro"

    class Status(models.TextChoices):
        PENDING = "pending", "Pendente"
        APPROVED = "approved", "Aprovada"
        REJECTED = "rejected", "Rejeitada"
        CANCELLED = "cancelled", "Cancelada"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="leave_requests")
    leave_type = models.CharField(max_length=16, choices=Type.choices)
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    reason = models.TextField(blank=True, default="")
    requested_by = models.ForeignKey(
        "core.User", on_delete=models.PROTECT, related_name="hr_leave_requests"
    )
    approval = models.OneToOneField(
        "governance.ApprovalRequest",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="hr_leave_request",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Statuses that occupy the employee's calendar (block overlapping requests).
    BLOCKING_STATUSES = ("pending", "approved")

    class Meta:
        ordering = ["-start_date"]
        verbose_name = "Solicitação de afastamento"
        verbose_name_plural = "Solicitações de afastamento"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_date__gte=models.F("start_date")),
                name="hr_leave_valid_period",
            ),
        ]

    def is_active_on(self, when) -> bool:
        """True if this is an approved leave covering the date ``when``."""
        return self.status == self.Status.APPROVED and self.start_date <= when <= self.end_date

    def __str__(self):
        return f"{self.employee} — {self.get_leave_type_display()} ({self.status})"


class DutyRoster(models.Model):
    """Escala assistencial — a named duty roster over a period at a facility."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    facility = models.ForeignKey(
        "organization.Facility", on_delete=models.PROTECT, related_name="duty_rosters"
    )
    name = models.CharField(max_length=160)
    start_date = models.DateField()
    end_date = models.DateField()
    active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-start_date"]
        verbose_name = "Escala"
        verbose_name_plural = "Escalas"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_date__gte=models.F("start_date")),
                name="hr_roster_valid_period",
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.start_date}→{self.end_date})"


class RosterSlot(models.Model):
    """A single shift on a :class:`DutyRoster` for a professional or employee.

    ``on_duty`` powers the emr availability read-side: when a professional has any
    slot for a given day, they are only available inside a covering slot's window
    (see ``hr.roster_integration``). A day with no slots leaves availability
    unconstrained (backward compatible with pre-roster scheduling).
    """

    class Shift(models.TextChoices):
        MORNING = "morning", "Manhã"
        AFTERNOON = "afternoon", "Tarde"
        NIGHT = "night", "Noite"
        FULL = "full", "Integral"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    roster = models.ForeignKey(DutyRoster, on_delete=models.CASCADE, related_name="slots")
    professional = models.ForeignKey(
        "emr.Professional",
        on_delete=models.CASCADE,
        related_name="roster_slots",
        null=True,
        blank=True,
    )
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="roster_slots",
        null=True,
        blank=True,
    )
    unit = models.ForeignKey(
        "organization.OrganizationalUnit",
        on_delete=models.PROTECT,
        related_name="roster_slots",
        null=True,
        blank=True,
    )
    date = models.DateField(db_index=True)
    shift = models.CharField(max_length=16, choices=Shift.choices, default=Shift.FULL)
    start_time = models.TimeField()
    end_time = models.TimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date", "start_time"]
        verbose_name = "Plantão"
        verbose_name_plural = "Plantões"
        indexes = [
            models.Index(fields=["unit", "date"]),
            models.Index(fields=["professional", "date"]),
        ]
        constraints = [
            # S-IA2: an overnight plantão (e.g. 19h→07h) is a real shift, so
            # end_time < start_time is allowed and MEANS "ends next day". Only a
            # zero-length window (end == start) is rejected.
            models.CheckConstraint(
                condition=~models.Q(end_time=models.F("start_time")),
                name="hr_rosterslot_valid_window",
            ),
        ]

    @property
    def is_overnight(self) -> bool:
        """True when the shift crosses midnight (end_time on the following day)."""
        return bool(self.start_time and self.end_time and self.end_time < self.start_time)

    def clean(self):
        super().clean()
        if self.professional_id is None and self.employee_id is None:
            raise ValidationError("Informe um profissional ou um funcionário para o plantão.")
        # end == start is a zero-length window (invalid); end < start is a valid
        # overnight plantão (ends next day), so only equality is rejected.
        if self.start_time and self.end_time and self.end_time == self.start_time:
            raise ValidationError({"end_time": "Horário de fim não pode ser igual ao início."})

    @classmethod
    def on_duty(cls, unit, when):
        """RosterSlots covering ``when`` (aware datetime) in ``unit``.

        Returns the queryset of active-roster slots for ``unit`` (dated on
        ``when``'s day) whose shift window contains its time. A same-day slot
        (start < end) covers ``[start, end)``; an overnight slot (start > end,
        e.g. 19h→07h) covers ``[start, 24h)`` and ``[00h, end)`` — so both 23:00
        and 05:00 fall inside a 19h→07h plantão.
        """
        when_local = timezone.localtime(when) if timezone.is_aware(when) else when
        t = when_local.time()
        overnight = models.Q(start_time__gt=models.F("end_time"))
        same_day_cover = models.Q(start_time__lte=t, end_time__gt=t)
        overnight_cover = overnight & (models.Q(start_time__lte=t) | models.Q(end_time__gt=t))
        return cls.objects.filter(
            unit=unit,
            roster__active=True,
            date=when_local.date(),
        ).filter((~overnight & same_day_cover) | overnight_cover)

    def __str__(self):
        who = self.professional_id or self.employee_id
        return f"{who} — {self.date} {self.get_shift_display()}"
