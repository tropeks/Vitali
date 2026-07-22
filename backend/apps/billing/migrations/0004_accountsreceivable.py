from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies = [("billing", "0003_alter_tissbatch_status_add_cancelled")]
    operations = [migrations.CreateModel(
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
    ), migrations.AddIndex(model_name="accountsreceivable", index=models.Index(fields=["status", "due_date"], name="billing_acc_status_9ad8c7_idx"))]
