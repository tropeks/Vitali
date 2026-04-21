"""
Tests for S-069 AI Clinical Scribe.

Covers:
  - services_scribe._parse_soap_json (unit, no DB)
  - generate_soap_task (Celery task, mocked LLM)
  - ScribeStartView (view, mocked task dispatch)
  - ScribeStatusView (view)
"""
import datetime
import json
from unittest.mock import MagicMock, patch

from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.test_utils import TenantTestCase


# ─── Unit tests for _parse_soap_json ─────────────────────────────────────────

class TestParseSoapJson(TenantTestCase):
    """Pure-unit tests — no LLM calls, no DB beyond tenant setup."""

    def _parse(self, raw):
        from apps.ai.services_scribe import _parse_soap_json
        return _parse_soap_json(raw)

    def test_valid_json_returned_as_dict(self):
        raw = json.dumps({
            "subjective": "Paciente relata dor de cabeça",
            "objective": "PA 120/80, afebril",
            "assessment": "Cefaleia tensional (G44.2)",
            "plan": "Dipirona 500mg VO se dor",
        })
        result = self._parse(raw)
        self.assertEqual(result["subjective"], "Paciente relata dor de cabeça")
        self.assertEqual(result["assessment"], "Cefaleia tensional (G44.2)")

    def test_strips_markdown_json_fence(self):
        raw = "```json\n{\"subjective\": \"dor\", \"objective\": \"\", \"assessment\": \"\", \"plan\": \"\"}\n```"
        result = self._parse(raw)
        self.assertEqual(result["subjective"], "dor")

    def test_strips_plain_code_fence(self):
        raw = "```\n{\"subjective\": \"s\", \"objective\": \"o\", \"assessment\": \"a\", \"plan\": \"p\"}\n```"
        result = self._parse(raw)
        self.assertEqual(result["plan"], "p")

    def test_invalid_json_returns_empty_fields(self):
        result = self._parse("not json at all")
        self.assertEqual(result, {"subjective": "", "objective": "", "assessment": "", "plan": ""})

    def test_non_dict_response_returns_empty(self):
        result = self._parse(json.dumps(["list", "not", "dict"]))
        self.assertEqual(result, {"subjective": "", "objective": "", "assessment": "", "plan": ""})

    def test_missing_keys_use_empty_string(self):
        result = self._parse(json.dumps({"subjective": "only this"}))
        self.assertEqual(result["objective"], "")
        self.assertEqual(result["plan"], "")

    def test_numeric_values_coerced_to_str(self):
        result = self._parse(json.dumps({"subjective": 42, "objective": "", "assessment": "", "plan": ""}))
        self.assertEqual(result["subjective"], "42")

    def test_empty_string_input_returns_empty(self):
        from apps.ai.services_scribe import generate_soap
        result = generate_soap("")
        self.assertEqual(result, {"subjective": "", "objective": "", "assessment": "", "plan": ""})


# ─── generate_soap_task tests ─────────────────────────────────────────────────

