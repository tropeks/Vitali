"""E1-T2 — evolve CID10Code into a rich, hierarchical, versioned catalog.

Adds hierarchy (parent/chapter/group/category), governed clinical metadata
(sex_allowed/age_min/age_max/is_notifiable), version, and a normalized_description
search column. Backfills normalized_description for existing rows so nothing is
lost and accent-insensitive search works immediately after deploy.
"""

import django.db.models.deletion
from django.db import migrations, models


def backfill_normalized_description(apps, schema_editor):
    from apps.core.terminology_base import normalize_text

    CID10Code = apps.get_model("core", "CID10Code")
    batch = []
    for row in CID10Code.objects.all().iterator(chunk_size=2000):
        row.normalized_description = normalize_text(row.description)
        batch.append(row)
        if len(batch) >= 2000:
            CID10Code.objects.bulk_update(batch, ["normalized_description"])
            batch = []
    if batch:
        CID10Code.objects.bulk_update(batch, ["normalized_description"])


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0023_terminologyimportlog"),
    ]

    operations = [
        migrations.AddField(
            model_name="cid10code",
            name="normalized_description",
            field=models.CharField(
                blank=True,
                db_index=True,
                default="",
                help_text="description sem acentos e em minúsculas — mantido em sincronia no save().",
                max_length=500,
                verbose_name="Descrição normalizada",
            ),
        ),
        migrations.AddField(
            model_name="cid10code",
            name="version",
            field=models.CharField(blank=True, default="", max_length=32, verbose_name="Versão"),
        ),
        migrations.AddField(
            model_name="cid10code",
            name="parent",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="children",
                to="core.cid10code",
                verbose_name="Código pai",
            ),
        ),
        migrations.AddField(
            model_name="cid10code",
            name="chapter",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Ex.: I Algumas doenças…",
                max_length=200,
                verbose_name="Capítulo",
            ),
        ),
        migrations.AddField(
            model_name="cid10code",
            name="group",
            field=models.CharField(blank=True, default="", max_length=200, verbose_name="Grupo"),
        ),
        migrations.AddField(
            model_name="cid10code",
            name="category",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Ex.: A00-A09",
                max_length=200,
                verbose_name="Categoria",
            ),
        ),
        migrations.AddField(
            model_name="cid10code",
            name="sex_allowed",
            field=models.CharField(
                choices=[
                    ("M", "Masculino"),
                    ("F", "Feminino"),
                    ("B", "Ambos/Qualquer"),
                ],
                default="B",
                help_text="Sexo compatível com o diagnóstico (B = ambos, sem restrição).",
                max_length=1,
                verbose_name="Sexo permitido",
            ),
        ),
        migrations.AddField(
            model_name="cid10code",
            name="age_min",
            field=models.IntegerField(
                blank=True,
                help_text="Idade mínima do paciente, em dias. Null = sem limite inferior.",
                null=True,
                verbose_name="Idade mínima (dias)",
            ),
        ),
        migrations.AddField(
            model_name="cid10code",
            name="age_max",
            field=models.IntegerField(
                blank=True,
                help_text="Idade máxima do paciente, em dias. Null = sem limite superior.",
                null=True,
                verbose_name="Idade máxima (dias)",
            ),
        ),
        migrations.AddField(
            model_name="cid10code",
            name="is_notifiable",
            field=models.BooleanField(
                default=False,
                help_text="Doença de notificação compulsória (SINAN).",
                verbose_name="Notificação compulsória",
            ),
        ),
        migrations.RunPython(
            backfill_normalized_description,
            migrations.RunPython.noop,
        ),
    ]
