"""M2-S1-T3 — governed CNES FK on organization.Facility.

Adds a nullable cross-schema FK to core.CNESEstablishment (DO_NOTHING + the
protect_cnes_establishment_deletion pre_delete signal) plus a legacy free-text
column + unmatched flag, mirroring emr.Professional.cnes. A best-effort reconcile
(matched → FK, unmatched → preserved raw + flag) keeps any pre-seeded CNES text.
"""

import django.db.models.deletion
from django.db import migrations, models


def run_reconcile(apps, schema_editor):
    from apps.core.catalog_backfill import reconcile_catalog_fk

    Facility = apps.get_model("organization", "Facility")
    CNESEstablishment = apps.get_model("core", "CNESEstablishment")
    reconcile_catalog_fk(
        Facility,
        CNESEstablishment,
        fk_field="cnes",
        legacy_field="legacy_cnes_text",
        unmatched_field="cnes_unmatched",
    )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0028_cnesestablishment"),
        ("organization", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="facility",
            name="cnes",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name="+",
                to="core.cnesestablishment",
                verbose_name="Estabelecimento CNES",
            ),
        ),
        migrations.AddField(
            model_name="facility",
            name="legacy_cnes_text",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Código CNES bruto não reconciliado com core.CNESEstablishment.",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="facility",
            name="cnes_unmatched",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "True quando legacy_cnes_text não corresponde a nenhum "
                    "CNESEstablishment governado."
                ),
            ),
        ),
        migrations.RunPython(run_reconcile, migrations.RunPython.noop),
    ]
