"""
pharmacy 0003 — Add DB-level non-negative quantity constraint to StockItem.
Prevents adjustment movements from driving stock below zero at the database layer.
"""
from decimal import Decimal
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pharmacy', '0002_dispensation'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='stockitem',
            constraint=models.CheckConstraint(
                check=models.Q(quantity__gte=Decimal('0')),
                name='stock_item_quantity_non_negative',
            ),
        ),
    ]
