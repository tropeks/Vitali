"""
pharmacy 0001 — Drug, Material, StockItem, StockMovement only.
Dispensation + DispensationLot live in 0002 (depends on emr.0005_add_prescription).
"""
import uuid
import decimal
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Drug',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('name', models.CharField(db_index=True, max_length=300)),
                ('generic_name', models.CharField(blank=True, db_index=True, max_length=300)),
                ('anvisa_code', models.CharField(blank=True, db_index=True, max_length=20)),
                ('barcode', models.CharField(blank=True, max_length=50, null=True, unique=True)),
                ('dosage_form', models.CharField(blank=True, max_length=100)),
                ('concentration', models.CharField(blank=True, max_length=100)),
                ('unit_of_measure', models.CharField(default='un', max_length=20)),
                ('controlled_class', models.CharField(
                    choices=[
                        ('none', 'Não controlado'),
                        ('A1', 'Lista A1 — Entorpecentes'),
                        ('A2', 'Lista A2 — Entorpecentes especiais'),
                        ('A3', 'Lista A3 — Entorpecentes sujeitos a controle especial'),
                        ('B1', 'Lista B1 — Psicotrópicos'),
                        ('B2', 'Lista B2 — Psicotrópicos retinóides/anorexígenos'),
                        ('C1', 'Lista C1 — Outras substâncias sujeitas a controle'),
                        ('C2', 'Lista C2 — Retinóides de uso sistêmico'),
                        ('C3', 'Lista C3 — Imunossupressores'),
                        ('C4', 'Lista C4 — Antirretrovirais'),
                        ('C5', 'Lista C5 — Anabolizantes'),
                    ],
                    db_index=True, default='none', max_length=5,
                )),
                ('is_active', models.BooleanField(db_index=True, default=True)),
                ('notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={'ordering': ['name']},
        ),
        migrations.AddIndex(
            model_name='drug',
            index=models.Index(fields=['name', 'is_active'], name='pharmacy_drug_name_active'),
        ),
        migrations.AddIndex(
            model_name='drug',
            index=models.Index(fields=['generic_name'], name='pharmacy_drug_generic_name'),
        ),
        migrations.AddIndex(
            model_name='drug',
            index=models.Index(fields=['controlled_class', 'is_active'], name='pharmacy_drug_controlled'),
        ),
        migrations.CreateModel(
            name='Material',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('name', models.CharField(db_index=True, max_length=300)),
                ('category', models.CharField(blank=True, max_length=100)),
                ('barcode', models.CharField(blank=True, max_length=50, null=True, unique=True)),
                ('unit_of_measure', models.CharField(default='un', max_length=20)),
                ('is_active', models.BooleanField(db_index=True, default=True)),
                ('notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={'ordering': ['name']},
        ),
        migrations.CreateModel(
            name='StockItem',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('drug', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                    related_name='stock_items', to='pharmacy.drug',
                )),
                ('material', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                    related_name='stock_items', to='pharmacy.material',
                )),
                ('lot_number', models.CharField(blank=True, db_index=True, max_length=50)),
                ('expiry_date', models.DateField(db_index=True, null=True, blank=True)),
                ('quantity', models.DecimalField(decimal_places=3, default=decimal.Decimal('0'), max_digits=12)),
                ('min_stock', models.DecimalField(decimal_places=3, default=decimal.Decimal('0'), max_digits=12)),
                ('location', models.CharField(blank=True, max_length=100)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={'ordering': ['expiry_date', 'lot_number']},
        ),
        migrations.AddConstraint(
            model_name='stockitem',
            constraint=models.CheckConstraint(
                check=(
                    models.Q(drug__isnull=False, material__isnull=True) |
                    models.Q(drug__isnull=True, material__isnull=False)
                ),
                name='stock_item_drug_xor_material',
            ),
        ),
        migrations.AddIndex(
            model_name='stockitem',
            index=models.Index(fields=['drug', 'expiry_date'], name='pharmacy_stockitem_drug_expiry'),
        ),
        migrations.AddIndex(
            model_name='stockitem',
            index=models.Index(fields=['material', 'expiry_date'], name='pharmacy_stockitem_mat_expiry'),
        ),
        migrations.AddIndex(
            model_name='stockitem',
            index=models.Index(fields=['expiry_date'], name='pharmacy_stockitem_expiry'),
        ),
        migrations.CreateModel(
            name='StockMovement',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('stock_item', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='movements', to='pharmacy.stockitem',
                )),
                ('movement_type', models.CharField(
                    choices=[
                        ('entry', 'Entrada'),
                        ('dispense', 'Dispensação'),
                        ('adjustment', 'Ajuste de inventário'),
                        ('return', 'Devolução'),
                        ('expired_write_off', 'Baixa por vencimento'),
                        ('transfer', 'Transferência'),
                    ],
                    db_index=True, max_length=30,
                )),
                ('quantity', models.DecimalField(decimal_places=3, max_digits=12)),
                ('reference', models.CharField(blank=True, max_length=200)),
                ('notes', models.TextField(blank=True)),
                ('performed_by', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                    to=settings.AUTH_USER_MODEL,
                )),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={'ordering': ['-created_at']},
        ),
    ]
