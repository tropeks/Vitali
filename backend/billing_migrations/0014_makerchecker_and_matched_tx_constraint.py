import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Maker-checker fields for settlements/cash-flow + a DB-level guard against
    two bank transactions matched to the same receivable."""

    dependencies = [
        ("billing", "0013_alter_cashflowentry_options_and_more"),
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="professionalsettlement",
            name="created_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="settlements_created",
                to="core.user",
            ),
        ),
        migrations.AddField(
            model_name="professionalsettlement",
            name="approved_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="settlements_approved",
                to="core.user",
            ),
        ),
        migrations.AddField(
            model_name="professionalsettlement",
            name="approved_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="cashflowentry",
            name="created_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="cashflow_entries_created",
                to="core.user",
            ),
        ),
        migrations.AddConstraint(
            model_name="banktransaction",
            constraint=models.UniqueConstraint(
                fields=["receivable"],
                condition=models.Q(status="matched"),
                name="uniq_matched_tx_per_receivable",
            ),
        ),
    ]
