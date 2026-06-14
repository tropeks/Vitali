# Generated manually for S29-03 — provenance fields on AllergenClass + DrugInteraction.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("pharmacy", "0017_doserule_validated"),
    ]

    operations = [
        migrations.AddField(
            model_name="allergenclass",
            name="source",
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name="allergenclass",
            name="version",
            field=models.CharField(blank=True, max_length=40),
        ),
        migrations.AddField(
            model_name="druginteraction",
            name="source",
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name="druginteraction",
            name="version",
            field=models.CharField(blank=True, max_length=40),
        ),
    ]
