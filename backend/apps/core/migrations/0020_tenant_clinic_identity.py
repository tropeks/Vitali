# Issue #116 — capture clinic identity (razão social, endereço, DPO) during the
# onboarding wizard. Additive, nullable/blank columns on the public-schema Tenant.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0019_auditlog_immutable"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenant",
            name="razao_social",
            field=models.CharField(
                blank=True, default="", max_length=255, verbose_name="Razão social"
            ),
        ),
        migrations.AddField(
            model_name="tenant",
            name="address",
            field=models.CharField(blank=True, default="", max_length=500, verbose_name="Endereço"),
        ),
        migrations.AddField(
            model_name="tenant",
            name="dpo_name",
            field=models.CharField(
                blank=True,
                default="",
                max_length=255,
                verbose_name="Encarregado de dados (DPO)",
            ),
        ),
        migrations.AddField(
            model_name="tenant",
            name="dpo_email",
            field=models.EmailField(
                blank=True, default="", max_length=254, verbose_name="E-mail do DPO"
            ),
        ),
        migrations.AddField(
            model_name="tenant",
            name="dpo_phone",
            field=models.CharField(
                blank=True, default="", max_length=30, verbose_name="Telefone do DPO"
            ),
        ),
    ]