class TestGenerateSoapTask(TenantTestCase):

    def setUp(self):
        from django.contrib.auth import get_user_model
        from apps.emr.models import Patient, Professional, Encounter

        User = get_user_model()
        self.user = User.objects.create_user(
            email="scribe_task@clinic.test",
            password="TestPass123!",
        )
        patient = Patient.objects.create(
            full_name="Task Test Patient",
            cpf="111.222.333-44",
            birth_date=datetime.date(1980, 5, 15),
            gender="F",
        )
        professional = Professional.objects.create(
            user=self.user,
            council_type="CRM",
            council_number="111222",
            council_state="RJ",
        )
        self.encounter = Encounter.objects.create(
            patient=patient,
            professional=professional,
            encounter_date=timezone.now(),
        )

    def _make_session(self, transcription="Paciente com febre há 2 dias"):
        from apps.ai.models import AIScribeSession
        return AIScribeSession.objects.create(
            encounter=self.encounter,
            raw_transcription=transcription,
        )

    @patch("apps.ai.services_scribe.ClaudeGateway")
    def test_task_sets_completed_on_success(self, MockGateway):
        soap_response = json.dumps({
            "subjective": "Febre há 2 dias",
            "objective": "Tax 38.5°C",
            "assessment": "Síndrome gripal (J11.1)",
            "plan": "Dipirona 500mg 6/6h",
        })
        MockGateway.return_value.complete.return_value = (soap_response, 100, 200)

        session = self._make_session()
        from apps.ai.tasks import generate_soap_task
        generate_soap_task(session_id=str(session.id))

        session.refresh_from_db()
        self.assertEqual(session.status, "completed")
        self.assertIsNotNone(session.soap_json)
        self.assertEqual(session.soap_json["assessment"], "Síndrome gripal (J11.1)")
        self.assertIsNotNone(session.completed_at)

    @patch("apps.ai.services_scribe.ClaudeGateway")
    def test_task_sets_failed_on_empty_soap(self, MockGateway):
        # generate_soap is fail-open: empty strings trigger FAILED status
        MockGateway.return_value.complete.return_value = (
            json.dumps({"subjective": "", "objective": "", "assessment": "", "plan": ""}),
            50, 20,
        )

        session = self._make_session()
        from apps.ai.tasks import generate_soap_task
        generate_soap_task(session_id=str(session.id))

        session.refresh_from_db()
        self.assertEqual(session.status, "failed")
        self.assertIn("empty SOAP", session.error_message)

    def test_task_noop_on_missing_session(self):
        from apps.ai.tasks import generate_soap_task
        import uuid
        # Should not raise — just logs an error
        generate_soap_task(session_id=str(uuid.uuid4()))


# ─── View tests ───────────────────────────────────────────────────────────────

class TestScribeViews(TenantTestCase):

    def setUp(self):
        import datetime
        from django.contrib.auth import get_user_model
        from apps.emr.models import Patient, Professional, Encounter

        User = get_user_model()
        self.user = User.objects.create_user(
            email="scribe_view@clinic.test",
            password="TestPass123!",
        )
        patient = Patient.objects.create(
            full_name="View Test Patient",
            cpf="999.888.777-66",
            birth_date=datetime.date(1975, 3, 10),
            gender="M",
        )
        professional = Professional.objects.create(
            user=self.user,
            council_type="CRM",
            council_number="999888",
            council_state="MG",
        )
        self.encounter = Encounter.objects.create(
            patient=patient,
            professional=professional,
            encounter_date=timezone.now(),
            status="open",
        )
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        self.client.force_authenticate(user=self.user)

    def _dpa_signed(self, schema_name):
        return True

    @override_settings(FEATURE_AI_SCRIBE=False)
    def test_start_returns_404_when_feature_disabled(self):
        url = f"/api/v1/encounters/{self.encounter.id}/scribe/start/"
        res = self.client.post(url, {"transcription": "Test"}, format="json")
        self.assertEqual(res.status_code, 404)

    @override_settings(FEATURE_AI_SCRIBE=True)
    @patch("apps.emr.views_scribe._check_dpa_signed", return_value=False)
    def test_start_returns_403_when_dpa_not_signed(self, _mock):
        url = f"/api/v1/encounters/{self.encounter.id}/scribe/start/"
        res = self.client.post(url, {"transcription": "Test"}, format="json")
        self.assertEqual(res.status_code, 403)

    @override_settings(FEATURE_AI_SCRIBE=True)
    @patch("apps.emr.views_scribe._check_dpa_signed", return_value=True)
    @patch("apps.ai.tasks.generate_soap_task.delay")
    def test_start_creates_session_and_returns_202(self, mock_delay, _mock_dpa):
        url = f"/api/v1/encounters/{self.encounter.id}/scribe/start/"
        res = self.client.post(url, {"transcription": "Paciente relata dor abdominal"}, format="json")
        self.assertEqual(res.status_code, 202)
        self.assertIn("session_id", res.json())
        self.assertEqual(res.json()["status"], "processing")
        mock_delay.assert_called_once()

    @override_settings(FEATURE_AI_SCRIBE=True)
    @patch("apps.emr.views_scribe._check_dpa_signed", return_value=True)
    def test_start_rejects_empty_transcription(self, _mock_dpa):
        url = f"/api/v1/encounters/{self.encounter.id}/scribe/start/"
        res = self.client.post(url, {"transcription": "   "}, format="json")
        self.assertEqual(res.status_code, 400)

    @override_settings(FEATURE_AI_SCRIBE=True)
    @patch("apps.emr.views_scribe._check_dpa_signed", return_value=True)
    def test_start_rejects_transcription_over_10k_chars(self, _mock_dpa):
        url = f"/api/v1/encounters/{self.encounter.id}/scribe/start/"
        res = self.client.post(url, {"transcription": "x" * 10_001}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_status_returns_none_when_no_session(self):
        url = f"/api/v1/encounters/{self.encounter.id}/scribe/status/"
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["status"], "none")

    def test_status_returns_soap_on_completed_session(self):
        from apps.ai.models import AIScribeSession

        soap = {"subjective": "s", "objective": "o", "assessment": "a", "plan": "p"}
        session = AIScribeSession.objects.create(
            encounter=self.encounter,
            raw_transcription="test",
            status="completed",
            soap_json=soap,
            completed_at=timezone.now(),
        )

        url = f"/api/v1/encounters/{self.encounter.id}/scribe/status/"
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "completed")
        self.assertEqual(data["soap"]["assessment"], "a")

    def test_status_returns_error_on_failed_session(self):
        from apps.ai.models import AIScribeSession

        AIScribeSession.objects.create(
            encounter=self.encounter,
            raw_transcription="test",
            status="failed",
            error_message="LLM timeout",
            completed_at=timezone.now(),
        )

        url = f"/api/v1/encounters/{self.encounter.id}/scribe/status/"
        res = self.client.get(url)
        data = res.json()
        self.assertEqual(data["status"], "failed")
        self.assertEqual(data["error"], "LLM timeout")

    def test_unauthenticated_start_returns_401(self):
        self.client.logout()
        url = f"/api/v1/encounters/{self.encounter.id}/scribe/start/"
        res = self.client.post(url, {"transcription": "Test"}, format="json")
        self.assertEqual(res.status_code, 401)


