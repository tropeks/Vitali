"""
S-039: Backfill FeatureFlag rows for all existing tenants.

Without this migration, deploying S-039 immediately 403s every existing tenant
on billing, pharmacy, and AI endpoints — because ModuleRequiredPermission checks
FeatureFlag rows that don't yet exist.

Strategy:
  - Tenants with a Subscription → enable all modules in Subscription.active_modules
    plus 'analytics' if 'billing' is included (analytics is bundled with billing).
  - Tenants without a Subscription → enable only 'emr' (minimum viable access).

All writes are public-schema (FeatureFlag is in SHARED_APPS — no schema switching needed).
"""

from django.db import migrations


def backfill_feature_flags(apps, schema_editor):
    Tenant = apps.get_model("core", "Tenant")
    Subscription = apps.get_model("core", "Subscription")
    FeatureFlag = apps.get_model("core", "FeatureFlag")

    subscriptions_by_tenant = {
        sub.tenant_id: sub for sub in Subscription.objects.select_related("tenant").all()
    }

    for tenant in Tenant.objects.exclude(schema_name="public"):
        sub = subscriptions_by_tenant.get(tenant.pk)
        if sub:
            modules = list(sub.active_modules)
            # analytics is bundled with billing
            if "billing" in modules and "analytics" not in modules:
                modules.append("analytics")
        else:
            modules = ["emr"]

        for module_key in modules:
            FeatureFlag.objects.get_or_create(
                tenant=tenant,
                module_key=module_key,
                defaults={"is_enabled": True},
            )


def reverse_backfill(apps, schema_editor):
    # Safe to no-op: removing flags would lock tenants out; leave them in place.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0003_tussynclog_tenantaiconfig"),
    ]

    operations = [
        migrations.RunPython(backfill_feature_flags, reverse_code=reverse_backfill),
    ]
