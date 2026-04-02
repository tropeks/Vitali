"""
Core signals — auto-create FeatureFlags, audit logging for model changes.
"""
import logging

from django.db.models.deletion import ProtectedError
from django.db.models.signals import post_save, post_delete, pre_delete
from django.dispatch import receiver

logger = logging.getLogger(__name__)

# ─── Models that trigger automatic audit logs ─────────────────────────────────
# Add model labels here as new clinical apps are introduced.
AUDITED_MODELS = {
    "core.User": "user",
    # Future apps:
    # "emr.Patient": "patient",
    # "emr.Encounter": "encounter",
    # "emr.ClinicalNote": "clinical_note",
    # "emr.Prescription": "prescription",
}


def _serialize_instance(instance):
    """Convert a model instance to a plain dict for audit storage."""
    from django.forms.models import model_to_dict
    try:
        data = model_to_dict(instance)
        # Convert non-serializable types to strings
        return {k: str(v) if not isinstance(v, (str, int, float, bool, type(None), list, dict)) else v
                for k, v in data.items()}
    except Exception:
        return {"id": str(getattr(instance, "pk", None))}


def _write_audit(action: str, resource_type: str, resource_id: str, old_data=None, new_data=None):
    """Write an AuditLog entry, silently ignoring errors to never disrupt the main flow."""
    from apps.core.middleware import get_current_request
    from apps.core.models import AuditLog

    request = get_current_request()
    user = None
    ip_address = None
    user_agent = ""

    if request:
        u = getattr(request, "user", None)
        if u and u.is_authenticated:
            user = u
        ip_address = _get_client_ip(request)
        user_agent = request.META.get("HTTP_USER_AGENT", "")[:500]

    try:
        AuditLog.objects.create(
            user=user,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id),
            old_data=old_data,
            new_data=new_data,
            ip_address=ip_address,
            user_agent=user_agent,
        )
    except Exception as exc:
        logger.warning("Failed to write audit log: %s", exc)


def _get_client_ip(request) -> str | None:
    """Extract real IP from X-Forwarded-For or REMOTE_ADDR."""
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


# ─── Generic audit signal handlers ───────────────────────────────────────────

def handle_post_save(sender, instance, created, **kwargs):
    label = f"{sender._meta.app_label}.{sender.__name__}"
    resource_type = AUDITED_MODELS.get(label, label.lower().replace(".", "_"))
    action = "create" if created else "update"
    new_data = _serialize_instance(instance)
    _write_audit(action, resource_type, instance.pk, new_data=new_data)


def handle_post_delete(sender, instance, **kwargs):
    label = f"{sender._meta.app_label}.{sender.__name__}"
    resource_type = AUDITED_MODELS.get(label, label.lower().replace(".", "_"))
    old_data = _serialize_instance(instance)
    _write_audit("delete", resource_type, instance.pk, old_data=old_data)


def register_audit_signals():
    """
    Call this to hook audit signals onto additional models (e.g., from emr app).
    Usage: register_audit_signals() in emr/apps.py ready()
    """
    from django.apps import apps as django_apps
    for model_label in AUDITED_MODELS:
        try:
            model = django_apps.get_model(model_label)
            post_save.connect(handle_post_save, sender=model, weak=False)
            post_delete.connect(handle_post_delete, sender=model, weak=False)
        except LookupError:
            pass  # App not yet loaded


# ─── TUSSCode cross-schema PROTECT ───────────────────────────────────────────
# PostgreSQL does not enforce FK integrity across schemas (public → tenant).
# This signal provides the application-layer PROTECT equivalent.

@receiver(pre_delete, sender="core.TUSSCode")
def protect_tuss_code_deletion(sender, instance, **kwargs):
    """Block deletion of a TUSSCode that is referenced by billing data in any tenant."""
    from django_tenants.utils import get_tenant_model, schema_context

    TenantModel = get_tenant_model()
    for tenant in TenantModel.objects.exclude(schema_name="public"):
        with schema_context(tenant.schema_name):
            from apps.billing.models import TISSGuideItem, PriceTableItem

            if TISSGuideItem.objects.filter(tuss_code=instance).exists():
                raise ProtectedError(
                    f"TUSSCode {instance.code} is referenced by TISSGuideItem in "
                    f"schema '{tenant.schema_name}' and cannot be deleted.",
                    {instance},
                )
            if PriceTableItem.objects.filter(tuss_code=instance).exists():
                raise ProtectedError(
                    f"TUSSCode {instance.code} is referenced by PriceTableItem in "
                    f"schema '{tenant.schema_name}' and cannot be deleted.",
                    {instance},
                )


# ─── Tenant → TenantAIConfig ─────────────────────────────────────────────────

@receiver(post_save, sender="core.Tenant")
def create_tenant_ai_config_on_new_tenant(sender, instance, created, **kwargs):
    """
    Auto-create TenantAIConfig with all-disabled defaults whenever a new Tenant is provisioned.
    This makes every tenant's AI config visible in Django Admin from day one.
    'All disabled' is an explicit visible state — not a silent absence.
    Prevents ops from misreading 'no config row' as low adoption.
    """
    if not created:
        return
    from apps.core.models import TenantAIConfig
    TenantAIConfig.objects.get_or_create(tenant=instance)


# ─── Subscription → FeatureFlags ─────────────────────────────────────────────

@receiver(post_save, sender="core.Subscription")
def create_feature_flags_on_subscription(sender, instance, created, **kwargs):
    """Automatically enable FeatureFlags for the modules in a new subscription."""
    if not created:
        return

    from apps.core.models import FeatureFlag

    for module_key in instance.active_modules:
        FeatureFlag.objects.get_or_create(
            tenant=instance.tenant,
            module_key=module_key,
            defaults={"is_enabled": True},
        )
