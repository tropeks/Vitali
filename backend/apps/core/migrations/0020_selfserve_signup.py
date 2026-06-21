# Generated for S-132 — self-serve signup & subscription billing.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0019_auditlog_immutable"),
    ]

    operations = [
        migrations.AlterField(
            model_name="tenant",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "Pendente"),
                    ("trial", "Trial"),
                    ("active", "Ativo"),
                    ("suspended", "Suspenso"),
                    ("cancelled", "Cancelado"),
                ],
                default="trial",
                max_length=20,
                verbose_name="Status",
            ),
        ),
        migrations.AddField(
            model_name="subscription",
            name="asaas_customer_id",
            field=models.CharField(
                blank=True,
                db_index=True,
                default="",
                max_length=100,
                verbose_name="Asaas Customer ID",
            ),
        ),
        migrations.AddField(
            model_name="subscription",
            name="asaas_subscription_id",
            field=models.CharField(
                blank=True,
                db_index=True,
                default="",
                max_length=100,
                verbose_name="Asaas Subscription ID",
            ),
        ),
    ]
