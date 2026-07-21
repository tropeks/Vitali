import django.db.models.deletion
import encrypted_model_fields.fields
from django.conf import settings
from django.db import migrations, models

import apps.core.fields


class Migration(migrations.Migration):
    dependencies = [
        ("emr", "0027_labtest_laborder_laborderitem_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="labtest",
            name="category",
            field=models.CharField(
                choices=[
                    ("hematology", "Hematologia"),
                    ("biochemistry", "Bioquímica"),
                    ("immunology", "Imunologia e sorologia"),
                    ("hormones", "Hormônios"),
                    ("microbiology", "Microbiologia"),
                    ("urinalysis", "Urinálise"),
                    ("parasitology", "Parasitologia"),
                    ("coagulation", "Coagulação"),
                    ("toxicology", "Toxicologia"),
                    ("molecular", "Genética e biologia molecular"),
                    ("pathology", "Anatomia patológica"),
                    ("rapid_test", "Teste rápido"),
                    ("other", "Outros"),
                ],
                db_index=True,
                default="other",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="labtest",
            name="result_type",
            field=models.CharField(
                choices=[
                    ("numeric", "Numérico"),
                    ("qualitative", "Qualitativo"),
                    ("text", "Texto"),
                    ("panel", "Painel"),
                    ("microbiology", "Microbiologia"),
                ],
                db_index=True,
                default="numeric",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="labtest", name="method", field=models.CharField(blank=True, max_length=120)
        ),
        migrations.AddField(
            model_name="labtest",
            name="loinc_code",
            field=models.CharField(blank=True, db_index=True, max_length=20),
        ),
        migrations.AddField(
            model_name="labtest",
            name="components",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="labtest",
            name="reference_ranges",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="laborder",
            name="accession_number",
            field=models.CharField(blank=True, db_index=True, max_length=64),
        ),
        migrations.AddField(
            model_name="laborder",
            name="collected_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="collected_lab_orders",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="laborder",
            name="collection_notes",
            field=encrypted_model_fields.fields.EncryptedTextField(blank=True),
        ),
        migrations.AddField(
            model_name="laborder",
            name="specimen_details",
            field=apps.core.fields.EncryptedJSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="laborderitem",
            name="category",
            field=models.CharField(
                choices=[
                    ("hematology", "Hematologia"),
                    ("biochemistry", "Bioquímica"),
                    ("immunology", "Imunologia e sorologia"),
                    ("hormones", "Hormônios"),
                    ("microbiology", "Microbiologia"),
                    ("urinalysis", "Urinálise"),
                    ("parasitology", "Parasitologia"),
                    ("coagulation", "Coagulação"),
                    ("toxicology", "Toxicologia"),
                    ("molecular", "Genética e biologia molecular"),
                    ("pathology", "Anatomia patológica"),
                    ("rapid_test", "Teste rápido"),
                    ("other", "Outros"),
                ],
                default="other",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="laborderitem",
            name="result_type",
            field=models.CharField(
                choices=[
                    ("numeric", "Numérico"),
                    ("qualitative", "Qualitativo"),
                    ("text", "Texto"),
                    ("panel", "Painel"),
                    ("microbiology", "Microbiologia"),
                ],
                default="numeric",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="laborderitem",
            name="method",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="laborderitem",
            name="loinc_code",
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name="laborderitem",
            name="specimen_type",
            field=models.CharField(blank=True, max_length=80),
        ),
        migrations.AddField(
            model_name="laborderitem",
            name="components",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="laborderitem",
            name="reference_ranges",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="laborderitem",
            name="result_data",
            field=apps.core.fields.EncryptedJSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="laborderitem",
            name="microbiology",
            field=apps.core.fields.EncryptedJSONField(blank=True, default=dict),
        ),
    ]
