"""
S-055: AsaasChargeMap — public schema table for PIX webhook tenant resolution.
Maps asaas_charge_id → tenant_schema so the webhook handler can find the right
tenant schema without scanning all schemas.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0004_backfill_feature_flags"),
    ]

    operations = [
        migrations.CreateModel(
            name="AsaasChargeMap",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                (
                    "asaas_charge_id",
                    models.CharField(
                        db_index=True, max_length=100, unique=True, verbose_name="Asaas Charge ID"
                    ),
                ),
                (
                    "tenant_schema",
                    models.CharField(db_index=True, max_length=100, verbose_name="Tenant Schema"),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "Asaas Charge Map",
                "verbose_name_plural": "Asaas Charge Maps",
                "app_label": "core",
            },
        ),
    ]
