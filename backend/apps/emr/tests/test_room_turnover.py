"""
CS3 — Centro Cirúrgico: turnover de sala (higienização/preparo entre cirurgias).

Covers:
* OperatingRoom.turnover_minutes (novo campo, default 30) + exposição no serializer.
* RoomTurnover model + lifecycle do serviço (open_turnover → complete_turnover).
* Enforcement no agendamento: dois casos na MESMA sala precisam de um gap
  >= turnover_minutes entre o fim de um e o início do outro; gap exatamente igual
  passa; casos que se sobrepõem continuam barrados pelo guard de overlap; sala
  diferente não sofre a restrição.
* API: RoomTurnoverViewSet — create / list / retrieve / complete; RBAC.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import Role, User
from apps.emr.models import OperatingRoom, Patient, Professional, RoomTurnover, SurgicalCase
from apps.emr.services import surgery_scheduling as svc
from apps.emr.services import surgery_turnover as turnover_svc
from apps.organization.models import Facility, LegalEntity
from apps.test_utils import TenantTestCase

BASE = "/api/v1"

MANAGE_PERMS = ["surgery.read", "surgery.manage"]
SCHEDULE_PERMS = ["surgery.read", "surgery.schedule"]
READ_PERMS = ["surgery.read"]


def _dt(hour, minute=0, day=15):
    """A fixed aware datetime on 2026-08-``day``."""
    return datetime(2026, 8, day, hour, minute, tzinfo=UTC)


class TurnoverTestBase(TenantTestCase):
    def setUp(self):
        self.manage_role = Role.objects.create(name="gestor_cc", permissions=MANAGE_PERMS)
        self.schedule_role = Role.objects.create(name="cirurgiao_cc", permissions=SCHEDULE_PERMS)
        self.read_role = Role.objects.create(name="enf_cc", permissions=READ_PERMS)
        self.none_role = Role.objects.create(name="sem_perm", permissions=[])
        self.manager = User.objects.create_user(
            email="gestor@t.com", password="pw", role=self.manage_role
        )
        self.scheduler = User.objects.create_user(
            email="cir@t.com", password="pw", role=self.schedule_role
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
        # Room with a 30-min turnover requirement, plus a spare room.
        self.room = OperatingRoom.objects.create(
            facility=self.facility, code="SO-1", name="Sala 1", turnover_minutes=30
        )
        self.room2 = OperatingRoom.objects.create(
            facility=self.facility, code="SO-2", name="Sala 2", turnover_minutes=30
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


# ── OperatingRoom.turnover_minutes field ─────────────────────────────────────


class TestTurnoverMinutesField(TurnoverTestBase):
    def test_default_is_30(self):
        room = OperatingRoom.objects.create(facility=self.facility, code="SO-9", name="Sala 9")
        assert room.turnover_minutes == 30

    def test_serializer_exposes_turnover_minutes(self):
        resp = self._client(self.reader).get(f"{BASE}/operating-rooms/{self.room.id}/")
        assert resp.status_code == 200, resp.content
        assert resp.data["turnover_minutes"] == 30

    def test_create_room_with_turnover_via_api(self):
        resp = self._client(self.manager).post(
            f"{BASE}/operating-rooms/",
            {
                "facility": str(self.facility.id),
                "code": "SO-3",
                "name": "Sala 3",
                "turnover_minutes": 45,
            },
            format="json",
        )
        assert resp.status_code == 201, resp.content
        assert OperatingRoom.objects.get(code="SO-3").turnover_minutes == 45


# ── RoomTurnover model + lifecycle service ───────────────────────────────────


class TestRoomTurnoverModel(TurnoverTestBase):
    def test_create_turnover(self):
        case_out = self._case()
        t = RoomTurnover.objects.create(
            operating_room=self.room,
            case_out=case_out,
            started_at=timezone.now(),
            performed_by=self.surgeon,
        )
        assert t.status == RoomTurnover.Status.AGUARDANDO
        assert t.ready_at is None
        assert t.case_out_id == case_out.id
        assert case_out.turnover_out.first() == t
        assert self.room.turnovers.first() == t

    def test_open_and_complete_lifecycle(self):
        case_out = self._case()
        t = turnover_svc.open_turnover(self.room, case_out=case_out, by=self.manager)
        assert t.status == RoomTurnover.Status.AGUARDANDO
        assert t.ready_at is None
        assert t.created_by_id == self.manager.id

        done = turnover_svc.complete_turnover(t)
        assert done.status == RoomTurnover.Status.PRONTA
        assert done.ready_at is not None
        done.refresh_from_db()
        assert done.status == RoomTurnover.Status.PRONTA


# ── Enforcement no agendamento (o coração do CS3) ────────────────────────────


class TestTurnoverEnforcement(TurnoverTestBase):
    def test_gap_below_turnover_rejected(self):
        # Caso A 08:00–09:00 na sala (turnover 30).
        self._case(
            operating_room=self.room,
            scheduled_start=_dt(8),
            scheduled_end=_dt(9),
            status=SurgicalCase.Status.AGENDADA,
        )
        # Caso B 09:15–10:00 → gap 15 < 30 → barrado.
        new = self._case()
        with pytest.raises(ValidationError):
            svc.schedule(new, self.room, _dt(9, 15), _dt(10))

    def test_gap_exactly_turnover_ok(self):
        self._case(
            operating_room=self.room,
            scheduled_start=_dt(8),
            scheduled_end=_dt(9),
            status=SurgicalCase.Status.AGENDADA,
        )
        # Caso B 09:30–10:00 → gap exatamente 30 → OK.
        new = self._case()
        out = svc.schedule(new, self.room, _dt(9, 30), _dt(10))
        assert out.scheduled_start == _dt(9, 30)

    def test_gap_below_turnover_before_existing_rejected(self):
        # Turnover é simétrico: um novo caso ANTES de um existente também precisa
        # respeitar o gap. Existente 10:00–11:00; novo 09:00–09:45 → gap 15 < 30.
        self._case(
            operating_room=self.room,
            scheduled_start=_dt(10),
            scheduled_end=_dt(11),
            status=SurgicalCase.Status.AGENDADA,
        )
        new = self._case()
        with pytest.raises(ValidationError):
            svc.schedule(new, self.room, _dt(9), _dt(9, 45))

    def test_other_room_not_restricted(self):
        self._case(
            operating_room=self.room,
            scheduled_start=_dt(8),
            scheduled_end=_dt(9),
            status=SurgicalCase.Status.AGENDADA,
        )
        # Caso B numa OUTRA sala às 09:15 → OK (turnover é por sala).
        new = self._case()
        out = svc.schedule(new, self.room2, _dt(9, 15), _dt(10))
        assert out.operating_room_id == self.room2.id

    def test_overlap_still_rejected(self):
        # Casos que se SOBREPÕEM continuam barrados (não regride o overlap guard).
        self._case(
            operating_room=self.room,
            scheduled_start=_dt(8),
            scheduled_end=_dt(10),
            status=SurgicalCase.Status.AGENDADA,
        )
        new = self._case()
        with pytest.raises(ValidationError):
            svc.schedule(new, self.room, _dt(9), _dt(11))  # overlaps [8,10)

    def test_cancelled_case_does_not_impose_turnover(self):
        self._case(
            operating_room=self.room,
            scheduled_start=_dt(8),
            scheduled_end=_dt(9),
            status=SurgicalCase.Status.CANCELADA,
        )
        # Caso cancelado não bloqueia nem impõe turnover.
        new = self._case()
        out = svc.schedule(new, self.room, _dt(9, 15), _dt(10))
        assert out.scheduled_start == _dt(9, 15)

    def test_reschedule_respects_turnover(self):
        self._case(
            operating_room=self.room,
            scheduled_start=_dt(8),
            scheduled_end=_dt(9),
            status=SurgicalCase.Status.AGENDADA,
        )
        case = self._case(operating_room=self.room, scheduled_start=_dt(12), scheduled_end=_dt(13))
        # Reagendar para 09:15 viola o turnover do caso das 08:00–09:00.
        with pytest.raises(ValidationError):
            svc.reschedule(case, _dt(9, 15), _dt(10))

    def test_schedule_endpoint_turnover_returns_409(self):
        self._case(
            operating_room=self.room,
            scheduled_start=_dt(8),
            scheduled_end=_dt(9),
            status=SurgicalCase.Status.AGENDADA,
        )
        case = self._case()
        resp = self._client(self.scheduler).post(
            f"{BASE}/surgical-cases/{case.id}/schedule/",
            {
                "operating_room": str(self.room.id),
                "scheduled_start": _dt(9, 15).isoformat(),
                "scheduled_end": _dt(10).isoformat(),
            },
            format="json",
        )
        assert resp.status_code == 409, resp.content
        assert "turnover" in resp.data["detail"].lower()


# ── RoomTurnover API ─────────────────────────────────────────────────────────


class TestRoomTurnoverAPI(TurnoverTestBase):
    def test_create_turnover(self):
        case_out = self._case()
        resp = self._client(self.manager).post(
            f"{BASE}/room-turnovers/",
            {
                "operating_room": str(self.room.id),
                "case_out": str(case_out.id),
                "performed_by": str(self.surgeon.id),
            },
            format="json",
        )
        assert resp.status_code == 201, resp.content
        t = RoomTurnover.objects.get(operating_room=self.room)
        assert t.status == RoomTurnover.Status.AGUARDANDO
        # created_by stamped from request.user (never client-set).
        assert t.created_by_id == self.manager.id

    def test_create_requires_manage(self):
        resp = self._client(self.reader).post(
            f"{BASE}/room-turnovers/",
            {"operating_room": str(self.room.id)},
            format="json",
        )
        assert resp.status_code == 403, resp.content

    def test_complete_action(self):
        t = RoomTurnover.objects.create(operating_room=self.room)
        resp = self._client(self.manager).post(
            f"{BASE}/room-turnovers/{t.id}/complete/", {}, format="json"
        )
        assert resp.status_code == 200, resp.content
        assert resp.data["status"] == RoomTurnover.Status.PRONTA
        t.refresh_from_db()
        assert t.ready_at is not None

    def test_reader_can_list_filtered_by_room(self):
        RoomTurnover.objects.create(operating_room=self.room)
        RoomTurnover.objects.create(operating_room=self.room2)
        resp = self._client(self.reader).get(
            f"{BASE}/room-turnovers/?operating_room={self.room.id}"
        )
        assert resp.status_code == 200, resp.content
        assert resp.data["count"] == 1

    def test_no_perm_cannot_read(self):
        RoomTurnover.objects.create(operating_room=self.room)
        resp = self._client(self.nobody).get(f"{BASE}/room-turnovers/")
        assert resp.status_code == 403, resp.content
