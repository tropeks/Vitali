"""Tests for the smart-scheduling ranker service + REST endpoint."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from datetime import timezone as tz_module

from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import FeatureFlag, Role, User
from apps.emr.models import Appointment, Patient, Professional, ScheduleConfig
from apps.smart_scheduling.services.ranker import suggest_slots
from apps.test_utils import TenantTestCase

SUGGEST_URL = "/api/v1/scheduling/suggest/"


def _make_user(*, role_name: str, perms: list[str], full_name: str = "Tester") -> User:
    role, _ = Role.objects.get_or_create(name=role_name, defaults={"permissions": perms})
    role.permissions = perms
    role.save()
    return User.objects.create_user(
        email=f"{role_name}@test.com", password="pw", role=role, full_name=full_name
    )


class SmartSchedulingTest(TenantTestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key="smart_scheduling",
            defaults={"is_enabled": True},
        )
        self.user = _make_user(role_name="sched_user", perms=["smart_scheduling.read"])
        self.client.force_authenticate(user=self.user)

        self.patient = Patient.objects.create(
            full_name="Ana Souza",
            cpf="12345678909",
            birth_date=date(1985, 7, 14),
            gender="F",
        )
        self.md_user = _make_user(
            role_name="md_sched",
            perms=["smart_scheduling.read"],
            full_name="Dra Bia",
        )
        self.professional = Professional.objects.create(
            user=self.md_user,
            council_type="CRM",
            council_number="900200",
            council_state="SP",
        )
        # 30-minute slots, Mon-Fri 8-12 / 14-18.
        self.config = ScheduleConfig.objects.create(
            professional=self.professional,
            slot_duration_minutes=30,
            working_days=["monday", "tuesday", "wednesday", "thursday", "friday"],
            working_hours_start=time(8, 0),
            working_hours_end=time(18, 0),
            lunch_start=time(12, 0),
            lunch_end=time(14, 0),
        )
        # Pick a future Wednesday so tests are deterministic regardless of
        # when the suite runs.
        d = date.today()
        while d.strftime("%A").lower() != "wednesday" or d <= date.today():
            d += timedelta(days=1)
        self.wednesday = d

    # ─── Service-level ────────────────────────────────────────────────────────

    def test_returns_zero_slots_when_no_schedule_config(self):
        # Build a professional with no schedule config
        u = _make_user(role_name="no_sched", perms=[], full_name="No Sched")
        prof = Professional.objects.create(
            user=u, council_type="CRM", council_number="000111", council_state="SP"
        )
        slots = suggest_slots(
            professional=prof,
            patient=None,
            from_date=self.wednesday,
            to_date=self.wednesday,
        )
        self.assertEqual(slots, [])

    def test_returns_slots_within_working_hours(self):
        slots = suggest_slots(
            professional=self.professional,
            patient=None,
            from_date=self.wednesday,
            to_date=self.wednesday,
            limit=50,
        )
        # 8-12 = 8 slots, 14-18 = 8 slots = 16 candidate slots
        self.assertEqual(len(slots), 16)
        for slot in slots:
            self.assertEqual(slot.start.date(), self.wednesday)
            self.assertGreaterEqual(slot.start.hour, 8)
            self.assertLess(slot.start.hour, 18)
            # No slots overlap lunch
            self.assertFalse(12 <= slot.start.hour < 14)

    def test_top_ranked_slot_prefers_clinical_morning(self):
        slots = suggest_slots(
            professional=self.professional,
            patient=None,
            from_date=self.wednesday,
            to_date=self.wednesday,
            limit=3,
        )
        # 10am is the explicit peak in _HOUR_SCORE — should be the top slot
        # (in an empty schedule the gap_fill is constant so clinical wins).
        self.assertEqual(slots[0].start.hour, 10)

    def test_taken_slot_is_excluded(self):
        # Book the 10am slot directly.
        start = timezone.make_aware(
            datetime.combine(self.wednesday, time(10, 0)),
            timezone.get_current_timezone(),
        )
        end = start + timedelta(minutes=30)
        Appointment.objects.create(
            patient=self.patient,
            professional=self.professional,
            start_time=start,
            end_time=end,
        )
        slots = suggest_slots(
            professional=self.professional,
            patient=None,
            from_date=self.wednesday,
            to_date=self.wednesday,
            limit=50,
        )
        starts = {(s.start.hour, s.start.minute) for s in slots}
        self.assertNotIn((10, 0), starts)
        # And we have 1 fewer slot
        self.assertEqual(len(slots), 15)

    def test_patient_history_score_boosts_familiar_hour(self):
        # Patient has 3 completed appointments at 15:00 in the past.
        for offset in range(3):
            past_start = timezone.make_aware(
                datetime.combine(self.wednesday - timedelta(days=7 + offset * 7), time(15, 0)),
                timezone.get_current_timezone(),
            )
            Appointment.objects.create(
                patient=self.patient,
                professional=self.professional,
                start_time=past_start,
                end_time=past_start + timedelta(minutes=30),
                status="completed",
            )

        slots_with_patient = suggest_slots(
            professional=self.professional,
            patient=self.patient,
            from_date=self.wednesday,
            to_date=self.wednesday,
            limit=50,
        )
        slots_no_patient = suggest_slots(
            professional=self.professional,
            patient=None,
            from_date=self.wednesday,
            to_date=self.wednesday,
            limit=50,
        )
        # Find the score for the 15:00 slot in both runs.
        score_with = next(s for s in slots_with_patient if s.start.hour == 15).score
        score_without = next(s for s in slots_no_patient if s.start.hour == 15).score
        self.assertGreater(score_with, score_without)

    def test_from_date_must_be_le_to_date(self):
        with self.assertRaises(ValueError):
            suggest_slots(
                professional=self.professional,
                patient=None,
                from_date=self.wednesday + timedelta(days=1),
                to_date=self.wednesday,
            )

    def test_limit_must_be_positive(self):
        with self.assertRaises(ValueError):
            suggest_slots(
                professional=self.professional,
                patient=None,
                from_date=self.wednesday,
                to_date=self.wednesday,
                limit=0,
            )

    # ─── Endpoint ─────────────────────────────────────────────────────────────

    def test_endpoint_returns_ranked_suggestions(self):
        resp = self.client.get(
            SUGGEST_URL,
            {
                "professional": str(self.professional.pk),
                "from": self.wednesday.isoformat(),
                "to": self.wednesday.isoformat(),
                "limit": 5,
            },
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data["professional_id"], str(self.professional.pk))
        self.assertEqual(len(resp.data["suggestions"]), 5)
        scores = [s["score"] for s in resp.data["suggestions"]]
        # Must be sorted descending by score
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_endpoint_missing_professional_returns_400(self):
        resp = self.client.get(SUGGEST_URL)
        self.assertEqual(resp.status_code, 400)

    def test_endpoint_unknown_professional_returns_404(self):
        resp = self.client.get(
            SUGGEST_URL,
            {"professional": "00000000-0000-4000-8000-000000000000"},
        )
        self.assertEqual(resp.status_code, 404)

    def test_endpoint_to_before_from_returns_400(self):
        resp = self.client.get(
            SUGGEST_URL,
            {
                "professional": str(self.professional.pk),
                "from": self.wednesday.isoformat(),
                "to": (self.wednesday - timedelta(days=1)).isoformat(),
            },
        )
        self.assertEqual(resp.status_code, 400)

    def test_endpoint_window_too_wide_returns_400(self):
        resp = self.client.get(
            SUGGEST_URL,
            {
                "professional": str(self.professional.pk),
                "from": self.wednesday.isoformat(),
                "to": (self.wednesday + timedelta(days=90)).isoformat(),
            },
        )
        self.assertEqual(resp.status_code, 400)

    def test_endpoint_unknown_patient_returns_404(self):
        resp = self.client.get(
            SUGGEST_URL,
            {
                "professional": str(self.professional.pk),
                "patient": "00000000-0000-4000-8000-000000000000",
            },
        )
        self.assertEqual(resp.status_code, 404)

    def test_endpoint_blocked_when_module_disabled(self):
        FeatureFlag.objects.filter(
            tenant=self.__class__.tenant, module_key="smart_scheduling"
        ).update(is_enabled=False)
        resp = self.client.get(SUGGEST_URL, {"professional": str(self.professional.pk)})
        self.assertEqual(resp.status_code, 403)

    def test_endpoint_blocked_without_permission(self):
        no_perm = _make_user(role_name="no_sched_perm", perms=["patients.read"])
        self.client.force_authenticate(user=no_perm)
        resp = self.client.get(SUGGEST_URL, {"professional": str(self.professional.pk)})
        self.assertEqual(resp.status_code, 403)

    def test_endpoint_unauthenticated_returns_401(self):
        self.client.logout()
        resp = self.client.get(SUGGEST_URL, {"professional": str(self.professional.pk)})
        self.assertIn(resp.status_code, [401, 403])


# Suppress unused warnings for date imports.
_ = tz_module
