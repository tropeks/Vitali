"""
Onda 3 / 3.1: encrypt AIUsageLog.input_text at rest (LGPD).

Same two-step pattern as 0007_encrypt_scribe_raw_transcription:
1. Schema: change input_text from TextField to EncryptedTextField.
2. Data: re-save all existing rows so the library encrypts the plaintext value.
"""

import encrypted_model_fields.fields
from django.db import migrations


def encrypt_existing_input_text(apps, schema_editor):
    from apps.ai.models import AIUsageLog  # real model, not historical

    for log in AIUsageLog.objects.all():
        log.save(update_fields=["input_text"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        (
            "ai",
            "0009_rename_ai_scribe_encounter_status_idx_ai_aiscribe_encount_f856b2_idx_and_more",
        ),
    ]

    operations = [
        migrations.AlterField(
            model_name="aiusagelog",
            name="input_text",
            field=encrypted_model_fields.fields.EncryptedTextField(blank=True),
        ),
        migrations.RunPython(encrypt_existing_input_text, noop),
    ]
