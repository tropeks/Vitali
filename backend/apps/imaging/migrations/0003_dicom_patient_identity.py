from django.db import migrations, models


def backfill_dicom_patient_identity(apps, schema_editor):
    DicomStudy = apps.get_model("imaging", "DicomStudy")
    for study in DicomStudy.objects.select_related("patient").filter(dicom_patient_id=""):
        study.dicom_patient_id = study.patient.medical_record_number
        study.save(update_fields=["dicom_patient_id"])


class Migration(migrations.Migration):
    dependencies = [("imaging", "0002_link_lab_items_and_reports")]

    operations = [
        migrations.AddField(
            model_name="dicomstudy",
            name="dicom_patient_id",
            field=models.CharField(blank=True, db_index=True, max_length=64),
        ),
        migrations.AddField(
            model_name="dicomstudy",
            name="dicom_patient_id_issuer",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="dicomstudy",
            name="dicom_identity_verified",
            field=models.BooleanField(db_index=True, default=False),
        ),
        migrations.RunPython(backfill_dicom_patient_identity, migrations.RunPython.noop),
    ]
