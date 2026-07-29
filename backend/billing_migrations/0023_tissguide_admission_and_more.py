# Generated for Sprint B3 — Guia TISS de Internação.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0022_accommodationtuss_dailycharge"),
        ("emr", "0056_transfusionadministration_transfusionreaction_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="tissguide",
            name="admission",
            field=models.ForeignKey(
                blank=True,
                help_text="Internação que originou esta guia (ponte internação→faturamento).",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="tiss_guides",
                to="emr.admission",
            ),
        ),
        migrations.AlterField(
            model_name="tissguide",
            name="guide_type",
            field=models.CharField(
                choices=[
                    ("sadt", "SP/SADT"),
                    ("consulta", "Consulta"),
                    ("honorarios", "Honorários"),
                    ("internacao", "Resumo de Internação"),
                ],
                max_length=20,
                verbose_name="Tipo",
            ),
        ),
        migrations.AddConstraint(
            model_name="tissguide",
            constraint=models.UniqueConstraint(
                condition=models.Q(("admission__isnull", False)),
                fields=("admission",),
                name="uniq_tiss_guide_per_admission",
            ),
        ),
    ]
