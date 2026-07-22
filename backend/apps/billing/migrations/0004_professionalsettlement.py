from django.db import migrations, models
import django.db.models.deletion
import uuid

class Migration(migrations.Migration):
    dependencies = [("billing", "0003_alter_tissbatch_status_add_cancelled")]
    operations = [migrations.CreateModel(
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
    ), migrations.AddConstraint(model_name="professionalsettlement", constraint=models.UniqueConstraint(fields=("professional", "competency"), name="uniq_prof_settlement_competency"))]
