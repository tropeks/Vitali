from django.db import migrations, models


class Migration(migrations.Migration):
    """Add the 'cancelled' choice to TISSBatch.status.

    A cancelled batch never reaches the insurer, so its guides are excluded from
    double-submit conflict checks (a cancelled batch frees its guides to be
    re-batched). This is a choices-only change — no SQL alteration to the column.
    """

    dependencies = [
        ("billing", "0002_tissbatch_retorno_xml_file"),
    ]

    operations = [
        migrations.AlterField(
            model_name="tissbatch",
            name="status",
            field=models.CharField(
                choices=[
                    ("open", "Aberto"),
                    ("closed", "Fechado"),
                    ("submitted", "Enviado"),
                    ("processed", "Processado"),
                    ("cancelled", "Cancelado"),
                ],
                db_index=True,
                default="open",
                max_length=20,
                verbose_name="Status",
            ),
        ),
    ]
