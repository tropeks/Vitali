"""
HealthOS Core Models
====================
ALL models here live in the PUBLIC schema — apps.core is in SHARED_APPS only.
That includes User, Role and AuditLog: they are a single GLOBAL registry shared
across every tenant, NOT per-tenant tables. A user is bound to a tenant via
``UserTenantMembership`` (enforced by ``TenantJWTAuthentication`` when
``ENFORCE_TENANT_MEMBERSHIP`` is on); see ``apps.core.tenant_auth`` and
docs/plans/TENANT-MEMBERSHIP.md.

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

    # ── Clinical-compatibility metadata (glosa wedge PR G3b) ──────────────────
    # ANS-STANDARD TRUTH, NEVER FABRICATED IN CODE. These columns encode the
    # age/sex/CID restrictions the ANS publishes for a procedure. They are
    # populated ONLY by the `import_tuss` command FROM the ANS source export
    # (out of band). Until a row is populated, every field keeps its INERT
    # default (null window / sex "B" / empty whitelist) so the clinical_incompat
    # glosa check fires NOTHING — no fabricated clinical rule ever ships in code.
    SEX_CHOICES = [
        ("M", "Masculino"),
        ("F", "Feminino"),
        ("B", "Ambos/Qualquer"),  # B = both/any → no sex constraint (default)
    ]
    age_min_days = models.IntegerField(
        "Idade mínima (dias)",
        null=True,
        blank=True,
        help_text="Idade mínima do paciente para o procedimento, em dias. Null = sem limite inferior. Fonte: ANS.",
    )
    age_max_days = models.IntegerField(
        "Idade máxima (dias)",
        null=True,
        blank=True,
        help_text="Idade máxima do paciente para o procedimento, em dias. Null = sem limite superior. Fonte: ANS.",
    )
    sex_allowed = models.CharField(
        "Sexo permitido",
        max_length=1,
        choices=SEX_CHOICES,
        default="B",
        help_text="Sexo do paciente compatível com o procedimento (B = ambos, sem restrição). Fonte: ANS.",
    )
    cid10_whitelist = models.JSONField(
        "CIDs compatíveis (whitelist)",
        default=list,
        blank=True,
        help_text="Lista de códigos CID-10 compatíveis com o procedimento. Lista vazia = sem restrição de CID. Fonte: ANS.",
    )

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
    """RBAC role with JSON permission list. Lives in the PUBLIC schema (apps.core is
    SHARED_APPS) — a global table shared across tenants, not per-tenant."""

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
    Lives in the PUBLIC schema (apps.core is SHARED_APPS) — a single GLOBAL user
    registry shared across all tenants (``email`` is globally unique), NOT a
    per-clinic table. A user is granted access to a clinic via
    ``UserTenantMembership``; ``TenantJWTAuthentication`` rejects requests for
    tenants the user is not a member of (when ``ENFORCE_TENANT_MEMBERSHIP`` is on).
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
    must_change_password = models.BooleanField(
        "Senha temporária — exige alteração no primeiro login", default=False
    )
    # Phase 3 multi-country — populated when the user picks a UI language
    # via /api/v1/users/me/language/. Empty string means "use platform
    # default (pt-BR) / Accept-Language". Values come from settings.LANGUAGES.
    preferred_language = models.CharField(
        "Idioma preferido",
        max_length=10,
        blank=True,
        default="",
        help_text="Código do idioma (pt-br, pt-pt, es, en). Vazio = padrão da plataforma.",
    )
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

    def effective_role(self):
        """Role governing this user IN THE CURRENT TENANT (Model B M2).

        When ``ENFORCE_TENANT_MEMBERSHIP`` is on, resolves the active
        ``UserTenantMembership.role`` for ``connection.tenant`` (per-tenant roles
        for multi-clinic staff), falling back to the global ``self.role`` when
        there is no tenant/membership or the membership records no role. When the
        flag is off it is a no-op returning ``self.role`` — so role resolution only
        becomes per-tenant at the same deliberate go-live flip as the rest of
        Model B (no staleness/divergence before then). Memoized per request, keyed
        by the current schema (a fresh ``User`` is loaded per request, and a schema
        switch invalidates the key).
        """
        from django.conf import settings
        from django.db import connection

        if not getattr(settings, "ENFORCE_TENANT_MEMBERSHIP", False):
            return self.role

        schema = getattr(connection, "schema_name", None)
        cache = self.__dict__.setdefault("_effective_role_cache", {})
        if schema in cache:
            return cache[schema]

        role = self.role
        tenant = getattr(connection, "tenant", None)
        if tenant is not None:
            membership = (
                UserTenantMembership.objects.filter(user=self, tenant=tenant, is_active=True)
                .select_related("role")
                .first()
            )
            if membership is not None and membership.role_id is not None:
                role = membership.role
        cache[schema] = role
        return role

    def has_role_permission(self, perm: str) -> bool:
        """Check if the user's effective (per-tenant) role grants a permission."""
        if self.is_superuser:
            return True
        role = self.effective_role()
        return bool(role and role.has_permission(perm))


