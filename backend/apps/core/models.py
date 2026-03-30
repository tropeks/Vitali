"""
HealthOS Core Models
====================
Public schema: Tenant, Domain, Plan, PlanModule, Subscription, FeatureFlag, TUSSCode
Per-tenant: User, Role, AuditLog

Multi-tenancy via django-tenants (schema-per-tenant — ADR-004).
LGPD: CPF armazenado criptografado via django-encrypted-model-fields.
"""
import uuid

from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models
from django_tenants.models import TenantMixin, DomainMixin
from encrypted_model_fields.fields import EncryptedCharField

from .managers import UserManager


# ─── Public Schema Models ─────────────────────────────────────────────────────


class Tenant(TenantMixin, models.Model):
    """
    Represents a clinic/hospital. Each tenant gets its own PostgreSQL schema.
    schema_name is derived from slug and used by django-tenants for routing.
    """

    class Status(models.TextChoices):
        TRIAL = "trial", "Trial"
        ACTIVE = "active", "Ativo"
        SUSPENDED = "suspended", "Suspenso"
        CANCELLED = "cancelled", "Cancelado"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField("Nome da clínica", max_length=255)
    slug = models.SlugField("Slug", max_length=100, unique=True)
    # schema_name is required by TenantMixin — set equal to slug on save
    cnpj = models.CharField("CNPJ", max_length=18, unique=True, blank=True, null=True)
    status = models.CharField(
        "Status", max_length=20, choices=Status.choices, default=Status.TRIAL
    )
    trial_ends_at = models.DateTimeField("Fim do trial", null=True, blank=True)
    created_at = models.DateTimeField("Criado em", auto_now_add=True)
    updated_at = models.DateTimeField("Atualizado em", auto_now=True)

    # django-tenants requires auto_create_schema
    auto_create_schema = True

    class Meta:
        verbose_name = "Tenant"
        verbose_name_plural = "Tenants"

    def save(self, *args, **kwargs):
        if not self.schema_name:
            self.schema_name = self.slug
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.schema_name})"


class Domain(DomainMixin, models.Model):
    """Maps a hostname to a Tenant for django-tenants URL routing."""

    class Meta:
        verbose_name = "Domínio"
        verbose_name_plural = "Domínios"

    def __str__(self):
        return self.domain


class Plan(models.Model):
    """Subscription plan (Starter, Professional, Enterprise)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField("Nome", max_length=100)
    base_price = models.DecimalField("Preço base (R$)", max_digits=10, decimal_places=2)
    is_active = models.BooleanField("Ativo", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Plano"
        verbose_name_plural = "Planos"

    def __str__(self):
        return f"{self.name} — R${self.base_price}"


class PlanModule(models.Model):
    """Individual module within a plan (marketplace model)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name="modules")
    module_key = models.CharField(
        "Módulo",
        max_length=50,
        help_text="emr, billing, pharmacy, ai_tuss, whatsapp",
    )
    price = models.DecimalField("Preço adicional (R$)", max_digits=10, decimal_places=2)
    is_included = models.BooleanField("Incluso no plano base", default=False)

    class Meta:
        verbose_name = "Módulo do Plano"
        verbose_name_plural = "Módulos do Plano"
        unique_together = ("plan", "module_key")

    def __str__(self):
        return f"{self.plan.name} — {self.module_key}"


class Subscription(models.Model):
    """Active subscription linking a Tenant to a Plan + selected modules."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Ativo"
        PAST_DUE = "past_due", "Em atraso"
        CANCELLED = "cancelled", "Cancelado"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.OneToOneField(
        Tenant, on_delete=models.CASCADE, related_name="subscription"
    )
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="subscriptions")
    active_modules = models.JSONField(
        "Módulos ativos",
        default=list,
        help_text='["emr", "billing", "pharmacy", "ai_tuss", "whatsapp"]',
    )
    monthly_price = models.DecimalField("Mensalidade (R$)", max_digits=10, decimal_places=2)
    status = models.CharField(
        "Status", max_length=20, choices=Status.choices, default=Status.ACTIVE
    )
    current_period_start = models.DateField("Início do período")
    current_period_end = models.DateField("Fim do período")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Assinatura"
        verbose_name_plural = "Assinaturas"

    def __str__(self):
        return f"{self.tenant.name} — {self.plan.name} ({self.status})"


class FeatureFlag(models.Model):
    """Per-tenant module/feature toggle. Foundation of the modular billing system."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name="feature_flags"
    )
    module_key = models.CharField(
        "Módulo/Feature",
        max_length=50,
        help_text="emr, billing, pharmacy, ai_tuss, whatsapp, ai_scribe",
    )
    is_enabled = models.BooleanField("Habilitado", default=False)

    class Meta:
        verbose_name = "Feature Flag"
        verbose_name_plural = "Feature Flags"
        unique_together = ("tenant", "module_key")

    def __str__(self):
        status = "✓" if self.is_enabled else "✗"
        return f"{status} {self.tenant.schema_name} — {self.module_key}"


