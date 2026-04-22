"""
emr 0006 — Add MinValueValidator(0.001) to PrescriptionItem.quantity.
Prevents zero or negative quantity items from being created via the API.
This is a validator-only change; no DB schema change is required.
"""

import decimal

import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("emr", "0005_add_prescription"),
    ]

    operations = [
        migrations.AlterField(
            model_name="prescriptionitem",
            name="quantity",
            field=models.DecimalField(
                decimal_places=3,
                max_digits=10,
                validators=[django.core.validators.MinValueValidator(decimal.Decimal("0.001"))],
            ),
        ),
    ]
