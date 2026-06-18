# Generated manually

from django.db import migrations, models

class Migration(migrations.Migration):

    dependencies = [
        ('emr', '0024_escalationconfig'),
    ]

    operations = [
        migrations.AddField(
            model_name='encounter',
            name='is_icp_brasil',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='encounter',
            name='signature_hash',
            field=models.CharField(blank=True, max_length=128),
        ),
        migrations.AddField(
            model_name='clinicaldocument',
            name='is_icp_brasil',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='clinicaldocument',
            name='signature_hash',
            field=models.CharField(blank=True, max_length=128),
        ),
        migrations.AddField(
            model_name='prescription',
            name='is_icp_brasil',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='prescription',
            name='signature_hash',
            field=models.CharField(blank=True, max_length=128),
        ),
    ]
