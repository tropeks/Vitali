from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("pharmacy", "0027_nfecatalogmapping_nfe_mapping_catalog_target")]

    operations = [
        migrations.AddField(
            model_name="threewaymatch",
            name="override_reason",
            field=models.TextField(blank=True),
        ),
    ]
