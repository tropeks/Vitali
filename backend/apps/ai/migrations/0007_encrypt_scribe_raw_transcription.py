"""
S-071: Encrypt AIScribeSession.raw_transcription at rest (LGPD).

Two steps:
1. Schema: change raw_transcription from TextField to EncryptedTextField.
2. Data: re-save all existing rows so the library encrypts the plaintext value.
"""
import encrypted_model_fields.fields
from django.db import migrations


def encrypt_existing_transcriptions(apps, schema_editor):
    from apps.ai.models import AIScribeSession  # real model, not historical
    for session in AIScribeSession.objects.all():
        session.save(update_fields=['raw_transcription'])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("ai", "0006_ai_scribe_session"),
    ]

    operations = [
        migrations.AlterField(
            model_name="aiscribesession",
            name="raw_transcription",
            field=encrypted_model_fields.fields.EncryptedTextField(),
        ),
        migrations.RunPython(encrypt_existing_transcriptions, noop),
    ]