class TUSSCode(models.Model):
    """
    ANS TUSS procedure/material/fee code table. Lives in the public schema,
    shared across all tenants. ~6-8k rows imported via `import_tuss` command.

    Cross-schema FK note: PostgreSQL does NOT enforce referential integrity
    across schemas. on_delete=PROTECT on references to this model is
    application-layer only. A pre-delete signal compensates (see signals.py).
    """

    code = models.CharField(max_length=20, unique=True, db_index=True)
    description = models.TextField()
    group = models.CharField(max_length=100)        # procedimento, material, diária, taxa…
    subgroup = models.CharField(max_length=100, blank=True)
    version = models.CharField(max_length=20)       # e.g. "2024-01"
    active = models.BooleanField(default=True, db_index=True)
    search_vector = SearchVectorField(null=True)    # pg_trgm + tsvector for fuzzy search

    class Meta:
        app_label = "core"
        verbose_name = "Código TUSS"
        verbose_name_plural = "Códigos TUSS"
        indexes = [GinIndex(fields=["search_vector"])]

    def __str__(self):
        return f"{self.code} — {self.description[:60]}"


# ─── Per-Tenant Models ────────────────────────────────────────────────────────


class Role(models.Model):
    """RBAC role with JSON permission list. Lives in tenant schema."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(
        "Nome",
        max_length=50,
        help_text="admin, medico, enfermeiro, recepcionista, farmaceutico",
    )
    permissions = models.JSONField(
        "Permissões",
        default=list,
        help_text='["emr.read", "emr.write", "billing.read", "pharmacy.dispense"]',
    )
    is_system = models.BooleanField(
        "Role de sistema",
        default=False,
        help_text="Roles de sistema não podem ser excluídas.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Role"
        verbose_name_plural = "Roles"

    def __str__(self):
        return self.name

    def has_permission(self, perm: str) -> bool:
        return perm in self.permissions


class User(AbstractBaseUser, PermissionsMixin):
    """
    Custom user model for HealthOS.
    Lives in tenant schema — each clinic has its own user registry.
    CPF encrypted at rest (LGPD — dado pessoal sensível).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField("E-mail", unique=True)
    full_name = models.CharField("Nome completo", max_length=255)
    cpf = EncryptedCharField(
        "CPF",
        max_length=14,
        null=True,
        blank=True,
        help_text="Armazenado criptografado (LGPD).",
    )
    role = models.ForeignKey(
        Role,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="users",
        verbose_name="Role",
    )
    is_active = models.BooleanField("Ativo", default=True)
    is_staff = models.BooleanField("Staff", default=False)
    last_login = models.DateTimeField("Último acesso", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]

    objects = UserManager()

    class Meta:
        verbose_name = "Usuário"
        verbose_name_plural = "Usuários"

    def __str__(self):
        return f"{self.full_name} <{self.email}>"

    def has_role_permission(self, perm: str) -> bool:
        """Check if the user's role grants a specific permission."""
        if self.is_superuser:
            return True
        return bool(self.role and self.role.has_permission(perm))


class AuditLog(models.Model):
    """
    Append-only audit trail for all data changes.
    Required by CFM Res. 1.821/2007 (prontuário eletrônico).
    Lives in tenant schema. Never UPDATE or DELETE rows.
    """

    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="audit_logs",
        verbose_name="Usuário",
    )
    action = models.CharField(
        "Ação",
        max_length=50,
        help_text="create, update, delete, login, view_record",
    )
    resource_type = models.CharField(
        "Tipo de recurso",
        max_length=50,
        help_text="patient, prescription, encounter",
    )
    resource_id = models.CharField("ID do recurso", max_length=36, blank=True)
    old_data = models.JSONField("Dados anteriores", null=True, blank=True)
    new_data = models.JSONField("Dados novos", null=True, blank=True)
    ip_address = models.GenericIPAddressField("IP", null=True, blank=True)
    user_agent = models.TextField("User Agent", blank=True)
    created_at = models.DateTimeField("Criado em", auto_now_add=True)

    class Meta:
        verbose_name = "Audit Log"
        verbose_name_plural = "Audit Logs"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["resource_type", "resource_id"]),
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return f"{self.action} {self.resource_type}/{self.resource_id} by {self.user_id}"

    def save(self, *args, **kwargs):
        # Enforce append-only: block updates
        if self.pk:
            raise ValueError("AuditLog entries are immutable.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("AuditLog entries cannot be deleted.")
