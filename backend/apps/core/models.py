"""
HealthOS Core Models
====================
Public schema: Tenant, Domain, Plan, PlanModule, Subscription, FeatureFlag, TUSSCode,
               TUSSSyncLog, TenantAIConfig
Per-tenant: User, Role, AuditLog

Multi-tenancy via django-tenants (schema-per-tenant — ADR-004).
LGPD: CPF armazenado criptografado via django-encrypted-model-fields.
"""

import uuid

from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django_tenants.models import DomainMixin, TenantMixin
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
    status = models.CharField("Status", max_length=20, choices=Status.choices, default=Status.TRIAL)
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
    tenant = models.OneToOneField(Tenant, on_delete=models.CASCADE, related_name="subscription")
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
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="feature_flags")
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
    group = models.CharField(max_length=100)  # procedimento, material, diária, taxa…
    subgroup = models.CharField(max_length=100, blank=True)
    version = models.CharField(max_length=20)  # e.g. "2024-01"
    active = models.BooleanField(default=True, db_index=True)
    search_vector = SearchVectorField(null=True)  # pg_trgm + tsvector for fuzzy search

    class Meta:
        app_label = "core"
        verbose_name = "Código TUSS"
        verbose_name_plural = "Códigos TUSS"
        indexes = [GinIndex(fields=["search_vector"])]

    def __str__(self):
        return f"{self.code} — {self.description[:60]}"


class TUSSSyncLog(models.Model):
    """
    Records every `import_tuss` run. Lives in the PUBLIC schema (SHARED_APPS) alongside
    TUSSCode — the TUSS table is global, so its sync log is global too.
    Ops can verify the TUSS table is current from the billing overview badge without
    a DB console query.
    """

    class Status(models.TextChoices):
        SUCCESS = "success", "Sucesso"
        PARTIAL = "partial", "Parcial"
        ERROR = "error", "Erro"

    class Source(models.TextChoices):
        MANAGEMENT_COMMAND = "management_command", "Management Command"
        API = "api", "API"
        SCHEDULED = "scheduled", "Agendado"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ran_at = models.DateTimeField(auto_now_add=True, db_index=True)
    source = models.CharField(
        max_length=30,
        choices=Source.choices,
        default=Source.MANAGEMENT_COMMAND,
    )
    row_count_total = models.PositiveIntegerField(default=0)
    row_count_added = models.PositiveIntegerField(default=0)
    row_count_updated = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.SUCCESS)
    error_message = models.TextField(
        blank=True,
        help_text="Scrubbed: connection strings stripped, max 200 chars",
    )
    duration_ms = models.PositiveIntegerField(default=0)

    class Meta:
        app_label = "core"
        verbose_name = "TUSS Sync Log"
        verbose_name_plural = "TUSS Sync Logs"
        ordering = ["-ran_at"]

    def __str__(self):
        return f"TUSSSyncLog {self.status} @ {self.ran_at:%Y-%m-%d %H:%M} ({self.row_count_added}+{self.row_count_updated} rows)"


