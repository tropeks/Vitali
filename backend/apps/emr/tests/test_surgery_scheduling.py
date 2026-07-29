"""
C2 — Centro Cirúrgico scheduling: the atomic slot state machine + its API.

Covers the scheduling service (schedule / reschedule / confirm / cancel with the
room-slot overlap-guard and the status-transition rules) AND the DRF actions
(``schedule`` / ``reschedule`` / ``confirm`` / ``cancel`` gated ``surgery.schedule``,
overlap → 409; the ``board`` mapa cirúrgico gated ``surgery.read``).

Overlap predicate: two blocking cases on the SAME room conflict when
``existing.scheduled_start < new_end AND existing.scheduled_end > new_start`` —
finalizada / cancelada cases free the slot.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.core.models import Role, TUSSCode, User
from apps.emr.models import (
    OperatingRoom,
    Patient,
    Professional,
    SurgicalCase,
    SurgicalProcedure,
    SurgicalTeamMember,
)
from apps.emr.services import surgery_scheduling as svc
from apps.organization.models import Facility, LegalEntity
from apps.test_utils import TenantTestCase

BASE = "/api/v1"

SCHEDULE_PERMS = ["surgery.read", "surgery.schedule"]
MANAGE_PERMS = ["surgery.read", "surgery.manage"]
READ_PERMS = ["surgery.read"]


def _dt(hour, minute=0, day=15):
    """A fixed aware datetime on 2026-08-``day``."""
    return datetime(2026, 8, day, hour, minute, tzinfo=UTC)


class SchedulingTestBase(TenantTestCase):
    def setUp(self):
        self.schedule_role = Role.objects.create(name="cirurgiao_cc", permissions=SCHEDULE_PERMS)
        self.manage_role = Role.objects.create(name="gestor_cc", permissions=MANAGE_PERMS)
        self.read_role = Role.objects.create(name="enf_cc", permissions=READ_PERMS)
        self.none_role = Role.objects.create(name="sem_perm", permissions=[])
        self.scheduler = User.objects.create_user(
            email="cir@t.com", password="pw", role=self.schedule_role
        )
        self.manager = User.objects.create_user(
            email="gestor@t.com", password="pw", role=self.manage_role
        )
        self.reader = User.objects.create_user(
            email="enfcc@t.com", password="pw", role=self.read_role
        )
        self.nobody = User.objects.create_user(
            email="none@t.com", password="pw", role=self.none_role
        )

        self.legal = LegalEntity.objects.create(code="LE1", name="Hospital SA")
        self.facility = Facility.objects.create(
            code="FAC1", name="Hospital Central", legal_entity=self.legal
        )
        self.surgeon = Professional.objects.create(
            user=self.scheduler,
            council_type="CRM",
            council_number="12345",
            council_state="SP",
        )
        self.patient = Patient.objects.create(
            full_name="Maria Operada", birth_date="1980-01-01", gender="F", cpf="52998224725"
        )
        self.room = OperatingRoom.objects.create(facility=self.facility, code="SO-1", name="Sala 1")
        self.room2 = OperatingRoom.objects.create(
            facility=self.facility, code="SO-2", name="Sala 2"
        )

    def _case(self, **kw):
        defaults = {"patient": self.patient, "surgeon": self.surgeon}
        defaults.update(kw)
        return SurgicalCase.objects.create(**defaults)

    def _client(self, user):
        c = APIClient()
        c.defaults["SERVER_NAME"] = self.__class__.domain.domain
        c.force_authenticate(user)
        return c


class TestScheduleService(SchedulingTestBase):
    def test_schedule_sets_room_times_and_keeps_status(self):
        case = self._case()
        out = svc.schedule(case, self.room, _dt(8), _dt(10))
        out.refresh_from_db()
        assert out.operating_room_id == self.room.id
        assert out.scheduled_start == _dt(8)
        assert out.scheduled_end == _dt(10)
        assert out.status == SurgicalCase.Status.AGENDADA

    def test_schedule_confirmed_case_keeps_confirmada(self):
        case = self._case(status=SurgicalCase.Status.CONFIRMADA)
        out = svc.schedule(case, self.room, _dt(8), _dt(10))
        assert out.status == SurgicalCase.Status.CONFIRMADA

    def test_schedule_requires_end_after_start(self):
        case = self._case()
        with pytest.raises(ValidationError):
            svc.schedule(case, self.room, _dt(10), _dt(8))
        with pytest.raises(ValidationError):
            svc.schedule(case, self.room, _dt(10), _dt(10))

    def test_overlapping_case_same_room_rejected(self):
        self._case(
            operating_room=self.room,
            scheduled_start=_dt(8),
            scheduled_end=_dt(10),
            status=SurgicalCase.Status.AGENDADA,
        )
        new = self._case()
        with pytest.raises(ValidationError):
            svc.schedule(new, self.room, _dt(9), _dt(11))  # overlaps [8,10)

    def test_adjacent_slot_same_room_ok(self):
        self._case(
            operating_room=self.room,
            scheduled_start=_dt(8),
            scheduled_end=_dt(10),
        )
        new = self._case()
        # [10,12) touches but does not overlap [8,10) — half-open intervals.
        out = svc.schedule(new, self.room, _dt(10), _dt(12))
        assert out.scheduled_start == _dt(10)

    def test_overlap_on_different_room_ok(self):
        # Distinct surgeon on the pre-existing case so this isolates the ROOM
        # dimension (same surgeon overlapping is a separate CS1 conflict).
        other_role = Role.objects.create(name="cir_outro", permissions=SCHEDULE_PERMS)
        other_user = User.objects.create_user(
            email="outrocir@t.com", password="pw", role=other_role, full_name="Outro Cirurgião"
        )
        other_surgeon = Professional.objects.create(
            user=other_user, council_type="CRM", council_number="54321", council_state="SP"
        )
        self._case(
            surgeon=other_surgeon,
            operating_room=self.room,
            scheduled_start=_dt(8),
            scheduled_end=_dt(10),
        )
        new = self._case()
        out = svc.schedule(new, self.room2, _dt(8), _dt(10))
        assert out.operating_room_id == self.room2.id

    def test_cancelled_case_does_not_block(self):
        self._case(
            operating_room=self.room,
            scheduled_start=_dt(8),
            scheduled_end=_dt(10),
            status=SurgicalCase.Status.CANCELADA,
        )
        new = self._case()
        out = svc.schedule(new, self.room, _dt(8), _dt(10))
        assert out.scheduled_start == _dt(8)

    def test_finalizada_case_does_not_block(self):
        self._case(
            operating_room=self.room,
            scheduled_start=_dt(8),
            scheduled_end=_dt(10),
            status=SurgicalCase.Status.FINALIZADA,
        )
        new = self._case()
        out = svc.schedule(new, self.room, _dt(8), _dt(10))
        assert out.scheduled_start == _dt(8)

    def test_cannot_schedule_cancelled_case(self):
        case = self._case(status=SurgicalCase.Status.CANCELADA)
        with pytest.raises(ValidationError):
            svc.schedule(case, self.room, _dt(8), _dt(10))

    def test_cannot_schedule_finalizada_case(self):
        case = self._case(status=SurgicalCase.Status.FINALIZADA)
        with pytest.raises(ValidationError):
            svc.schedule(case, self.room, _dt(8), _dt(10))


class TestProfessionalAvailability(SchedulingTestBase):
    """CS1 — the same surgeon / team member cannot be booked on two overlapping
    surgical cases even when they run in different rooms."""

    def _make_surgeon(self, email, council_number):
        role = Role.objects.create(name=f"role_{council_number}", permissions=SCHEDULE_PERMS)
        user = User.objects.create_user(email=email, password="pw", role=role, full_name=email)
        return Professional.objects.create(
            user=user,
            council_type="CRM",
            council_number=council_number,
            council_state="SP",
        )

    def test_same_surgeon_overlapping_different_room_rejected(self):
        # Case A: surgeon busy [8,10) in room1.
        self._case(
            operating_room=self.room,
            scheduled_start=_dt(8),
            scheduled_end=_dt(10),
            status=SurgicalCase.Status.AGENDADA,
        )
        # Case B: SAME surgeon (default self.surgeon), different room, overlaps.
        new = self._case()
        with pytest.raises(ValidationError):
            svc.schedule(new, self.room2, _dt(9), _dt(11))

    def test_same_team_member_overlapping_different_surgeons_rejected(self):
        other_surgeon = self._make_surgeon("outro@t.com", "99999")
        shared = self._make_surgeon("aux@t.com", "88888")

        case_a = self._case(
            surgeon=other_surgeon,
            operating_room=self.room,
            scheduled_start=_dt(8),
            scheduled_end=_dt(10),
            status=SurgicalCase.Status.AGENDADA,
        )
        SurgicalTeamMember.objects.create(
            case=case_a, professional=shared, role=SurgicalTeamMember.Role.PRIMEIRO_AUXILIAR
        )

        # Case B has a different surgeon but the SAME auxiliary on its team.
        case_b = self._case(surgeon=self.surgeon)
        SurgicalTeamMember.objects.create(
            case=case_b, professional=shared, role=SurgicalTeamMember.Role.PRIMEIRO_AUXILIAR
        )
        with pytest.raises(ValidationError):
            svc.schedule(case_b, self.room2, _dt(9), _dt(11))

    def test_distinct_professionals_overlapping_different_room_ok(self):
        other_surgeon = self._make_surgeon("outro2@t.com", "77777")
        self._case(
            surgeon=other_surgeon,
            operating_room=self.room,
            scheduled_start=_dt(8),
            scheduled_end=_dt(10),
            status=SurgicalCase.Status.AGENDADA,
        )
        # Different surgeon, different room, overlapping time → OK.
        new = self._case(surgeon=self.surgeon)
        out = svc.schedule(new, self.room2, _dt(9), _dt(11))
        assert out.operating_room_id == self.room2.id

    def test_same_surgeon_non_overlapping_ok(self):
        self._case(
            operating_room=self.room,
            scheduled_start=_dt(8),
            scheduled_end=_dt(10),
            status=SurgicalCase.Status.AGENDADA,
        )
        new = self._case()  # same surgeon
        out = svc.schedule(new, self.room2, _dt(10), _dt(12))  # touches but no overlap
        assert out.scheduled_start == _dt(10)

    def test_cancelled_case_does_not_block_surgeon(self):
        self._case(
            operating_room=self.room,
            scheduled_start=_dt(8),
            scheduled_end=_dt(10),
            status=SurgicalCase.Status.CANCELADA,
        )
        new = self._case()  # same surgeon, overlapping, but the other case is cancelled
        out = svc.schedule(new, self.room2, _dt(9), _dt(11))
        assert out.scheduled_start == _dt(9)


class TestRescheduleService(SchedulingTestBase):
    def test_reschedule_excludes_self(self):
        case = self._case(operating_room=self.room, scheduled_start=_dt(8), scheduled_end=_dt(10))
        # Moving within an overlapping window on its own room must NOT self-conflict.
        out = svc.reschedule(case, _dt(9), _dt(11))
        out.refresh_from_db()
        assert out.scheduled_start == _dt(9)
        assert out.scheduled_end == _dt(11)
        assert out.operating_room_id == self.room.id  # kept current room

    def test_reschedule_conflicts_with_other_case(self):
        self._case(operating_room=self.room, scheduled_start=_dt(8), scheduled_end=_dt(10))
        case = self._case(operating_room=self.room, scheduled_start=_dt(12), scheduled_end=_dt(13))
        with pytest.raises(ValidationError):
            svc.reschedule(case, _dt(9), _dt(11))

    def test_reschedule_to_new_room(self):
        case = self._case(operating_room=self.room, scheduled_start=_dt(8), scheduled_end=_dt(10))
        out = svc.reschedule(case, _dt(8), _dt(10), operating_room=self.room2)
        assert out.operating_room_id == self.room2.id

    def test_reschedule_without_room_and_no_current_room_rejected(self):
        case = self._case()  # no room
        with pytest.raises(ValidationError):
            svc.reschedule(case, _dt(8), _dt(10))


class TestTransitionsService(SchedulingTestBase):
    def test_confirm_agendada_to_confirmada(self):
        case = self._case()
        out = svc.confirm(case)
        assert out.status == SurgicalCase.Status.CONFIRMADA

    def test_confirm_non_agendada_rejected(self):
        case = self._case(status=SurgicalCase.Status.CONFIRMADA)
        with pytest.raises(ValidationError):
            svc.confirm(case)

    def test_cancel_frees_slot(self):
        case = self._case(operating_room=self.room, scheduled_start=_dt(8), scheduled_end=_dt(10))
        out = svc.cancel(case, reason="paciente desistiu")
        assert out.status == SurgicalCase.Status.CANCELADA
        assert "paciente desistiu" in out.notes
        # slot is now free: another case can take [8,10)
        new = self._case()
        ok = svc.schedule(new, self.room, _dt(8), _dt(10))
        assert ok.scheduled_start == _dt(8)

    def test_cannot_cancel_finalizada(self):
        case = self._case(status=SurgicalCase.Status.FINALIZADA)
        with pytest.raises(ValidationError):
            svc.cancel(case)


class TestSchedulingAPI(SchedulingTestBase):
    def test_schedule_endpoint_ok(self):
        case = self._case()
        resp = self._client(self.scheduler).post(
            f"{BASE}/surgical-cases/{case.id}/schedule/",
            {
                "operating_room": str(self.room.id),
                "scheduled_start": _dt(8).isoformat(),
                "scheduled_end": _dt(10).isoformat(),
            },
            format="json",
        )
        assert resp.status_code == 200, resp.content
        case.refresh_from_db()
        assert case.operating_room_id == self.room.id

    def test_schedule_overlap_returns_409(self):
        self._case(operating_room=self.room, scheduled_start=_dt(8), scheduled_end=_dt(10))
        case = self._case()
        resp = self._client(self.scheduler).post(
            f"{BASE}/surgical-cases/{case.id}/schedule/",
            {
                "operating_room": str(self.room.id),
                "scheduled_start": _dt(9).isoformat(),
                "scheduled_end": _dt(11).isoformat(),
            },
            format="json",
        )
        assert resp.status_code == 409, resp.content
        assert "detail" in resp.data

    def test_schedule_requires_surgery_schedule_perm(self):
        # A manager (surgery.manage but NOT surgery.schedule) is 403 on schedule.
        case = self._case()
        resp = self._client(self.manager).post(
            f"{BASE}/surgical-cases/{case.id}/schedule/",
            {
                "operating_room": str(self.room.id),
                "scheduled_start": _dt(8).isoformat(),
                "scheduled_end": _dt(10).isoformat(),
            },
            format="json",
        )
        assert resp.status_code == 403, resp.content

    def test_schedule_no_perm_forbidden(self):
        case = self._case()
        resp = self._client(self.nobody).post(
            f"{BASE}/surgical-cases/{case.id}/schedule/",
            {
                "operating_room": str(self.room.id),
                "scheduled_start": _dt(8).isoformat(),
                "scheduled_end": _dt(10).isoformat(),
            },
            format="json",
        )
        assert resp.status_code == 403, resp.content

    def test_confirm_and_cancel_endpoints(self):
        case = self._case()
        c = self._client(self.scheduler)
        confirm = c.post(f"{BASE}/surgical-cases/{case.id}/confirm/", {}, format="json")
        assert confirm.status_code == 200, confirm.content
        assert confirm.data["status"] == SurgicalCase.Status.CONFIRMADA
        cancel = c.post(f"{BASE}/surgical-cases/{case.id}/cancel/", {"reason": "x"}, format="json")
        assert cancel.status_code == 200, cancel.content
        assert cancel.data["status"] == SurgicalCase.Status.CANCELADA

    def test_confirm_illegal_transition_returns_409(self):
        case = self._case(status=SurgicalCase.Status.FINALIZADA)
        resp = self._client(self.scheduler).post(
            f"{BASE}/surgical-cases/{case.id}/confirm/", {}, format="json"
        )
        assert resp.status_code == 409, resp.content

    def test_reschedule_endpoint(self):
        case = self._case(operating_room=self.room, scheduled_start=_dt(8), scheduled_end=_dt(10))
        resp = self._client(self.scheduler).post(
            f"{BASE}/surgical-cases/{case.id}/reschedule/",
            {"scheduled_start": _dt(9).isoformat(), "scheduled_end": _dt(11).isoformat()},
            format="json",
        )
        assert resp.status_code == 200, resp.content
        case.refresh_from_db()
        assert case.scheduled_start == _dt(9)


class TestSurgicalBoardAPI(SchedulingTestBase):
    def setUp(self):
        super().setUp()
        self.tuss = TUSSCode.objects.create(
            code="30602246",
            description="Colecistectomia videolaparoscópica",
            group="procedimento",
            version="2024-01",
            active=True,
        )

    def test_board_returns_rooms_with_cases_for_date(self):
        case = self._case(operating_room=self.room, scheduled_start=_dt(8), scheduled_end=_dt(10))
        SurgicalProcedure.objects.create(case=case, tuss_code=self.tuss, quantity=1)
        # A case on another day must NOT appear.
        self._case(
            operating_room=self.room, scheduled_start=_dt(8, day=16), scheduled_end=_dt(10, day=16)
        )
        # A cancelled case on the same day must NOT appear.
        self._case(
            operating_room=self.room2,
            scheduled_start=_dt(8),
            scheduled_end=_dt(10),
            status=SurgicalCase.Status.CANCELADA,
        )

        resp = self._client(self.reader).get(
            f"{BASE}/surgical-cases/board/?date=2026-08-15&facility={self.facility.id}"
        )
        assert resp.status_code == 200, resp.content
        assert resp.data["date"] == "2026-08-15"
        rooms = {r["code"]: r for r in resp.data["rooms"]}
        assert set(rooms) == {"SO-1", "SO-2"}  # both rooms of the facility
        assert len(rooms["SO-1"]["cases"]) == 1
        assert rooms["SO-2"]["cases"] == []  # cancelled case excluded
        board_case = rooms["SO-1"]["cases"][0]
        assert board_case["id"] == str(case.id)
        assert board_case["patient"]["name"] == "Maria Operada"
        assert board_case["surgeon"]["id"] == str(self.surgeon.id)
        assert board_case["status"] == SurgicalCase.Status.AGENDADA
        assert board_case["priority"] == SurgicalCase.Priority.ELETIVA
        assert board_case["procedures"][0]["tuss_code"] == "30602246"

    def test_board_needs_surgery_read(self):
        resp = self._client(self.nobody).get(
            f"{BASE}/surgical-cases/board/?date=2026-08-15&facility={self.facility.id}"
        )
        assert resp.status_code == 403, resp.content

    def test_board_filters_by_operating_room(self):
        self._case(operating_room=self.room, scheduled_start=_dt(8), scheduled_end=_dt(10))
        self._case(operating_room=self.room2, scheduled_start=_dt(8), scheduled_end=_dt(10))
        resp = self._client(self.reader).get(
            f"{BASE}/surgical-cases/board/?date=2026-08-15&operating_room={self.room.id}"
        )
        assert resp.status_code == 200, resp.content
        assert {r["code"] for r in resp.data["rooms"]} == {"SO-1"}
