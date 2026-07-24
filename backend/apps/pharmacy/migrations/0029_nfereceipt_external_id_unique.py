from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("pharmacy", "0028_threewaymatch_override_reason")]

    operations = [
        migrations.AddConstraint(
            model_name="nfereceipt",
            constraint=models.UniqueConstraint(
                condition=models.Q(("external_id", ""), _negated=True),
                fields=("external_id",),
                name="nfe_external_id_unique_when_present",
            ),
        ),
    ]
