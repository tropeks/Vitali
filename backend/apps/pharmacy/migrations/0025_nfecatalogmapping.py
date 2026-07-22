from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid

class Migration(migrations.Migration):
    dependencies = [("pharmacy", "0024_nfereceipt_stockreceipt_nfereceiptitem_and_more")]
    operations = [migrations.CreateModel(name="NFeCatalogMapping", fields=[
        ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
        ("match_type", models.CharField(choices=[("barcode", "Código de barras"), ("supplier_code", "Código fornecedor"), ("ncm", "NCM"), ("manual", "Manual")], max_length=20)),
        ("confidence", models.DecimalField(decimal_places=2, default=0, max_digits=5)),
        ("status", models.CharField(choices=[("suggested", "Sugerido"), ("confirmed", "Confirmado"), ("rejected", "Rejeitado")], db_index=True, default="suggested", max_length=12)),
        ("reviewed_at", models.DateTimeField(blank=True, null=True)), ("created_at", models.DateTimeField(auto_now_add=True)),
        ("drug", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to="pharmacy.drug")),
        ("item", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="catalog_mapping", to="pharmacy.nfereceiptitem")),
        ("material", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to="pharmacy.material")),
        ("reviewed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
    ])]
