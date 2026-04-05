"""
S-055: PIXCharge model — per-tenant PIX payment record.
"""

import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("billing", "0001_squashed_0002_tissbatch"),
        ("emr", "0002_appointment_scheduleconfig"),
    ]

    operations = [
        migrations.CreateModel(
            name="PIXCharge",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("asaas_charge_id", models.CharField(max_length=100, unique=True, verbose_name="Asaas Charge ID")),
                ("asaas_customer_id", models.CharField(blank=True, max_length=100, verbose_name="Asaas Customer ID")),
                ("amount", models.DecimalField(decimal_places=2, max_digits=10, verbose_name="Valor (R$)")),
                ("status", models.CharField(
                    choices=[
                        ("pending", "Pendente"),
                        ("paid", "Pago"),
                        ("expired", "Expirado"),
                        ("cancelled", "Cancelado"),
                        ("refunded", "Reembolsado"),
                    ],
                    db_index=True,
                    default="pending",
                    max_length=20,
                    verbose_name="Status",
                )),
                ("pix_copy_paste", models.TextField(blank=True, verbose_name="PIX Copia e Cola")),
                ("pix_qr_code_base64", models.TextField(blank=True, verbose_name="QR Code (base64)")),
                ("expires_at", models.DateTimeField(verbose_name="Expira em")),
                ("paid_at", models.DateTimeField(blank=True, null=True, verbose_name="Pago em")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("appointment", models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="pix_charge",
                    to="emr.appointment",
                    verbose_name="Consulta",
                )),
            ],
            options={
                "verbose_name": "Cobrança PIX",
                "verbose_name_plural": "Cobranças PIX",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="pixcharge",
            index=models.Index(fields=["status", "expires_at"], name="billing_pix_status_expires_idx"),
        ),
    ]