class UserTenantMembership(models.Model):
    """Binds a global :class:`User` to a tenant (Model B tenant isolation).

    ``User``/``Role`` live in the PUBLIC schema (apps.core is SHARED_APPS) — one
    global registry shared across every tenant, with no per-tenant binding of its
    own. This row records that ``user`` may act within ``tenant``;
    ``TenantJWTAuthentication`` rejects (401) any authenticated request whose user
    holds no active membership for the current tenant, closing the cross-tenant
    access hole (a clinic-A credential must not work on clinic-B's domain).

    Lives in the public schema and carries an explicit ``tenant`` FK — the very
    discriminator AuditLog lacks (mirrors FeatureFlag's correct pattern).

    Phase 1 (M1): ``role`` is recorded for the future per-tenant-role migration
    (M2) but permission resolution still uses ``User.role``. Invariant:
    deactivating a membership (``is_active=False``) revokes access to THAT tenant
    only; ``User.is_active=False`` revokes everywhere.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="tenant_memberships", verbose_name="Usuário"
    )
    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name="user_memberships", verbose_name="Tenant"
    )
    role = models.ForeignKey(
        Role,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="memberships",
        verbose_name="Role (reservado p/ M2)",
    )
    is_active = models.BooleanField("Ativo", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Vínculo usuário-tenant"
        verbose_name_plural = "Vínculos usuário-tenant"
        unique_together = ("user", "tenant")
        indexes = [models.Index(fields=["user", "tenant", "is_active"])]

    def __str__(self):
        return f"{self.user.email} @ {self.tenant.schema_name}"


class AuditLog(models.Model):
    """
    Append-only audit trail for all data changes.
    Required by CFM Res. 1.821/2007 (prontuário eletrônico).

    Physically lives in the PUBLIC schema (apps.core is SHARED_APPS), shared
    across all tenants. ``schema_name`` is the tenant discriminator: it is stamped
    automatically on write from ``connection.schema_name`` (covers every write
    path — all wedges and the app trail — without touching call sites). Any
    audit-trail READ endpoint MUST filter by it, or it will leak every tenant's
    rows; use :meth:`for_current_tenant` to do so safely. A denormalized string
    (not an FK) so the immutable trail survives tenant deletion. Rows written
    before this column existed carry an empty ``schema_name`` (unattributable —
    cannot be inferred). See .gstack/security-reports (finding SYS-1).
    Never UPDATE or DELETE rows (append-only).
    """

    id = models.BigAutoField(primary_key=True)
    schema_name = models.CharField(
        "Schema do tenant",
        max_length=63,  # Postgres identifier limit
        blank=True,
        default="",
        db_index=True,
        help_text="Tenant que originou o evento; carimbado de connection no save. "
        "Vazio = linha anterior à coluna (não atribuível).",
    )
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
            models.Index(fields=["schema_name", "created_at"], name="core_auditlog_schema_idx"),
        ]

    def __str__(self):
        return f"{self.action} {self.resource_type}/{self.resource_id} by {self.user_id}"

    @classmethod
    def for_current_tenant(cls):
        """AuditLog rows for the CURRENT tenant only (SYS-1).

        The table is shared across all tenants, so a bare ``AuditLog.objects``
        query returns every tenant's rows. Any read path that surfaces audit
        entries to a tenant user MUST go through this to avoid cross-tenant
        disclosure. The public schema sees nothing tenant-scoped here.
        """
        from django.db import connection

        return cls.objects.filter(schema_name=getattr(connection, "schema_name", "") or "")

    def save(self, *args, **kwargs):
        # Enforce append-only: block updates
        if self.pk:
            raise ValueError("AuditLog entries are immutable.")
        # Stamp the originating tenant (SYS-1) from the active connection unless an
        # explicit value was set. One chokepoint covers all ~38 write sites.
        if not self.schema_name:
            from django.db import connection

            self.schema_name = getattr(connection, "schema_name", "") or ""
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


class UserInvitation(models.Model):
    """
    Single-use invitation token for the invite-email onboarding flow (S-076-NEW).
    token_hash stores SHA-256 of the JWT signature to allow validation without
    storing the raw token (defense in depth — leaked DB doesn't expose valid tokens).

    Lives in the PUBLIC schema (apps.core is SHARED_APPS) — global, not per-tenant.
    ``tenant`` records which clinic the invite is for (captured at creation from the
    inviting admin's tenant); accepting it grants a ``UserTenantMembership`` for that
    tenant and binds the issued token to it, so an invite for clinic A cannot be
    consumed to gain access to clinic B (Model B — see apps.core.tenant_auth).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey("core.User", on_delete=models.CASCADE, related_name="invitations")
    tenant = models.ForeignKey(
        "core.Tenant",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="invitations",
        verbose_name="Tenant",
        help_text="Clínica do convite; null = convite legado anterior ao Model B.",
    )
    created_by = models.ForeignKey(
        "core.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="invitations_sent",
        verbose_name="Criado por",
    )
    token_hash = models.CharField("Hash do token", max_length=64, unique=True, db_index=True)
    expires_at = models.DateTimeField("Expira em")
    consumed_at = models.DateTimeField("Consumido em", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Convite de usuário"
        verbose_name_plural = "Convites de usuário"
        ordering = ["-created_at"]

    @property
    def is_expired(self) -> bool:
        from django.utils import timezone

        return timezone.now() > self.expires_at

    @property
    def is_consumed(self) -> bool:
        return self.consumed_at is not None

    def __str__(self) -> str:
        status = "consumed" if self.is_consumed else ("expired" if self.is_expired else "pending")
        return f"Invitation for {self.user.email} ({status})"


# ─── Wedge business-value dashboard (issue #123) ─────────────────────────────


class WedgeValueSnapshot(models.Model):
    """Daily per-tenant snapshot of AI-wedge business-value (ROI) metrics.

    Lives in the PUBLIC schema (apps.core is SHARED) so the platform operator
    (Romulo, superuser) can read ROI per wedge per tenant from a single query
    WITHOUT fan-out schema switching on every page load. The per-tenant numbers
    are computed inside each tenant schema by ``apps.core.services.wedge_value``
    and written here once a day by the ``snapshot_wedge_value`` Celery Beat task.

    ``metrics`` is an opaque JSON payload (one key per wedge plus aggregates).
    Keeping it JSON — rather than a wide column set — lets new wedge KPIs be
    added without a migration; the shape is documented in the service module and
    is additive-only (never remove a key consumers may read).

    One row per (schema_name, snapshot_date); the daily task ``update_or_create``s
    in place so a re-run on the same day refreshes rather than duplicates.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    schema_name = models.CharField("Schema do tenant", max_length=63, db_index=True)
    tenant_name = models.CharField("Nome do tenant", max_length=255, blank=True)
    snapshot_date = models.DateField("Data do snapshot", db_index=True)
    window_days = models.PositiveIntegerField(
        "Janela (dias)",
        default=30,
        help_text="Janela móvel usada no cálculo das métricas (ex.: últimos 30 dias).",
    )
    metrics = models.JSONField(
        "Métricas por wedge",
        default=dict,
        help_text="Payload por wedge (glosa_safety, dose_safety, …) + agregados.",
    )
    generated_at = models.DateTimeField("Gerado em", auto_now=True)

    class Meta:
        verbose_name = "Snapshot de Valor de Wedge"
        verbose_name_plural = "Snapshots de Valor de Wedge"
        ordering = ["-snapshot_date", "tenant_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["schema_name", "snapshot_date"],
                name="uniq_wedge_value_snapshot_per_day",
            ),
        ]
        indexes = [
            models.Index(fields=["snapshot_date", "schema_name"]),
        ]

    def __str__(self) -> str:
        return f"WedgeValueSnapshot({self.schema_name}, {self.snapshot_date})"
