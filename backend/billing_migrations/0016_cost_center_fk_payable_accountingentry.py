"""
S4-T2 — Convert Payable.cost_center and AccountingEntry.cost_center from a
free-text CharField to a real FK on organization.CostCenter, PRESERVING data.

A plain CharField→FK AlterField would try to cast varchar → uuid and fail. This
migration instead does the safe rename-dance:

  1. rename the old varchar column to ``cost_center_legacy``,
  2. add the new nullable FK column ``cost_center``,
  3. data-migrate: for each row whose legacy value matches an existing
     CostCenter.code, point the FK at it; unmatched/blank values become NULL
     (organization.CostCenter mandates a non-null legal_entity, so a free-text
     value with no matching center cannot be fabricated into a valid row),
  4. drop the legacy column.
"""

import django.db.models.deletion
from django.db import migrations, models


def _link_cost_centers(apps, schema_editor):
    CostCenter = apps.get_model("organization", "CostCenter")
    by_code = {cc.code: cc for cc in CostCenter.objects.all()}
    for model_name in ("Payable", "AccountingEntry"):
        Model = apps.get_model("billing", model_name)
        for row in Model.objects.exclude(cost_center_legacy="").exclude(
            cost_center_legacy__isnull=True
        ):
            cc = by_code.get(row.cost_center_legacy)
            if cc is not None:
                row.cost_center_id = cc.id
                row.save(update_fields=["cost_center"])


def _noop_reverse(apps, schema_editor):
    # Irreversible data preservation is best-effort: on reverse the legacy column
    # is recreated empty (the FK code is not copied back). Nothing to do here.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0015_accountsreceivable_cost_center_and_more"),
        ("organization", "0001_initial"),
    ]

    operations = [
        migrations.RenameField(
            model_name="payable",
            old_name="cost_center",
            new_name="cost_center_legacy",
        ),
        migrations.RenameField(
            model_name="accountingentry",
            old_name="cost_center",
            new_name="cost_center_legacy",
        ),
        migrations.AddField(
            model_name="payable",
            name="cost_center",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="payables",
                to="organization.costcenter",
            ),
        ),
        migrations.AddField(
            model_name="accountingentry",
            name="cost_center",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="accounting_entries",
                to="organization.costcenter",
            ),
        ),
        migrations.RunPython(_link_cost_centers, _noop_reverse),
        migrations.RemoveField(model_name="payable", name="cost_center_legacy"),
        migrations.RemoveField(model_name="accountingentry", name="cost_center_legacy"),
    ]