# ─── S-071: Encryption and purge tests ───────────────────────────────────────

class TestScribeEncryption(TenantTestCase):

    def setUp(self):
        from django.contrib.auth import get_user_model
        from apps.emr.models import Patient, Professional, Encounter

        User = get_user_model()
        self.user = User.objects.create_user(
            email="scribe_enc@clinic.test",
            password="TestPass123!",
        )
        patient = Patient.objects.create(
            full_name="Enc Test Patient",
            cpf="222.333.444-55",
            birth_date=datetime.date(1985, 3, 10),
            gender="M",
        )
        professional = Professional.objects.create(
            user=self.user,
            council_type="CRM",
            council_number="222333",
            council_state="SP",
        )
        self.encounter = Encounter.objects.create(
            patient=patient,
            professional=professional,
            encounter_date=timezone.now(),
        )

    def test_raw_transcription_stored_encrypted(self):
        from django.db import connection
        from apps.ai.models import AIScribeSession

        plaintext = "Paciente relata dor de cabeça intensa."
        session = AIScribeSession.objects.create(
            encounter=self.encounter,
            raw_transcription=plaintext,
        )

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT raw_transcription FROM ai_aiscribesession WHERE id = %s",
                [str(session.pk)],
            )
            row = cursor.fetchone()
        raw_db_value = row[0]
        self.assertNotEqual(raw_db_value, plaintext)

    def test_raw_transcription_round_trips_correctly(self):
        from apps.ai.models import AIScribeSession

        plaintext = "Febre há 3 dias, tosse seca."
        session = AIScribeSession.objects.create(
            encounter=self.encounter,
            raw_transcription=plaintext,
        )
        refreshed = AIScribeSession.objects.get(pk=session.pk)
        self.assertEqual(refreshed.raw_transcription, plaintext)

    def test_encrypt_existing_transcriptions_migration_fn(self):
        import importlib

        from django.db import connection
        from apps.ai.models import AIScribeSession

        migration_module = importlib.import_module(
            "apps.ai.migrations.0007_encrypt_scribe_raw_transcription"
        )
        encrypt_existing_transcriptions = migration_module.encrypt_existing_transcriptions

        plaintext = "Texto de migração."
        session = AIScribeSession.objects.create(
            encounter=self.encounter,
            raw_transcription=plaintext,
        )

        encrypt_existing_transcriptions(None, None)

        refreshed = AIScribeSession.objects.get(pk=session.pk)
        self.assertEqual(refreshed.raw_transcription, plaintext)

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT raw_transcription FROM ai_aiscribesession WHERE id = %s",
                [str(session.pk)],
            )
            row = cursor.fetchone()
        self.assertNotEqual(row[0], plaintext)


