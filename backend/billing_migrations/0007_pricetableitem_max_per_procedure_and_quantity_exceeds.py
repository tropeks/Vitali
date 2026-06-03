# Generated for glosa wedge G3c — per-procedure quantity ceiling.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0006_alter_glosasafetyalert_check_code"),
    ]

    operations = [
        migrations.AddField(
            model_name="pricetableitem",
            name="max_per_procedure",
            field=models.PositiveIntegerField(
                blank=True,
                help_text="Quantidade máxima por procedimento no contrato. Vazio = sem teto.",
                null=True,
                verbose_name="Teto de quantidade por procedimento",
            ),
        ),
        migrations.AlterField(
            model_name="glosasafetyalert",
            name="check_code",
            field=models.CharField(
                choices=[
                    ("duplicate", "Procedimento duplicado"),
                    ("stale_price", "Valor diverge da tabela vigente"),
                    ("not_in_table", "Procedimento não tabelado"),
                    ("incomplete", "Dados incompletos"),
                    ("engine_error", "Verificação indisponível"),
                    ("table_unresolved", "Cobertura não verificada"),
                    ("clinical_incompat", "Incompatibilidade clínica"),
                    ("quantity_exceeds", "Quantidade acima do teto"),
                ],
                max_length=20,
            ),
        ),
    ]
