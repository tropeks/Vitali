# Generated manually for S29-02 — DoseRule validation gate.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("pharmacy", "0016_drug_min_refill_interval_days_controlledalert"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="doserule",
            name="validated",
            field=models.BooleanField(default=False, db_index=True),
        ),
        migrations.AddField(
            model_name="doserule",
            name="validated_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="doserule",
            name="validated_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
