"""
emr 0005 — Prescription + PrescriptionItem (minimal S-015)
Depends on pharmacy 0001 so PrescriptionItem can FK to pharmacy.Drug.
"""
import uuid
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('emr', '0004_add_patientinsurance'),
        ('pharmacy', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Prescription',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('encounter', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='prescriptions', to='emr.encounter',
                )),
                ('patient', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='prescriptions', to='emr.patient',
                )),
                ('prescriber', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='prescriptions', to='emr.professional',
                )),
                ('status', models.CharField(
                    choices=[
                        ('draft', 'Rascunho'),
                        ('signed', 'Assinada'),
                        ('partially_dispensed', 'Parcialmente dispensada'),
                        ('dispensed', 'Dispensada'),
                        ('cancelled', 'Cancelada'),
                    ],
                    db_index=True, default='draft', max_length=25,
                )),
                ('signed_at', models.DateTimeField(blank=True, null=True)),
                ('signed_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='signed_prescriptions', to=settings.AUTH_USER_MODEL,
                )),
                ('notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.AddIndex(
            model_name='prescription',
            index=models.Index(fields=['patient', 'status'], name='emr_prescription_patient_status'),
        ),
        migrations.AddIndex(
            model_name='prescription',
            index=models.Index(fields=['encounter', 'status'], name='emr_prescription_encounter_status'),
        ),
        migrations.CreateModel(
            name='PrescriptionItem',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('prescription', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='items', to='emr.prescription',
                )),
                ('drug', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='prescription_items', to='pharmacy.drug',
                )),
                ('generic_name', models.CharField(blank=True, max_length=300)),
                ('quantity', models.DecimalField(decimal_places=3, max_digits=10)),
                ('unit_of_measure', models.CharField(default='un', max_length=20)),
                ('dosage_instructions', models.TextField(blank=True)),
                ('notes', models.TextField(blank=True)),
            ],
            options={'ordering': ['id']},
        ),
    ]
