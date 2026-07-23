import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("billing", "0011_bankstatementimport_banktransaction")]

    operations = [
        migrations.CreateModel(
            name="AccountingCategory",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("name", models.CharField(max_length=160)),
                ("code", models.CharField(max_length=40)),
                (
                    "kind",
                    models.CharField(
                        choices=[("revenue", "Receita"), ("expense", "Despesa")], max_length=10
                    ),
                ),
                ("active", models.BooleanField(default=True)),
            ],
            options={"ordering": ["code", "name"], "unique_together": {("code", "kind")}},
        ),
        migrations.CreateModel(
            name="AccountingEntry",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                (
                    "kind",
                    models.CharField(
                        choices=[("revenue", "Receita"), ("expense", "Despesa")], max_length=10
                    ),
                ),
                ("amount", models.DecimalField(decimal_places=2, max_digits=14)),
                ("competency", models.DateField(db_index=True)),
                ("unit", models.CharField(blank=True, max_length=120)),
                ("cost_center", models.CharField(blank=True, max_length=120)),
                ("description", models.CharField(blank=True, max_length=300)),
                ("reconciled", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "category",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="entries",
                        to="billing.accountingcategory",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        null=True, on_delete=django.db.models.deletion.SET_NULL, to="core.user"
                    ),
                ),
                (
                    "receivable",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="accounting_entries",
                        to="billing.accountsreceivable",
                    ),
                ),
            ],
            options={"ordering": ["-competency", "-created_at"]},
        ),
        migrations.AddIndex(
            model_name="accountingentry",
            index=models.Index(fields=["competency", "kind"], name="billing_entry_comp_kind_idx"),
        ),
        migrations.CreateModel(
            name="Payable",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                (
                    "external_id",
                    models.CharField(
                        help_text="ID idempotente da origem", max_length=180, unique=True
                    ),
                ),
                ("description", models.CharField(max_length=300)),
                ("category", models.CharField(blank=True, max_length=120)),
                ("cost_center", models.CharField(blank=True, max_length=120)),
                (
                    "amount",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=12,
                        validators=[django.core.validators.MinValueValidator(0)],
                    ),
                ),
                ("due_date", models.DateField()),
                ("paid_at", models.DateTimeField(blank=True, null=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("planned", "Prevista"),
                            ("approved", "Aprovada"),
                            ("paid", "Paga"),
                            ("cancelled", "Cancelada"),
                        ],
                        db_index=True,
                        default="planned",
                        max_length=12,
                    ),
                ),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="payables_created",
                        to="core.user",
                    ),
                ),
            ],
            options={"ordering": ["due_date", "-created_at"]},
        ),
        migrations.CreateModel(
            name="CashFlowEntry",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("external_id", models.CharField(max_length=180, unique=True)),
                ("description", models.CharField(max_length=300)),
                (
                    "kind",
                    models.CharField(
                        choices=[("inflow", "Entrada"), ("outflow", "Saída")], max_length=8
                    ),
                ),
                (
                    "amount",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=12,
                        validators=[django.core.validators.MinValueValidator(0)],
                    ),
                ),
                ("due_date", models.DateField()),
                ("realized_at", models.DateTimeField(blank=True, null=True)),
                ("category", models.CharField(blank=True, max_length=120)),
                ("cost_center", models.CharField(blank=True, max_length=120)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("forecast", "Previsto"),
                            ("realized", "Realizado"),
                            ("cancelled", "Cancelado"),
                        ],
                        db_index=True,
                        default="forecast",
                        max_length=10,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.AddIndex(
            model_name="payable",
            index=models.Index(fields=["status", "due_date"], name="billing_pay_status_due_idx"),
        ),
    ]
