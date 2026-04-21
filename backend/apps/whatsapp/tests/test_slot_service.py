"""
Tests for slot_service.get_available_slots.
"""
from datetime import date, timedelta
from unittest.mock import patch

from django.utils import timezone
from apps.test_utils import TenantTestCase

from apps.core.models import Role, User


def _make_professional_with_schedule(specialty="Clínica Geral", working_days=None):
    from apps.emr.models import Professional, ScheduleConfig
    role, _ = Role.objects.get_or_create(name="medico_slot", defaults={"permissions": []})
    user = User.objects.create_user(
        email=f"slot_{timezone.now().timestamp()}@test.com",
        password="pw",
        role=role,
        full_name="Dr. Slot",
    )
    pro = Professional.objects.create(
        user=user,
        council_type="CRM",
        council_number=f"SL{id(user)}",
        council_state="SP",
        specialty=specialty,
        is_active=True,
    )
    ScheduleConfig.objects.create(
        professional=pro,
        slot_duration_minutes=30,
        working_days=working_days or [0, 1, 2, 3, 4],
        working_hours_start="08:00",
        working_hours_end="12:00",  # 4h window = 8 slots/day for tests
        lunch_start=None,
        lunch_end=None,
        is_active=True,
    )
    return pro


class SlotServiceTests(TenantTestCase):

    def test_returns_slots_within_working_hours(self):
        from apps.whatsapp.slot_service import get_available_slots
        pro = _make_professional_with_schedule()
        # Pick a weekday
        start = date(2026, 4, 6)  # Monday
        slots = get_available_slots(pro, start_date=start, days_ahead=1)
        self.assertIn(start.isoformat(), slots)
        day_slots = slots[start.isoformat()]
        self.assertGreater(len(day_slots), 0)
        for slot in day_slots:
            self.assertGreaterEqual(slot.start.hour, 8)
            self.assertLessEqual(slot.end.hour, 12)

    def test_excludes_booked_appointments(self):
        from apps.emr.models import Appointment
        from apps.whatsapp.slot_service import get_available_slots
        from apps.emr.models import Patient
        pro = _make_professional_with_schedule()
        start_day = date(2026, 4, 7)  # Tuesday
        from django.utils.timezone import make_aware
        from datetime import datetime
        slot_start = make_aware(datetime(2026, 4, 7, 8, 0))
        slot_end = make_aware(datetime(2026, 4, 7, 8, 30))

        patient = Patient.objects.create(
            full_name="Paciente Slot", cpf="52998224725",
            birth_date="1990-01-01", gender="N",
        )
        Appointment.objects.create(
            patient=patient, professional=pro,
            start_time=slot_start, end_time=slot_end,
            status="scheduled",
        )
        slots = get_available_slots(pro, start_date=start_day, days_ahead=1)
        day_slots = slots.get(start_day.isoformat(), [])
        for slot in day_slots:
            self.assertFalse(
                slot.start < slot_end and slot.end > slot_start,
                f"Slot {slot.label} overlaps with booked appointment"
            )

    def test_excludes_non_working_days(self):
        from apps.whatsapp.slot_service import get_available_slots
        # Only Monday (0)
        pro = _make_professional_with_schedule(working_days=[0])
        start = date(2026, 4, 7)  # Tuesday
        slots = get_available_slots(pro, start_date=start, days_ahead=1)
        self.assertNotIn(start.isoformat(), slots)

    def test_no_schedule_config_returns_empty(self):
        from apps.emr.models import Professional, ScheduleConfig
        from apps.whatsapp.slot_service import get_available_slots
        role, _ = Role.objects.get_or_create(name="medico_noconfig", defaults={"permissions": []})
        user = User.objects.create_user(
            email=f"noconfig_{timezone.now().timestamp()}@test.com",
            password="pw",
            role=role,
        )
        pro = Professional.objects.create(
            user=user, council_type="CRM", council_number="NC001",
            council_state="SP", is_active=True,
        )
        slots = get_available_slots(pro)
        self.assertEqual(slots, {})

    def test_returns_maximum_days_ahead(self):
        from apps.whatsapp.slot_service import get_available_slots
        pro = _make_professional_with_schedule()
        start = date(2026, 4, 6)
        slots = get_available_slots(pro, start_date=start, days_ahead=7)
        # All returned dates must be within 7 days
        for d_str in slots.keys():
            d = date.fromisoformat(d_str)
            self.assertLess((d - start).days, 7)
