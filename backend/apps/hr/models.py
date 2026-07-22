"""HR (Recursos Humanos) models — Sprint 18 / E-013 Workflow Intelligence v0.

Employee is the canonical HR record for any clinic staff member with an active
User account. The OneToOneField to core.User keeps authentication separate from
HR metadata (hire_date, contract type, employment status). Soft-delete is the
default: terminated employees keep their row with employment_status="terminated"
and terminated_at timestamp, preserving CFM attribution.
"""

import uuid

from django.db import models


class Employee(models.Model):
    """HR record for clinic staff (doctors, nurses, receptionists, admins)."""

    EMPLOYMENT_STATUS_CHOICES = [
        ("active", "Ativo"),
        ("leave", "Afastado"),
        ("terminated", "Desligado"),
    ]
    CONTRACT_TYPE_CHOICES = [
        ("clt", "CLT"),
        ("pj", "PJ"),
        ("estagio", "Estágio"),
        ("temporary", "Temporário"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        "core.User",
        on_delete=models.CASCADE,
        related_name="employee",
    )
    hire_date = models.DateField()
    employment_status = models.CharField(
        max_length=20,
        choices=EMPLOYMENT_STATUS_CHOICES,
        default="active",
        db_index=True,
    )
    contract_type = models.CharField(
        max_length=20,
        choices=CONTRACT_TYPE_CHOICES,
    )
    terminated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Funcionário"
        verbose_name_plural = "Funcionários"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.full_name} ({self.get_employment_status_display()})"


class WorkSchedule(models.Model):
    """Effective-dated work schedule used for attendance reconciliation."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="work_schedules")
    weekly_hours = models.DecimalField(max_digits=5, decimal_places=2)
    timezone = models.CharField(max_length=64, default="America/Sao_Paulo")
    effective_from = models.DateField()
    effective_until = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-effective_from"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(weekly_hours__gt=0), name="hr_schedule_positive_hours"
            ),
            models.CheckConstraint(
                condition=models.Q(effective_until__isnull=True)
                | models.Q(effective_until__gte=models.F("effective_from")),
                name="hr_schedule_valid_period",
            ),
        ]

    def __str__(self):
        return f"{self.employee} — {self.weekly_hours}h"


class TimeEntry(models.Model):
    """Immutable clock event; corrections are separate compensating events."""

    EVENT_CHOICES = [("in", "Entrada"), ("out", "Saída")]
    SOURCE_CHOICES = [("web", "Web"), ("mobile", "Mobile"), ("device", "Relógio")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="time_entries")
    event_type = models.CharField(max_length=8, choices=EVENT_CHOICES)
    occurred_at = models.DateTimeField(db_index=True)
    source = models.CharField(max_length=16, choices=SOURCE_CHOICES, default="web")
    external_id = models.CharField(max_length=128, blank=True, default="")
    correction_of = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="corrections"
    )
    reason = models.CharField(max_length=255, blank=True)
    recorded_by = models.ForeignKey(
        "core.User", on_delete=models.PROTECT, related_name="recorded_time_entries"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-occurred_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["source", "external_id"],
                condition=~models.Q(external_id=""),
                name="hr_timeentry_source_external_unique",
            )
        ]

    def __str__(self):
        return f"{self.employee} — {self.event_type} @ {self.occurred_at.isoformat()}"


class OccupationalHealthExam(models.Model):
    """ASO/SST lifecycle without storing clinical findings in HR."""

    EXAM_TYPE_CHOICES = [
        ("admission", "Admissional"),
        ("periodic", "Periódico"),
        ("return", "Retorno ao trabalho"),
        ("role_change", "Mudança de risco"),
        ("termination", "Demissional"),
    ]
    RESULT_CHOICES = [("fit", "Apto"), ("unfit", "Inapto"), ("pending", "Pendente")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="health_exams")
    exam_type = models.CharField(max_length=24, choices=EXAM_TYPE_CHOICES)
    performed_on = models.DateField()
    expires_on = models.DateField(null=True, blank=True, db_index=True)
    result = models.CharField(max_length=16, choices=RESULT_CHOICES, default="pending")
    provider_name = models.CharField(max_length=255)
    certificate_reference = models.CharField(max_length=128, blank=True)
    restrictions = models.TextField(blank=True)
    recorded_by = models.ForeignKey(
        "core.User", on_delete=models.PROTECT, related_name="recorded_health_exams"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-performed_on"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(expires_on__isnull=True)
                | models.Q(expires_on__gte=models.F("performed_on")),
                name="hr_aso_valid_expiry",
            )
        ]

    def __str__(self):
        return f"{self.employee} — {self.get_exam_type_display()} ({self.performed_on})"
