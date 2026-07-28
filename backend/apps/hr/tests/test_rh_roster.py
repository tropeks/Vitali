"""S2-T3 — DutyRoster / RosterSlot + emr availability read-side integration."""

from datetime import date, datetime, time, timedelta

from django.utils import timezone

from apps.core.models import User
from apps.emr.models import Professional, ScheduleConfig
from apps.emr.services.scheduling import is_professional_available
from apps.hr.models import DutyRoster, RosterSlot
from apps.organization.models import Facility, LegalEntity, OrganizationalUnit
from apps.test_utils import TenantTestCase


def _facility(code="R"):
    entity = LegalEntity.objects.create(code=f"LE-{code}", name="Entidade")
    return Facility.objects.create(code=f"FAC-{code}", name="Clínica", legal_entity=entity)


def _unit(facility, code="RU-1"):
    return OrganizationalUnit.objects.create(code=code, name="Pronto-socorro", facility=facility)


def _professional(email="doc.roster@test.local", suffix="R1"):
    user, _ = User.objects.get_or_create(email=email, defaults={"full_name": f"Dr {suffix}"})
    prof, _ = Professional.objects.get_or_create(
        user=user,
        defaults={"council_type": "CRM", "council_number": f"CRM{suffix}", "council_state": "SP"},
    )
    return prof


def _next_weekday(weekday: int) -> date:
    today = timezone.localdate()
    ahead = (weekday - today.weekday()) % 7
    if ahead == 0:
        ahead = 7
    return today + timedelta(days=ahead)


def _aware(d: date, t: time):
    return timezone.make_aware(datetime.combine(d, t))


class RosterSlotTests(TenantTestCase):
    def setUp(self):
        self.facility = _facility()
        self.unit = _unit(self.facility)
        self.roster = DutyRoster.objects.create(
            facility=self.facility,
            name="Escala PS agosto",
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 31),
        )
        self.prof = _professional()

    def test_roster_slot_creation_and_str(self):
        day = date(2026, 8, 10)
        slot = RosterSlot.objects.create(
            roster=self.roster,
            professional=self.prof,
            unit=self.unit,
            date=day,
            shift=RosterSlot.Shift.MORNING,
            start_time=time(7, 0),
            end_time=time(13, 0),
        )
        assert slot.roster_id == self.roster.id
        assert str(day) in str(slot)

    def test_on_duty_returns_covering_slots(self):
        day = date(2026, 8, 10)
        RosterSlot.objects.create(
            roster=self.roster,
            professional=self.prof,
            unit=self.unit,
            date=day,
            shift=RosterSlot.Shift.MORNING,
            start_time=time(7, 0),
            end_time=time(13, 0),
        )
        on = RosterSlot.on_duty(self.unit, _aware(day, time(9, 0)))
        assert on.count() == 1

    def test_on_duty_excludes_out_of_window(self):
        day = date(2026, 8, 10)
        RosterSlot.objects.create(
            roster=self.roster,
            professional=self.prof,
            unit=self.unit,
            date=day,
            shift=RosterSlot.Shift.MORNING,
            start_time=time(7, 0),
            end_time=time(13, 0),
        )
        assert RosterSlot.on_duty(self.unit, _aware(day, time(18, 0))).count() == 0


class OvernightRosterSlotTests(TenantTestCase):
    """S-IA2 Task C — a plantão crossing midnight (19h→07h) is representable."""

    def setUp(self):
        self.facility = _facility(code="ON")
        self.unit = _unit(self.facility, code="ONU-1")
        self.roster = DutyRoster.objects.create(
            facility=self.facility,
            name="Escala noturna",
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 31),
        )
        self.prof = _professional(email="doc.night@test.local", suffix="ON1")

    def _overnight(self, day):
        return RosterSlot.objects.create(
            roster=self.roster,
            professional=self.prof,
            unit=self.unit,
            date=day,
            shift=RosterSlot.Shift.NIGHT,
            start_time=time(19, 0),
            end_time=time(7, 0),  # next day — end < start
        )

    def test_overnight_slot_can_be_created(self):
        day = date(2026, 8, 10)
        slot = self._overnight(day)
        slot.full_clean()  # clean() must not reject end < start
        assert RosterSlot.objects.filter(pk=slot.pk).exists()

    def test_on_duty_matches_evening_and_early_morning(self):
        day = date(2026, 8, 10)
        self._overnight(day)
        assert RosterSlot.on_duty(self.unit, _aware(day, time(23, 0))).count() == 1
        assert RosterSlot.on_duty(self.unit, _aware(day, time(5, 0))).count() == 1

    def test_on_duty_excludes_daytime_gap(self):
        day = date(2026, 8, 10)
        self._overnight(day)
        # 12:00 is outside the 19h→07h window.
        assert RosterSlot.on_duty(self.unit, _aware(day, time(12, 0))).count() == 0

    def test_zero_length_slot_still_rejected(self):
        from django.core.exceptions import ValidationError

        slot = RosterSlot(
            roster=self.roster,
            professional=self.prof,
            unit=self.unit,
            date=date(2026, 8, 11),
            start_time=time(8, 0),
            end_time=time(8, 0),
        )
        try:
            slot.full_clean()
            raised = False
        except ValidationError:
            raised = True
        assert raised, "end_time == start_time must still be rejected"


class RosterAvailabilityIntegrationTests(TenantTestCase):
    """The duty roster constrains emr availability without breaking pre-roster use."""

    def setUp(self):
        self.facility = _facility(code="AV")
        self.unit = _unit(self.facility, code="AVU-1")
        self.prof = _professional(email="doc.avail@test.local", suffix="AV1")
        self.day = _next_weekday(0)  # a Monday, inside default working_days
        ScheduleConfig.objects.create(
            professional=self.prof,
            working_days=[0, 1, 2, 3, 4],
            working_hours_start=time(7, 0),
            working_hours_end=time(19, 0),
            is_active=True,
        )
        self.roster = DutyRoster.objects.create(
            facility=self.facility,
            name="Escala",
            start_date=self.day,
            end_date=self.day,
        )
        self.start = _aware(self.day, time(9, 0))
        self.end = _aware(self.day, time(9, 30))

    def test_availability_unconstrained_when_no_roster(self):
        # No slots for this professional/day → grid governs (backward compatible).
        assert is_professional_available(self.prof, self.start, self.end) is True

    def test_availability_true_when_on_duty(self):
        RosterSlot.objects.create(
            roster=self.roster,
            professional=self.prof,
            unit=self.unit,
            date=self.day,
            shift=RosterSlot.Shift.MORNING,
            start_time=time(7, 0),
            end_time=time(13, 0),
        )
        assert is_professional_available(self.prof, self.start, self.end) is True

    def test_availability_false_when_rostered_but_off_duty(self):
        # Rostered that day, but only for the night shift → daytime unavailable.
        RosterSlot.objects.create(
            roster=self.roster,
            professional=self.prof,
            unit=self.unit,
            date=self.day,
            shift=RosterSlot.Shift.NIGHT,
            start_time=time(19, 0),
            end_time=time(23, 0),
        )
        assert is_professional_available(self.prof, self.start, self.end) is False
