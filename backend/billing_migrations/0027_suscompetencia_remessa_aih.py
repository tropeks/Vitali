# Generated for AI3 — Remessa SISAIH (AIH) da competência SUS.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0026_aihautorizacao_aihprocedimentosecundario_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="suscompetencia",
            name="remessa_aih",
            field=models.TextField(
                blank=True,
                default="",
                help_text="Conteúdo .txt da remessa AIH (SISAIH) gerado no momento da exportação (imutável).",
                verbose_name="Remessa AIH (SISAIH, texto posicional)",
            ),
        ),
    ]
