# Generated for stockout wedge S3.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("pharmacy", "0009_stockalert"),
    ]

    operations = [
        migrations.AddField(
            model_name="stockalert",
            name="suggested_reorder_qty",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text=(
                    "Qtd sugerida p/ repor (stockout_risk): "
                    "ceil(velocidade*(lead_time+cobertura)-saldo). NULL → sem sugestão."
                ),
                max_digits=12,
                null=True,
                verbose_name="Reposição sugerida",
            ),
        ),
    ]
