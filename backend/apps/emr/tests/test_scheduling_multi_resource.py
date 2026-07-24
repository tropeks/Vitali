"""Sprint E5 — Agenda multi-recurso tests.

E5-T1 Resource + AppointmentResource anti-double-booking per resource.
E5-T2 ScheduleException removes availability over the weekly grid.
E5-T3 Encaixe/overbooking with permission + reason, audited.
"""

from datetime import date, datetime, time, timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from apps.core.models import AuditLog, Role, User
from apps.emr.models import (
    Appointment,
    AppointmentResource,
    Patient,
    Professional,
    Resource,
    ScheduleConfig,
    ScheduleException,
)
from apps.emr.services.scheduling import (
    AppointmentSchedulingService,
    is_professional_available,
)
from apps.organization.models import Facility, LegalEntity
from apps.test_utils import TenantTestCase


def _next_weekday(weekday: int) -> date:
    """Return the next future date (strictly after today) matching *weekday*."""
    today = timezone.localdate()
    ahead = (weekday - today.weekday()) % 7
    if ahead == 0:
        ahead = 7
    return today + timedelta(days=ahead)


def _aware(d: date, t: time):
    return timezone.make_aware(datetime.combine(d, t))


def _patient(cpf="111.222.333-00", name="João Silva"):
    return Patient.objects.create(full_name=name, cpf=cpf, birth_date=date(1985, 3, 10), gender="M")


def _professional(email, suffix):
    user, _ = User.objects.get_or_create(email=email, defaults={"full_name": f"Dr {suffix}"})
    prof, _ = Professional.objects.get_or_create(
        user=user,
        defaults={
            "council_type": "CRM",
            "council_number": f"CRM{suffix}",
            "council_state": "SP",
        },
    )
    return prof


def _facility():
    entity = LegalEntity.objects.create(code="LE-1", name="Entidade")
    return Facility.objects.create(code="FAC-1", name="Clínica", legal_entity=entity)


class ResourceDoubleBookingTests(TenantTestCase):
    def setUp(self):
        self.facility = _facility()
        self.resource = Resource.objects.create(
            name="Sala 1", kind=Resource.Kind.ROOM, facility=self.facility
        )
        self.other_resource = Resource.objects.create(
            name="Sala 2", kind=Resource.Kind.ROOM, facility=self.facility
        )
        self.prof_a = _professional("a@c.com", "001")
        self.prof_b = _professional("b@c.com", "002")
        day = _next_weekday(0)
        self.start = _aware(day, time(10, 0))
        self.end = _aware(day, time(10, 30))

    def _appt(self, professional, start, end, patient_cpf):
        return Appointment.objects.create(
            patient=_patient(cpf=patient_cpf),
            professional=professional,
            start_time=start,
            end_time=end,
            status="scheduled",
        )

    def test_overlapping_same_resource_rejected(self):
        appt1 = self._appt(self.prof_a, self.start, self.end, "111.111.111-11")
        AppointmentResource.objects.create(appointment=appt1, resource=self.resource)

        # Different professional, overlapping time -> professional guard passes,
        # but the shared resource must be rejected.
        appt2 = self._appt(
            self.prof_b,
            self.start + timedelta(minutes=15),
            self.end + timedelta(minutes=15),
            "222.222.222-22",
        )
        with self.assertRaises(ValidationError):
            AppointmentResource.objects.create(appointment=appt2, resource=self.resource)

    def test_overlapping_different_resource_ok(self):
        appt1 = self._appt(self.prof_a, self.start, self.end, "111.111.111-11")
        AppointmentResource.objects.create(appointment=appt1, resource=self.resource)

        appt2 = self._appt(self.prof_b, self.start, self.end, "222.222.222-22")
        link = AppointmentResource.objects.create(appointment=appt2, resource=self.other_resource)
        self.assertIsNotNone(link.pk)

    def test_non_overlapping_same_resource_ok(self):
        appt1 = self._appt(self.prof_a, self.start, self.end, "111.111.111-11")
        AppointmentResource.objects.create(appointment=appt1, resource=self.resource)

        later_start = self.end + timedelta(minutes=30)
        appt2 = self._appt(
            self.prof_b, later_start, later_start + timedelta(minutes=30), "222.222.222-22"
        )
        link = AppointmentResource.objects.create(appointment=appt2, resource=self.resource)
        self.assertIsNotNone(link.pk)

    def test_cancelled_appointment_frees_resource(self):
        appt1 = self._appt(self.prof_a, self.start, self.end, "111.111.111-11")
        AppointmentResource.objects.create(appointment=appt1, resource=self.resource)
        appt1.status = "cancelled"
        appt1.save()

        appt2 = self._appt(self.prof_b, self.start, self.end, "222.222.222-22")
        link = AppointmentResource.objects.create(appointment=appt2, resource=self.resource)
        self.assertIsNotNone(link.pk)

    def test_professional_level_guard_still_holds(self):
        self._appt(self.prof_a, self.start, self.end, "111.111.111-11")
        with self.assertRaises(ValidationError):
            self._appt(self.prof_a, self.start, self.end, "222.222.222-22")

    def test_resources_related_name_reverse(self):
        appt = self._appt(self.prof_a, self.start, self.end, "111.111.111-11")
        AppointmentResource.objects.create(appointment=appt, resource=self.resource)
        self.assertIn(self.resource, appt.resources.all())


