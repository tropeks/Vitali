"""M2-S1-T3 — migrate loose CBO/CNES text on emr.Professional to governed FKs.

* Professional.cbo_code (CharField)  → cbo FK (core.CBOCode) + legacy_cbo_text + flag.
* Professional.cnes_code (CharField) → cnes FK (core.CNESEstablishment) + legacy_cnes_text + flag.

Data is reconciled best-effort (matched → FK, unmatched → preserved raw + flag)
so nothing is ever lost. Cross-schema FKs mirror MedicalHistory.cid10 → CID10Code
(DO_NOTHING + pre_delete protection signal).
"""

import django.db.models.deletion
from django.db import migrations, models


def run_reconcile(apps, schema_editor):
    from apps.core.catalog_backfill import reconcile_catalog_fk

    Professional = apps.get_model("emr", "Professional")
    CBOCode = apps.get_model("core", "CBOCode")
    CNESEstablishment = apps.get_model("core", "CNESEstablishment")
    reconcile_catalog_fk(
        Professional,
        CBOCode,
        fk_field="cbo",
        legacy_field="legacy_cbo_text",
        unmatched_field="cbo_unmatched",
    )
    reconcile_catalog_fk(
        Professional,
        CNESEstablishment,
        fk_field="cnes",
        legacy_field="legacy_cnes_text",
        unmatched_field="cnes_unmatched",
    )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0028_cnesestablishment"),
        ("emr", "0039_medicationreconciliation_and_more"),
    ]

    operations = [
        # ── cbo_code → legacy_cbo_text + cbo FK ───────────────────────────────
        migrations.RenameField(
            model_name="professional",
            old_name="cbo_code",
            new_name="legacy_cbo_text",
        ),
        migrations.AlterField(
            model_name="professional",
            name="legacy_cbo_text",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Código CBO bruto não reconciliado com core.CBOCode.",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="professional",
            name="cbo",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name="+",
                to="core.cbocode",
                verbose_name="Ocupação CBO",
            ),
        ),
        migrations.AddField(
            model_name="professional",
            name="cbo_unmatched",
            field=models.BooleanField(
                default=False,
                help_text="True quando legacy_cbo_text não corresponde a nenhum CBOCode governado.",
            ),
        ),
        # ── cnes_code → legacy_cnes_text + cnes FK ────────────────────────────
        migrations.RenameField(
            model_name="professional",
            old_name="cnes_code",
            new_name="legacy_cnes_text",
        ),
        migrations.AlterField(
            model_name="professional",
            name="legacy_cnes_text",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Código CNES bruto não reconciliado com core.CNESEstablishment.",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="professional",
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
            model_name="professional",
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
