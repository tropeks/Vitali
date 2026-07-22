import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("pharmacy", "0024_nfereceipt_stockreceipt_nfereceiptitem_and_more")]
    operations = [
        migrations.AddField(
            "nfereceipt",
            "source",
            models.CharField(
                choices=[
                    ("manual", "Upload manual"),
                    ("email", "E-mail"),
                    ("webhook", "Webhook/API"),
                ],
                db_index=True,
                default="manual",
                max_length=20,
            ),
        ),
        migrations.AddField(
            "nfereceipt", "external_id", models.CharField(blank=True, db_index=True, max_length=160)
        ),
        migrations.AddField(
            "nfereceipt",
            "payload_sha256",
            models.CharField(blank=True, db_index=True, max_length=64),
        ),
        migrations.AlterField(
            "nfereceipt",
            "uploaded_by",
            models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="nfe_uploads",
                to="core.user",
            ),
        ),
    ]
