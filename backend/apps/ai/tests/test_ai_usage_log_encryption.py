"""
Tests for AIUsageLog.input_text encryption at rest (Onda 3 / 3.1).

Same verification pattern as apps/patient_portal/tests/test_transactional_preconsult.py
(test_encrypted_at_rest): read the raw DB column via cursor.execute and require
the Fernet token prefix, never search for the plaintext substring itself (a
base64 Fernet token can coincidentally contain short plaintext substrings).
"""

from django.db import connection

from apps.ai.models import AIUsageLog
from apps.test_utils import TenantTestCase


class AIUsageLogEncryptionTest(TenantTestCase):
    def test_input_text_stored_encrypted(self):
        plaintext = "Consulta cardiologia — paciente refere dor torácica."
        log = AIUsageLog.objects.create(event_type="llm_call", input_text=plaintext)

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT input_text FROM ai_aiusagelog WHERE id = %s",
                [str(log.pk)],
            )
            raw = cursor.fetchone()[0]

        self.assertNotEqual(raw, plaintext)
        self.assertTrue(raw.startswith("gAAAAA"), f"não parece um token Fernet: {raw[:16]}")

    def test_input_text_round_trips_correctly(self):
        plaintext = "TUSS 10101012 — consulta em consultório."
        log = AIUsageLog.objects.create(event_type="llm_call", input_text=plaintext)

        refreshed = AIUsageLog.objects.get(pk=log.pk)
        self.assertEqual(refreshed.input_text, plaintext)

    def test_blank_input_text_does_not_crash(self):
        log = AIUsageLog.objects.create(event_type="degraded", input_text="")
        refreshed = AIUsageLog.objects.get(pk=log.pk)
        self.assertEqual(refreshed.input_text, "")
