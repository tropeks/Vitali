from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _

from .models import (
    AuditLog,
    Domain,
    FeatureFlag,
    Plan,
    PlanModule,
    Role,
    Subscription,
    Tenant,
    TUSSCode,
    User,
)


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ("name", "schema_name", "cnpj", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("name", "schema_name", "cnpj")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(Domain)
class DomainAdmin(admin.ModelAdmin):
    list_display = ("domain", "tenant", "is_primary")
    list_filter = ("is_primary",)
    search_fields = ("domain",)


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ("name", "base_price", "is_active")
    list_filter = ("is_active",)


class PlanModuleInline(admin.TabularInline):
    model = PlanModule
    extra = 0


@admin.register(PlanModule)
class PlanModuleAdmin(admin.ModelAdmin):
    list_display = ("plan", "module_key", "price", "is_included")


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("tenant", "plan", "status", "monthly_price", "current_period_end")
    list_filter = ("status",)
    readonly_fields = ("id", "created_at")


@admin.register(FeatureFlag)
class FeatureFlagAdmin(admin.ModelAdmin):
    list_display = ("tenant", "module_key", "is_enabled")
    list_filter = ("is_enabled", "module_key")
    search_fields = ("tenant__name", "module_key")


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("name", "is_system", "created_at")
    list_filter = ("is_system",)
    readonly_fields = ("id",)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ("email",)
    list_display = ("email", "full_name", "role", "is_active", "is_staff")
    list_filter = ("is_active", "is_staff", "role")
    search_fields = ("email", "full_name")
    readonly_fields = ("id", "last_login", "created_at", "updated_at")

    fieldsets = (
        (None, {"fields": ("id", "email", "password")}),
        (_("Dados pessoais"), {"fields": ("full_name", "cpf")}),
        (_("Acesso"), {"fields": ("role", "is_active", "is_staff", "is_superuser")}),
        (_("Datas"), {"fields": ("last_login", "created_at", "updated_at")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "full_name", "password1", "password2"),
            },
        ),
    )


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("action", "resource_type", "resource_id", "user", "ip_address", "created_at")
    list_filter = ("action", "resource_type")
    search_fields = ("resource_id", "user__email")
    readonly_fields = tuple(
        f.name for f in AuditLog._meta.get_fields() if hasattr(f, "name")
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(TUSSCode)
class TUSSCodeAdmin(admin.ModelAdmin):
    list_display = ["code", "description_short", "group", "subgroup", "version", "active"]
    list_filter = ["active", "group", "version"]
    search_fields = ["code", "description", "group"]
    readonly_fields = ["search_vector"]
    ordering = ["code"]

    def description_short(self, obj):
        return obj.description[:80]
    description_short.short_description = "Descrição"
