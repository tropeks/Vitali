import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("governance", "0001_initial"),
        ("pharmacy", "0020_evaluate_stockout_beat_schedule"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name="Warehouse",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("code", models.CharField(max_length=40, unique=True)),
                ("name", models.CharField(max_length=160)),
                ("active", models.BooleanField(db_index=True, default=True)),
                ("controlled_substances", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ("code",)},
        ),
        migrations.CreateModel(
            name="StorageLocation",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("code", models.CharField(max_length=60)),
                ("name", models.CharField(blank=True, max_length=160)),
                ("active", models.BooleanField(default=True)),
                ("quarantine", models.BooleanField(default=False)),
                (
                    "warehouse",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="locations",
                        to="pharmacy.warehouse",
                    ),
                ),
            ],
            options={"ordering": ("warehouse__code", "code")},
        ),
        migrations.AddConstraint(
            model_name="storagelocation",
            constraint=models.UniqueConstraint(
                fields=("warehouse", "code"), name="uniq_storage_location"
            ),
        ),
        migrations.AddField(
            model_name="stockitem",
            name="status",
            field=models.CharField(
                choices=[
                    ("available", "Disponível"),
                    ("quarantine", "Quarentena"),
                    ("recalled", "Recall"),
                ],
                db_index=True,
                default="available",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="stockitem",
            name="warehouse",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="stock_items",
                to="pharmacy.warehouse",
            ),
        ),
        migrations.AddField(
            model_name="stockitem",
            name="storage_location",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="stock_items",
                to="pharmacy.storagelocation",
            ),
        ),
        migrations.RemoveConstraint(
            model_name="stockitem", name="stockitem_drug_lot_expiry_unique"
        ),
        migrations.RemoveConstraint(
            model_name="stockitem", name="stockitem_material_lot_expiry_unique"
        ),
        migrations.AddConstraint(
            model_name="stockitem",
            constraint=models.UniqueConstraint(
                fields=("drug", "lot_number", "expiry_date", "warehouse"),
                name="stockitem_drug_lot_expiry_unique",
                nulls_distinct=False,
            ),
        ),
        migrations.AddConstraint(
            model_name="stockitem",
            constraint=models.UniqueConstraint(
                fields=("material", "lot_number", "expiry_date", "warehouse"),
                name="stockitem_material_lot_expiry_unique",
                nulls_distinct=False,
            ),
        ),
        migrations.CreateModel(
            name="InventoryCount",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Rascunho"),
                            ("submitted", "Aguardando aprovação"),
                            ("approved", "Aprovado e lançado"),
                            ("rejected", "Rejeitado"),
                        ],
                        db_index=True,
                        default="draft",
                        max_length=20,
                    ),
                ),
                ("blind", models.BooleanField(default=True, editable=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("applied_at", models.DateTimeField(blank=True, null=True)),
                (
                    "approval",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        to="governance.approvalrequest",
                    ),
                ),
                (
                    "requested_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="inventory_counts",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "warehouse",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="inventory_counts",
                        to="pharmacy.warehouse",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="InventoryCountLine",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("counted_quantity", models.DecimalField(decimal_places=3, max_digits=12)),
                (
                    "system_quantity_snapshot",
                    models.DecimalField(decimal_places=3, editable=False, max_digits=12, null=True),
                ),
                (
                    "inventory",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="lines",
                        to="pharmacy.inventorycount",
                    ),
                ),
                (
                    "stock_item",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, to="pharmacy.stockitem"
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="inventorycountline",
            constraint=models.UniqueConstraint(
                fields=("inventory", "stock_item"), name="uniq_inventory_item"
            ),
        ),
        migrations.CreateModel(
            name="StockTransfer",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Rascunho"),
                            ("in_transit", "Em trânsito"),
                            ("accepted", "Aceita"),
                            ("cancelled", "Cancelada"),
                        ],
                        db_index=True,
                        default="draft",
                        max_length=20,
                    ),
                ),
                ("shipped_at", models.DateTimeField(blank=True, null=True)),
                ("accepted_at", models.DateTimeField(blank=True, null=True)),
                (
                    "accepted_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="stock_transfers_accepted",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "destination",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="incoming_transfers",
                        to="pharmacy.warehouse",
                    ),
                ),
                (
                    "origin",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="outgoing_transfers",
                        to="pharmacy.warehouse",
                    ),
                ),
                (
                    "requested_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="stock_transfers_requested",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="stocktransfer",
            constraint=models.CheckConstraint(
                condition=~models.Q(origin=models.F("destination")),
                name="transfer_distinct_warehouses",
            ),
        ),
        migrations.CreateModel(
            name="StockTransferLine",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("quantity", models.DecimalField(decimal_places=3, max_digits=12)),
                (
                    "destination_item",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="received_transfer_lines",
                        to="pharmacy.stockitem",
                    ),
                ),
                (
                    "source_item",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="transfer_lines",
                        to="pharmacy.stockitem",
                    ),
                ),
                (
                    "transfer",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="lines",
                        to="pharmacy.stocktransfer",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="LotRecall",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("lot_number", models.CharField(db_index=True, max_length=50)),
                ("reason", models.TextField()),
                (
                    "status",
                    models.CharField(
                        choices=[("open", "Aberto"), ("closed", "Encerrado")],
                        default="open",
                        max_length=20,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL
                    ),
                ),
                (
                    "drug",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        to="pharmacy.drug",
                    ),
                ),
                (
                    "material",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        to="pharmacy.material",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="lotrecall",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("drug__isnull", False), ("material__isnull", True)),
                    models.Q(("drug__isnull", True), ("material__isnull", False)),
                    _connector="OR",
                ),
                name="recall_drug_xor_material",
            ),
        ),
    ]
