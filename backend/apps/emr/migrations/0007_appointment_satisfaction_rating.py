from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("emr", "0006_prescriptionitem_quantity_validator"),
    ]

    operations = [
        migrations.AddField(
            model_name="appointment",
            name="satisfaction_rating",
            field=models.IntegerField(
                blank=True,
                null=True,
                help_text="1=Muito bom, 2=Ok, 3=Poderia ser melhor. Set by post-visit WhatsApp survey.",
            ),
        ),
    ]
