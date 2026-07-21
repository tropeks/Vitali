"""Enforce at most one active EscalationConfig per tenant.

apps.emr is a TENANT_APP: migrate_schemas runs this migration once per
tenant schema, so the RunPython below operates on a single schema's rows —
no manual tenant loop needed (unlike SHARED_APPS data migrations such as
core.0004, which must iterate tenants explicitly).

Before PR #152's follow-up, EscalationConfig had no uniqueness guarantee on
is_active=True: multiple active rows could coexist, and both the
clinical-deterioration escalation router (apps.emr.services.escalation) and
the triage emergency notifier (apps.triage.services.notifications) silently
picked the newest by created_at — surprising for an operator editing what
they think is "the" active config while an older row still quietly matches.

Strategy: for any tenant schema with more than one is_active=True row, keep
the most recently created one active and deactivate the rest, THEN add the
partial UniqueConstraint so the DB enforces it going forward.
"""

from django.db import migrations, models


def deactivate_duplicate_active_configs(apps, schema_editor):
    EscalationConfig = apps.get_model("emr", "EscalationConfig")

    active_ids = list(
        EscalationConfig.objects.filter(is_active=True)
        .order_by("-created_at")
        .values_list("id", flat=True)
    )
    # Keep the newest (active_ids[0]); deactivate everything else.
    stale_ids = active_ids[1:]
    if stale_ids:
        EscalationConfig.objects.filter(id__in=stale_ids).update(is_active=False)


def noop(apps, schema_editor):
    # Not reversible: we don't know which rows were originally active.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("emr", "0025_icp_brasil_fields"),
    ]

    operations = [
        migrations.RunPython(deactivate_duplicate_active_configs, noop),
        migrations.AddConstraint(
            model_name="escalationconfig",
            constraint=models.UniqueConstraint(
                fields=["is_active"],
                condition=models.Q(is_active=True),
                name="uniq_active_escalation_config_per_tenant",
            ),
        ),
    ]
