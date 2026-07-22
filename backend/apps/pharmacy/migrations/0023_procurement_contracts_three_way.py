import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("pharmacy", "0022_pharmacist_validation")]
    operations = [
        migrations.CreateModel(
            name="SupplierContract",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("number", models.CharField(max_length=80)),
                ("starts_on", models.DateField()),
                ("ends_on", models.DateField(blank=True, null=True)),
                ("currency", models.CharField(default="BRL", max_length=3)),
                (
                    "spending_limit",
                    models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Rascunho"),
                            ("active", "Ativo"),
                            ("expired", "Expirado"),
                            ("cancelled", "Cancelado"),
                        ],
                        default="draft",
                        max_length=20,
                    ),
                ),
                ("terms", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        null=True, on_delete=django.db.models.deletion.PROTECT, to="core.user"
                    ),
                ),
                (
                    "supplier",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="contracts",
                        to="pharmacy.supplier",
                    ),
                ),
            ],
            options={
                "ordering": ["-starts_on"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("supplier", "number"), name="supplier_contract_number_uniq"
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="SupplierInvoice",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("number", models.CharField(max_length=80)),
                ("issued_on", models.DateField(blank=True, null=True)),
                ("total_amount", models.DecimalField(decimal_places=2, max_digits=14)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pendente"),
                            ("matched", "Conciliada"),
                            ("mismatch", "Divergente"),
                            ("approved", "Aprovada"),
                            ("rejected", "Rejeitada"),
                        ],
                        db_index=True,
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("lines", models.JSONField(blank=True, default=list)),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="supplier_invoices_created",
                        to="core.user",
                    ),
                ),
                (
                    "purchase_order",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="invoices",
                        to="pharmacy.purchaseorder",
                    ),
                ),
                (
                    "supplier",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="invoices",
                        to="pharmacy.supplier",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("supplier", "number"), name="supplier_invoice_number_uniq"
                    )
                ]
            },
        ),
        migrations.CreateModel(
            name="ThreeWayMatch",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("ordered_total", models.DecimalField(decimal_places=2, max_digits=14)),
                ("received_total", models.DecimalField(decimal_places=2, max_digits=14)),
                ("invoiced_total", models.DecimalField(decimal_places=2, max_digits=14)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("matched", "Conciliada"),
                            ("mismatch", "Divergente"),
                            ("approved", "Aprovada"),
                        ],
                        db_index=True,
                        max_length=20,
                    ),
                ),
                ("discrepancies", models.JSONField(blank=True, default=list)),
                ("reviewed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "invoice",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="match",
                        to="pharmacy.supplierinvoice",
                    ),
                ),
                (
                    "purchase_order",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="matches",
                        to="pharmacy.purchaseorder",
                    ),
                ),
                (
                    "reviewed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="three_way_matches_reviewed",
                        to="core.user",
                    ),
                ),
            ],
        ),
    ]
