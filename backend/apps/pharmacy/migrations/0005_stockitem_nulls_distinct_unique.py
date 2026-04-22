"""
Replace unique_together with UniqueConstraint(nulls_distinct=False) on StockItem.

PostgreSQL's legacy UNIQUE constraint treats NULL as distinct — two rows with
(drug=X, lot='ABC', expiry_date=NULL) are considered different and both inserts
succeed, defeating the get_or_create deduplication in PO receiving.

UniqueConstraint(nulls_distinct=False) maps to PostgreSQL's
  CREATE UNIQUE INDEX ... NULLS NOT DISTINCT
which correctly treats NULL as equal, preventing duplicate lots.

Requires Django 5.0+ and PostgreSQL 15+. Vitali runs Django 5.2 + PostgreSQL 16.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("pharmacy", "0004_supplier_purchaseorder_stockitem_unique"),
    ]

    operations = [
        # Remove the old unique_together constraints
        migrations.AlterUniqueTogether(
            name="stockitem",
            unique_together=set(),
        ),
        # Add UniqueConstraint with nulls_distinct=False (handles NULL expiry_date safely)
        migrations.AddConstraint(
            model_name="stockitem",
            constraint=models.UniqueConstraint(
                fields=["drug", "lot_number", "expiry_date"],
                name="stockitem_drug_lot_expiry_unique",
                nulls_distinct=False,
            ),
        ),
        migrations.AddConstraint(
            model_name="stockitem",
            constraint=models.UniqueConstraint(
                fields=["material", "lot_number", "expiry_date"],
                name="stockitem_material_lot_expiry_unique",
                nulls_distinct=False,
            ),
        ),
    ]
