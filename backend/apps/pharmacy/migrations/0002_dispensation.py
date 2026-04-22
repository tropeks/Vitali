"""
pharmacy 0002 — Dispensation + DispensationLot
Depends on emr 0005 (Prescription, PrescriptionItem exist).
"""

import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("pharmacy", "0001_initial"),
        ("emr", "0005_add_prescription"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Dispensation",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                (
                    "prescription",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="dispensations",
                        to="emr.prescription",
                    ),
                ),
                (
                    "prescription_item",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="dispensations",
                        to="emr.prescriptionitem",
                    ),
                ),
                (
                    "patient",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="dispensations",
                        to="emr.patient",
                    ),
                ),
                (
                    "dispensed_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="dispensations",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                ("notes", models.TextField(blank=True)),
                ("dispensed_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["-dispensed_at"]},
        ),
        migrations.AddIndex(
            model_name="dispensation",
            index=models.Index(
                fields=["patient", "dispensed_at"], name="pharmacy_dispensation_patient"
            ),
        ),
        migrations.AddIndex(
            model_name="dispensation",
            index=models.Index(
                fields=["prescription", "dispensed_at"], name="pharmacy_dispensation_rx"
            ),
        ),
        migrations.CreateModel(
            name="DispensationLot",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                (
                    "dispensation",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="lots",
                        to="pharmacy.dispensation",
                    ),
                ),
                (
                    "stock_item",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="dispensation_lots",
                        to="pharmacy.stockitem",
                    ),
                ),
                ("quantity", models.DecimalField(decimal_places=3, max_digits=12)),
            ],
        ),
        migrations.AlterUniqueTogether(
            name="dispensationlot",
            unique_together={("dispensation", "stock_item")},
        ),
    ]
