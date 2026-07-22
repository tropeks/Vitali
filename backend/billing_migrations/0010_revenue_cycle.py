import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("billing", "0009_alter_glosa_reason_code")]

    operations = [
        migrations.CreateModel(
            name="ProfessionalSettlement",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("competency", models.CharField(help_text="AAAA-MM", max_length=7)),
                ("gross_amount", models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ("deductions", models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ("net_amount", models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ("status", models.CharField(choices=[("draft", "Rascunho"), ("approved", "Aprovado"), ("paid", "Pago")], default="draft", max_length=10)),
                ("calculated_at", models.DateTimeField(auto_now=True)),
                ("paid_at", models.DateTimeField(blank=True, null=True)),
                ("professional", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="settlements", to="emr.professional")),
            ],
            options={"ordering": ["-competency"]},
        ),
        migrations.AddConstraint(
            model_name="professionalsettlement",
            constraint=models.UniqueConstraint(fields=("professional", "competency"), name="uniq_prof_settlement_competency"),
        ),
        migrations.CreateModel(
            name="AccountsReceivable",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("amount", models.DecimalField(decimal_places=2, max_digits=12)),
                ("due_date", models.DateField(blank=True, null=True)),
                ("received_at", models.DateTimeField(blank=True, null=True)),
                ("status", models.CharField(choices=[("expected", "Previsto"), ("billed", "Faturado"), ("received", "Recebido"), ("overdue", "Vencido"), ("contested", "Contestado")], db_index=True, default="expected", max_length=12)),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("guide", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="receivable", to="billing.tissguide")),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddIndex(model_name="accountsreceivable", index=models.Index(fields=["status", "due_date"], name="billing_acc_status_ea3ffa_idx")),
    ]