class TestPurgeOldScribeSessions(TenantTestCase):

    def setUp(self):
        from django.contrib.auth import get_user_model
        from apps.emr.models import Patient, Professional, Encounter

        User = get_user_model()
        self.user = User.objects.create_user(
            email="scribe_purge@clinic.test",
            password="TestPass123!",
        )
        patient = Patient.objects.create(
            full_name="Purge Test Patient",
            cpf="333.444.555-66",
            birth_date=datetime.date(1990, 7, 20),
            gender="F",
        )
        professional = Professional.objects.create(
            user=self.user,
            council_type="CRM",
            council_number="333444",
            council_state="MG",
        )
        self.encounter = Encounter.objects.create(
            patient=patient,
            professional=professional,
            encounter_date=timezone.now(),
        )

    def _make_session(self, status, created_at, transcription="test"):
        from apps.ai.models import AIScribeSession
        session = AIScribeSession.objects.create(
            encounter=self.encounter,
            raw_transcription=transcription,
            status=status,
        )
        AIScribeSession.objects.filter(pk=session.pk).update(created_at=created_at)
        return session

    @override_settings(SCRIBE_SESSION_RETENTION_DAYS=90)
    def test_purge_deletes_old_non_completed_sessions(self):
        from apps.ai.tasks import purge_old_scribe_sessions

        old_dt = timezone.now() - datetime.timedelta(days=100)
        old_processing = self._make_session("processing", old_dt)
        old_failed = self._make_session("failed", old_dt)

        result = purge_old_scribe_sessions()
        self.assertGreaterEqual(result["deleted"], 2)

        from apps.ai.models import AIScribeSession
        self.assertFalse(AIScribeSession.objects.filter(pk=old_processing.pk).exists())
        self.assertFalse(AIScribeSession.objects.filter(pk=old_failed.pk).exists())

    @override_settings(SCRIBE_SESSION_RETENTION_DAYS=90)
    def test_purge_keeps_completed_sessions(self):
        from apps.ai.tasks import purge_old_scribe_sessions

        old_dt = timezone.now() - datetime.timedelta(days=100)
        completed = self._make_session("completed", old_dt)

        purge_old_scribe_sessions()

        from apps.ai.models import AIScribeSession
        self.assertTrue(AIScribeSession.objects.filter(pk=completed.pk).exists())

    @override_settings(SCRIBE_SESSION_RETENTION_DAYS=90)
    def test_purge_keeps_recent_non_completed_sessions(self):
        from apps.ai.tasks import purge_old_scribe_sessions

        recent_dt = timezone.now() - datetime.timedelta(days=10)
        recent = self._make_session("processing", recent_dt)

        purge_old_scribe_sessions()

        from apps.ai.models import AIScribeSession
        self.assertTrue(AIScribeSession.objects.filter(pk=recent.pk).exists())

    def test_purge_iterates_all_tenant_schemas(self):
        from unittest.mock import MagicMock, call, patch
        from apps.ai.tasks import purge_old_scribe_sessions

        mock_tenant = MagicMock()
        mock_tenant.schema_name = "test_schema"

        mock_tenant_model = MagicMock()
        mock_tenant_model.objects.exclude.return_value = [mock_tenant]

        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=None)
        mock_ctx.__exit__ = MagicMock(return_value=False)

        # Patch at the source module — task does a local import, so we patch
        # the original location which the local import resolves to.
        with patch("django_tenants.utils.get_tenant_model", return_value=mock_tenant_model), \
             patch("django_tenants.utils.tenant_context", return_value=mock_ctx) as mock_tc:
            purge_old_scribe_sessions()

        mock_tc.assert_called_once_with(mock_tenant)
