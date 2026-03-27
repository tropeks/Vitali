import django.db.models.deletion
import django.utils.timezone
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('emr', '0002_appointment_scheduleconfig'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Encounter',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('status', models.CharField(
                    choices=[('open', 'Em Aberto'), ('signed', 'Assinada'), ('cancelled', 'Cancelada')],
                    default='open', max_length=20)),
                ('encounter_date', models.DateTimeField(default=django.utils.timezone.now)),
                ('chief_complaint', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('appointment', models.OneToOneField(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='encounter', to='emr.appointment')),
                ('patient', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='encounters', to='emr.patient')),
                ('professional', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='encounters', to='emr.professional')),
            ],
            options={'ordering': ['-encounter_date']},
        ),
        migrations.AddIndex(
            model_name='encounter',
            index=models.Index(fields=['patient', 'encounter_date'], name='emr_enc_pat_date_idx'),
        ),
        migrations.AddIndex(
            model_name='encounter',
            index=models.Index(fields=['professional', 'encounter_date'], name='emr_enc_pro_date_idx'),
        ),
        migrations.AddIndex(
            model_name='encounter',
            index=models.Index(fields=['status', 'encounter_date'], name='emr_enc_sta_date_idx'),
        ),
        migrations.CreateModel(
            name='SOAPNote',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('subjective', models.TextField(blank=True, help_text='Queixa do paciente, história atual')),
                ('objective', models.TextField(blank=True, help_text='Exame físico, sinais vitais, achados')),
                ('assessment', models.TextField(blank=True, help_text='Diagnóstico, CID-10, impressão clínica')),
                ('plan', models.TextField(blank=True, help_text='Conduta, prescrição, retorno')),
                ('cid10_codes', models.JSONField(default=list, help_text='Lista de códigos CID-10')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('encounter', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='soap_note', to='emr.encounter')),
            ],
        ),
        migrations.CreateModel(
            name='VitalSigns',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('weight_kg', models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True)),
                ('height_cm', models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True)),
                ('blood_pressure_systolic', models.PositiveSmallIntegerField(blank=True, null=True)),
                ('blood_pressure_diastolic', models.PositiveSmallIntegerField(blank=True, null=True)),
                ('heart_rate', models.PositiveSmallIntegerField(blank=True, null=True)),
                ('temperature_celsius', models.DecimalField(blank=True, decimal_places=1, max_digits=4, null=True)),
                ('oxygen_saturation', models.PositiveSmallIntegerField(blank=True, null=True)),
                ('recorded_at', models.DateTimeField(auto_now_add=True)),
                ('encounter', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='vital_signs', to='emr.encounter')),
            ],
        ),
        migrations.CreateModel(
            name='ClinicalDocument',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('doc_type', models.CharField(
                    choices=[
                        ('certificate', 'Atestado Médico'), ('prescription', 'Receita'),
                        ('referral', 'Encaminhamento'), ('exam_request', 'Solicitação de Exame'),
                        ('report', 'Laudo'),
                    ],
                    max_length=20)),
                ('content', models.TextField()),
                ('signed_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('encounter', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='documents', to='emr.encounter')),
                ('signed_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='signed_documents', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-created_at']},
        ),
    ]