class TenantAIConfig(models.Model):
    """
    Per-tenant AI feature toggles and rate limits.
    Lives in the PUBLIC schema (SHARED_APPS), FK to Tenant.
    Django Admin runs in public schema context — tenant-schema models crash there.
    This is the standard django-tenants pattern for per-tenant configuration.

    Cache TTL: 5 minutes. Django Admin saves do NOT auto-invalidate the cache.
    Ops enabling/disabling AI will see up to 5-minute lag before effect.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.OneToOneField(
        Tenant,
        on_delete=models.CASCADE,
        related_name="ai_config",
    )
    ai_tuss_enabled = models.BooleanField(
        "AI TUSS Auto-Coding ativado",
        default=False,
        help_text="Habilita sugestão automática de códigos TUSS via IA para este tenant.",
    )
    ai_glosa_prediction_enabled = models.BooleanField(
        "AI Glosa Prediction ativado",
        default=False,
        help_text="Habilita predição de risco de glosa por item de guia para este tenant.",
    )
    rate_limit_per_hour = models.PositiveIntegerField(
        "Limite de chamadas/hora",
        default=500,
        help_text=(
            "Default 500/hr covers 10-item guide creation with edits and insurer changes. "
            "Reduce per-tenant if cost control is needed."
        ),
        validators=[MinValueValidator(10), MaxValueValidator(2000)],
    )
    monthly_token_ceiling = models.PositiveIntegerField(
        "Teto mensal de tokens",
        default=500000,
        help_text="Claude tokens/mês. A IA degrada silenciosamente quando excedido.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "core"
        verbose_name = "Configuração de IA por Tenant"
        verbose_name_plural = "Configurações de IA por Tenant"

    def __str__(self):
        return f"TenantAIConfig({self.tenant.schema_name})"


# ─── S-064: CID-10 Code Table (Public Schema) ────────────────────────────────


class CID10Code(models.Model):
    """
    ICD-10 (CID-10) diagnosis code table. Lives in the PUBLIC schema,
    shared across all tenants. Imported via `import_cid10` management command.
    Data source: DATASUS CID10CM_tabela.csv (SUBCAT, DESCRICAO columns).

    Follows the same pattern as TUSSCode (Sprint 8).
    CID10Suggester validates all LLM suggestions against this table (anti-hallucination gate).
    """

    code = models.CharField(max_length=10, unique=True, db_index=True)
    description = models.CharField(max_length=500)
    active = models.BooleanField(default=True, db_index=True)
    search_vector = SearchVectorField(null=True)

    class Meta:
        app_label = "core"
        verbose_name = "CID-10"
        verbose_name_plural = "CID-10 Codes"
        indexes = [GinIndex(fields=["search_vector"])]

    def __str__(self):
        return f"{self.code} — {self.description[:60]}"


# ─── S-063: AI DPA Status (Public Schema) ────────────────────────────────────


class AIDPAStatus(models.Model):
    """
    Tracks whether a tenant has a signed Data Processing Agreement (DPA) with
    Anthropic/OpenAI, required before enabling ai_prescription_safety feature
    (LGPD Art. 11 — health data is 'dados sensíveis').

    Without a DPA, the ai_prescription_safety feature flag must remain OFF.
    Checked by PrescriptionSafetyChecker before any LLM call.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.OneToOneField(Tenant, on_delete=models.CASCADE, related_name="ai_dpa_status")
    dpa_signed_date = models.DateField(null=True, blank=True)
    dpa_file_url = models.URLField(blank=True)
    signed_by_user = models.ForeignKey(
        "core.User", on_delete=models.SET_NULL, null=True, blank=True
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "core"
        verbose_name = "AI DPA Status"
        verbose_name_plural = "AI DPA Statuses"

    @property
    def is_signed(self):
        return self.dpa_signed_date is not None

    def __str__(self):
        status = "SIGNED" if self.is_signed else "UNSIGNED"
        return f"AIDPAStatus({self.tenant.schema_name}, {status})"


# ─── S-062: TOTP Device (Public Schema) ──────────────────────────────────────


class TOTPDevice(models.Model):
    """
    Custom TOTP MFA device. Stores the TOTP secret encrypted at rest (LGPD).
    Lives in the PUBLIC schema because User is in public schema (SHARED_APPS).

    Build with pyotp — does NOT use django-otp to avoid migration sequencing
    conflict with the billing_migrations workaround (plan decision D-14, E-14).

    Backup codes are stored as an encrypted JSON list of hashed codes.
    Each code is single-use: consumed codes are removed from the list.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField("core.User", on_delete=models.CASCADE, related_name="totp_device")
    # Encrypted TOTP base32 secret (LGPD)
    encrypted_secret = EncryptedCharField(max_length=200)
    # Encrypted JSON list of hashed single-use backup codes
    encrypted_backup_codes = EncryptedCharField(max_length=2000, default="[]")
    is_active = models.BooleanField(default=False, db_index=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "core"
        verbose_name = "TOTP Device"
        verbose_name_plural = "TOTP Devices"

    def __str__(self):
        status = "active" if self.is_active else "pending"
        return f"TOTPDevice({self.user.email}, {status})"


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
            models.Index(fields=["action", "created_at"], name="core_auditlog_act_created_idx"),
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


# ─── S-055: PIX Webhook Tenant Resolution (Public Schema) ─────────────────────


class AsaasChargeMap(models.Model):
    """
    Maps Asaas charge IDs to tenant schemas (public schema table).
    Enables webhook handler to resolve which tenant schema owns a given charge
    without scanning all tenant schemas.

    Created when a PIXCharge is created (signal in billing.signals).
    Deleted when a PIXCharge is deleted.
    """

    asaas_charge_id = models.CharField(
        "Asaas Charge ID", max_length=100, unique=True, db_index=True
    )
    tenant_schema = models.CharField(
        "Tenant Schema",
        max_length=100,
        db_index=True,
        help_text="schema_name of the tenant that owns this charge",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "core"
        verbose_name = "Asaas Charge Map"
        verbose_name_plural = "Asaas Charge Maps"

    def __str__(self):
        return f"{self.asaas_charge_id} → {self.tenant_schema}"
