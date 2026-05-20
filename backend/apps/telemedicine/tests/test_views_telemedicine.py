"""Integration tests for the telemedicine session-tracking REST surface."""

from __future__ import annotations

from datetime import date, timedelta

from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import FeatureFlag, Role, User
from apps.emr.models import Patient, Professional
from apps.telemedicine.models import TelemedicineSession
from apps.test_utils import TenantTestCase

LIST_URL = "/api/v1/telemedicine/sessions/"


def _detail(pk):
    return f"/api/v1/telemedicine/sessions/{pk}/"


def _start(pk):
    return f"/api/v1/telemedicine/sessions/{pk}/start/"


def _complete(pk):
    return f"/api/v1/telemedicine/sessions/{pk}/complete/"


def _cancel(pk):
    return f"/api/v1/telemedicine/sessions/{pk}/cancel/"


def _recording(pk):
    return f"/api/v1/telemedicine/sessions/{pk}/recording/"


def _make_user(*, role_name: str, perms: list[str], full_name: str = "Tester") -> User:
    role, _ = Role.objects.get_or_create(name=role_name, defaults={"permissions": perms})
    role.permissions = perms
    role.save()
    return User.objects.create_user(
        email=f"{role_name}@test.com", password="pw", role=role, full_name=full_name
    )


class TelemedicineSessionViewsTest(TenantTestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key="telemedicine",
            defaults={"is_enabled": True},
        )
        self.host_user = _make_user(
            role_name="tele_host",
            perms=["telemedicine.read", "telemedicine.host"],
            full_name="Telemed Host",
        )
        self.reader_user = _make_user(
            role_name="tele_reader",
            perms=["telemedicine.read"],
            full_name="Telemed Reader",
        )
        self.client.force_authenticate(user=self.host_user)

        self.patient = Patient.objects.create(
            full_name="Ana Maria Souza",
            cpf="12345678909",
            birth_date=date(1985, 7, 14),
            gender="F",
        )
        self.md_user = _make_user(
            role_name="md_tele",
            perms=["telemedicine.read", "telemedicine.host"],
            full_name="Dra Bia",
        )
        self.professional = Professional.objects.create(
            user=self.md_user,
            council_type="CRM",
            council_number="700400",
            council_state="SP",
        )

    def _create_session(self, status="scheduled"):
        session = TelemedicineSession.objects.create(
            patient=self.patient,
            professional=self.professional,
            scheduled_for=timezone.now() + timedelta(hours=1),
            status=status,
            created_by=self.host_user,
        )
        return session

    # ─── Create + list ────────────────────────────────────────────────────────

    def test_create_session_mints_room_uid(self):
        payload = {
            "patient": str(self.patient.pk),
            "professional": str(self.professional.pk),
            "scheduled_for": (timezone.now() + timedelta(hours=2)).isoformat(),
            "notes": "Teleconsulta retorno.",
        }
        resp = self.client.post(LIST_URL, payload, format="json")
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data["status"], "scheduled")
        self.assertTrue(resp.data["room_uid"])
        self.assertEqual(resp.data["created_by"], self.host_user.pk)

    def test_list_filters_by_status(self):
        self._create_session(status="scheduled")
        s2 = self._create_session(status="scheduled")
        s2.status = "in_progress"
        s2.started_at = timezone.now()
        s2.save(update_fields=["status", "started_at"])
        resp = self.client.get(LIST_URL, {"status": "in_progress"})
        ids = {entry["id"] for entry in resp.data}
        self.assertEqual(ids, {str(s2.pk)})

    def test_detail_returns_session(self):
        s = self._create_session()
        resp = self.client.get(_detail(s.pk))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["status_display"], "Agendada")

    def test_detail_unknown_id_returns_404(self):
        resp = self.client.get(_detail("00000000-0000-4000-8000-000000000000"))
        self.assertEqual(resp.status_code, 404)

    # ─── State transitions ────────────────────────────────────────────────────

    def test_start_transitions_scheduled_to_in_progress(self):
        s = self._create_session()
        resp = self.client.post(_start(s.pk))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["status"], "in_progress")
        self.assertIsNotNone(resp.data["started_at"])

    def test_complete_computes_duration(self):
        s = self._create_session()
        s.start()
        # Backdate `started_at` so duration is deterministic.
        s.started_at = timezone.now() - timedelta(minutes=20)
        s.save(update_fields=["started_at"])
        resp = self.client.post(_complete(s.pk))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["status"], "completed")
        # ~20 minutes give or take a few seconds.
        self.assertGreaterEqual(resp.data["duration_seconds"], 1190)
        self.assertLessEqual(resp.data["duration_seconds"], 1210)

    def test_complete_from_scheduled_returns_409(self):
        s = self._create_session()
        resp = self.client.post(_complete(s.pk))
        self.assertEqual(resp.status_code, 409)

    def test_cancel_from_scheduled(self):
        s = self._create_session()
        resp = self.client.post(_cancel(s.pk))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["status"], "cancelled")

    def test_cancel_in_progress_records_partial_duration(self):
        s = self._create_session()
        s.start()
        s.started_at = timezone.now() - timedelta(minutes=5)
        s.save(update_fields=["started_at"])
        resp = self.client.post(_cancel(s.pk))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["status"], "cancelled")
        self.assertIsNotNone(resp.data["duration_seconds"])

    def test_cannot_transition_from_terminal_state(self):
        s = self._create_session()
        s.cancel()
        resp = self.client.post(_start(s.pk))
        self.assertEqual(resp.status_code, 409)

    # ─── Recording ────────────────────────────────────────────────────────────

    def test_recording_patch_sets_url(self):
        s = self._create_session()
        resp = self.client.patch(
            _recording(s.pk),
            {"recording_url": "https://example.com/recordings/abc.mp4"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["recording_url"], "https://example.com/recordings/abc.mp4")

    def test_recording_patch_rejects_invalid_url(self):
        s = self._create_session()
        resp = self.client.patch(_recording(s.pk), {"recording_url": "not-a-url"}, format="json")
        self.assertEqual(resp.status_code, 400)

    # ─── Gates ────────────────────────────────────────────────────────────────

    def test_start_blocked_without_host_permission(self):
        s = self._create_session()
        self.client.force_authenticate(user=self.reader_user)
        resp = self.client.post(_start(s.pk))
        self.assertEqual(resp.status_code, 403)

    def test_reader_can_list(self):
        self._create_session()
        self.client.force_authenticate(user=self.reader_user)
        resp = self.client.get(LIST_URL)
        self.assertEqual(resp.status_code, 200)
        self.assertGreaterEqual(len(resp.data), 1)

    def test_list_blocked_when_module_disabled(self):
        FeatureFlag.objects.filter(tenant=self.__class__.tenant, module_key="telemedicine").update(
            is_enabled=False
        )
        resp = self.client.get(LIST_URL)
        self.assertEqual(resp.status_code, 403)

    def test_list_unauthenticated_returns_401(self):
        self.client.logout()
        resp = self.client.get(LIST_URL)
        self.assertIn(resp.status_code, [401, 403])
