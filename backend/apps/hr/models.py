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