class ScheduleExceptionAvailabilityTests(TenantTestCase):
    def setUp(self):
        self.prof = _professional("doc@c.com", "010")
        ScheduleConfig.objects.create(
            professional=self.prof,
            working_days=[0, 1, 2, 3, 4],
            working_hours_start=time(8, 0),
            working_hours_end=time(18, 0),
        )
        self.monday = _next_weekday(0)
        self.start = _aware(self.monday, time(10, 0))
        self.end = _aware(self.monday, time(10, 30))

    def test_available_when_grid_allows_and_no_exception(self):
        self.assertTrue(is_professional_available(self.prof, self.start, self.end))

    def test_whole_day_block_removes_availability(self):
        ScheduleException.objects.create(
            professional=self.prof,
            kind=ScheduleException.Kind.VACATION,
            start_date=self.monday,
            end_date=self.monday,
            reason="Férias",
        )
        self.assertFalse(is_professional_available(self.prof, self.start, self.end))

    def test_partial_day_block_only_affects_window(self):
        ScheduleException.objects.create(
            professional=self.prof,
            kind=ScheduleException.Kind.BLOCK,
            start_date=self.monday,
            end_date=self.monday,
            start_time=time(9, 0),
            end_time=time(11, 0),
            reason="Reunião",
        )
        # 10:00-10:30 falls inside the blocked window.
        self.assertFalse(is_professional_available(self.prof, self.start, self.end))
        # 14:00-14:30 is outside the window -> still available.
        s = _aware(self.monday, time(14, 0))
        e = _aware(self.monday, time(14, 30))
        self.assertTrue(is_professional_available(self.prof, s, e))

    def test_multiday_range_blocks_each_day(self):
        friday = _next_weekday(4)
        # Range covering the whole business week around monday..friday.
        ScheduleException.objects.create(
            professional=self.prof,
            kind=ScheduleException.Kind.VACATION,
            start_date=min(self.monday, friday),
            end_date=max(self.monday, friday),
            reason="Férias longas",
        )
        self.assertFalse(is_professional_available(self.prof, self.start, self.end))

    def test_outside_grid_unavailable_without_exception(self):
        sunday = _next_weekday(6)
        s = _aware(sunday, time(10, 0))
        e = _aware(sunday, time(10, 30))
        self.assertFalse(is_professional_available(self.prof, s, e))


class EncaixeOverbookingTests(TenantTestCase):
    def setUp(self):
        self.prof = _professional("enc@c.com", "020")
        ScheduleConfig.objects.create(
            professional=self.prof,
            working_days=[0, 1, 2, 3, 4],
            working_hours_start=time(8, 0),
            working_hours_end=time(18, 0),
        )
        self.patient = _patient(cpf="333.333.333-33")
        self.monday = _next_weekday(0)
        # Outside working hours -> not available.
        self.out_start = _aware(self.monday, time(20, 0))
        self.out_end = _aware(self.monday, time(20, 30))
        # Inside availability.
        self.in_start = _aware(self.monday, time(11, 0))
        self.in_end = _aware(self.monday, time(11, 30))

    def _user_with_encaixe(self):
        role = Role.objects.create(name="recepcionista", permissions=["emr.appointment_encaixe"])
        user, _ = User.objects.get_or_create(email="rec@c.com", defaults={"full_name": "Recep"})
        user.role = role
        user.save()
        return user

    def _user_without_encaixe(self):
        role = Role.objects.create(name="basic", permissions=["emr.read"])
        user, _ = User.objects.get_or_create(email="basic@c.com", defaults={"full_name": "Basic"})
        user.role = role
        user.save()
        return user

    def test_normal_booking_outside_availability_rejected(self):
        user = self._user_with_encaixe()
        service = AppointmentSchedulingService(requesting_user=user)
        with self.assertRaises(ValidationError):
            service.create(
                patient=self.patient,
                professional=self.prof,
                start_time=self.out_start,
                end_time=self.out_end,
            )
        self.assertEqual(Appointment.objects.count(), 0)

    def test_booking_inside_availability_succeeds_without_encaixe(self):
        user = self._user_with_encaixe()
        service = AppointmentSchedulingService(requesting_user=user)
        appt = service.create(
            patient=self.patient,
            professional=self.prof,
            start_time=self.in_start,
            end_time=self.in_end,
        )
        self.assertIsNotNone(appt.pk)
        self.assertFalse(AuditLog.objects.filter(action="appointment_encaixe").exists())

    def test_encaixe_without_permission_denied(self):
        user = self._user_without_encaixe()
        service = AppointmentSchedulingService(requesting_user=user)
        with self.assertRaises(PermissionDenied):
            service.create(
                patient=self.patient,
                professional=self.prof,
                start_time=self.out_start,
                end_time=self.out_end,
                encaixe=True,
                encaixe_reason="Urgência",
            )
        self.assertEqual(Appointment.objects.count(), 0)

    def test_encaixe_without_reason_rejected(self):
        user = self._user_with_encaixe()
        service = AppointmentSchedulingService(requesting_user=user)
        with self.assertRaises(ValidationError):
            service.create(
                patient=self.patient,
                professional=self.prof,
                start_time=self.out_start,
                end_time=self.out_end,
                encaixe=True,
                encaixe_reason="   ",
            )
        self.assertEqual(Appointment.objects.count(), 0)

    def test_encaixe_with_permission_and_reason_succeeds_and_audits(self):
        user = self._user_with_encaixe()
        service = AppointmentSchedulingService(requesting_user=user)
        appt = service.create(
            patient=self.patient,
            professional=self.prof,
            start_time=self.out_start,
            end_time=self.out_end,
            encaixe=True,
            encaixe_reason="Paciente em urgência",
        )
        self.assertIsNotNone(appt.pk)
        audit = AuditLog.objects.filter(
            action="appointment_encaixe",
            resource_type="appointment",
            resource_id=str(appt.id),
        ).first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.new_data["reason"], "Paciente em urgência")
        self.assertEqual(audit.user_id, user.id)
