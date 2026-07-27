"""
C3 — Centro Cirúrgico intra-op: equipe + tempos (append-only) + checklist OMS.

Covers:
* SurgicalTeamMember CRUD (add/remove) gated surgery.manage; duplicate
  (case, professional, role) rejected.
* record_time service: appends a SurgicalTime AND advances the case status by
  the time event (sala_entrada→em_sala, incisao→em_andamento, sala_saida→
  finalizada); out-of-order / illegal events rejected (ValidationError → 409).
* confirm_checklist service: creates a SurgicalChecklist for a phase once;
  re-confirming the same phase is rejected (→ 409).
* Times & checklists are append-only: the DRF surface is read-only (POST/PATCH/
  DELETE → 405).
* RBAC: surgery.manage to write (team / record-time / checklist), surgery.read
  to read (timeline / list viewsets).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.core.models import Role, User
from apps.emr.models import (
    OperatingRoom,
    Patient,
    Professional,
    SurgicalCase,
    SurgicalChecklist,
    SurgicalTeamMember,
    SurgicalTime,
)
from apps.emr.services import surgery_intraop as intraop
from apps.organization.models import Facility, LegalEntity
from apps.test_utils import TenantTestCase

BASE = "/api/v1"

MANAGE_PERMS = ["surgery.read", "surgery.manage"]
READ_PERMS = ["surgery.read"]


def _dt(hour, minute=0, day=15):
    return datetime(2026, 8, day, hour, minute, tzinfo=UTC)


class IntraOpTestBase(TenantTestCase):
    def setUp(self):
        self.manage_role = Role.objects.create(name="gestor_cc", permissions=MANAGE_PERMS)
        self.read_role = Role.objects.create(name="enf_cc", permissions=READ_PERMS)
        self.none_role = Role.objects.create(name="sem_perm", permissions=[])
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
            user=self.manager,
            council_type="CRM",
            council_number="12345",
            council_state="SP",
        )
        self.anesthetist = Professional.objects.create(
            user=self.reader,
            council_type="CRM",
            council_number="67890",
            council_state="SP",
        )
        self.patient = Patient.objects.create(
            full_name="Maria Operada", birth_date="1980-01-01", gender="F", cpf="52998224725"
        )
        self.room = OperatingRoom.objects.create(facility=self.facility, code="SO-1", name="Sala 1")

    def _case(self, **kw):
        defaults = {"patient": self.patient, "surgeon": self.surgeon}
        defaults.update(kw)
        return SurgicalCase.objects.create(**defaults)

    def _client(self, user):
        c = APIClient()
        c.defaults["SERVER_NAME"] = self.__class__.domain.domain
        c.force_authenticate(user)
        return c


# ── record_time service: append + status advance ──────────────────────────────


class TestRecordTimeService(IntraOpTestBase):
    def test_sala_entrada_advances_confirmada_to_em_sala(self):
        case = self._case(status=SurgicalCase.Status.CONFIRMADA)
        out = intraop.record_time(case, SurgicalTime.Event.SALA_ENTRADA, by=self.manager)
        out.refresh_from_db()
        assert out.status == SurgicalCase.Status.EM_SALA
        assert case.times.count() == 1
        t = case.times.first()
        assert t.event == SurgicalTime.Event.SALA_ENTRADA
        assert t.recorded_by_id == self.manager.id
        assert t.recorded_at is not None

    def test_incisao_advances_em_sala_to_em_andamento(self):
        case = self._case(status=SurgicalCase.Status.EM_SALA)
        out = intraop.record_time(case, SurgicalTime.Event.INCISAO)
        out.refresh_from_db()
        assert out.status == SurgicalCase.Status.EM_ANDAMENTO

    def test_sala_saida_advances_em_andamento_to_finalizada(self):
        case = self._case(status=SurgicalCase.Status.EM_ANDAMENTO)
        out = intraop.record_time(case, SurgicalTime.Event.SALA_SAIDA)
        out.refresh_from_db()
        assert out.status == SurgicalCase.Status.FINALIZADA

    def test_full_happy_path(self):
        case = self._case(status=SurgicalCase.Status.CONFIRMADA)
        intraop.record_time(case, SurgicalTime.Event.SALA_ENTRADA)
        intraop.record_time(case, SurgicalTime.Event.ANESTESIA_INICIO)
        intraop.record_time(case, SurgicalTime.Event.INCISAO)
        intraop.record_time(case, SurgicalTime.Event.FECHAMENTO)
        intraop.record_time(case, SurgicalTime.Event.ANESTESIA_FIM)
        intraop.record_time(case, SurgicalTime.Event.SALA_SAIDA)
        case.refresh_from_db()
        assert case.status == SurgicalCase.Status.FINALIZADA
        assert case.times.count() == 6

    def test_custom_recorded_at_and_notes(self):
        case = self._case(status=SurgicalCase.Status.CONFIRMADA)
        intraop.record_time(case, SurgicalTime.Event.SALA_ENTRADA, at=_dt(8), notes="entrou às 8h")
        t = case.times.first()
        assert t.recorded_at == _dt(8)
        assert t.notes == "entrou às 8h"

    def test_incisao_before_em_sala_rejected(self):
        case = self._case(status=SurgicalCase.Status.CONFIRMADA)
        with pytest.raises(ValidationError):
            intraop.record_time(case, SurgicalTime.Event.INCISAO)

    def test_sala_entrada_on_agendada_rejected(self):
        case = self._case(status=SurgicalCase.Status.AGENDADA)
        with pytest.raises(ValidationError):
            intraop.record_time(case, SurgicalTime.Event.SALA_ENTRADA)

    def test_time_on_cancelada_rejected(self):
        case = self._case(status=SurgicalCase.Status.CANCELADA)
        with pytest.raises(ValidationError):
            intraop.record_time(case, SurgicalTime.Event.SALA_ENTRADA)

    def test_sala_saida_before_incisao_rejected(self):
        case = self._case(status=SurgicalCase.Status.EM_SALA)
        with pytest.raises(ValidationError):
            intraop.record_time(case, SurgicalTime.Event.SALA_SAIDA)

    def test_duplicate_sala_entrada_rejected(self):
        # Second sala_entrada requires confirmada again but case is now em_sala.
        case = self._case(status=SurgicalCase.Status.CONFIRMADA)
        intraop.record_time(case, SurgicalTime.Event.SALA_ENTRADA)
        with pytest.raises(ValidationError):
            intraop.record_time(case, SurgicalTime.Event.SALA_ENTRADA)


# ── confirm_checklist service ─────────────────────────────────────────────────


class TestChecklistService(IntraOpTestBase):
    def test_confirm_creates_phase(self):
        case = self._case(status=SurgicalCase.Status.CONFIRMADA)
        cl = intraop.confirm_checklist(
            case,
            SurgicalChecklist.Phase.SIGN_IN,
            {"identidade_confirmada": True, "sitio_marcado": True},
            by=self.manager,
        )
        assert cl.phase == SurgicalChecklist.Phase.SIGN_IN
        assert cl.items["identidade_confirmada"] is True
        assert cl.confirmed_by_id == self.manager.id
        assert case.checklists.count() == 1

    def test_reconfirm_same_phase_rejected(self):
        case = self._case(status=SurgicalCase.Status.CONFIRMADA)
        intraop.confirm_checklist(case, SurgicalChecklist.Phase.TIME_OUT, {"a": True})
        with pytest.raises(ValidationError):
            intraop.confirm_checklist(case, SurgicalChecklist.Phase.TIME_OUT, {"a": True})

    def test_different_phases_ok(self):
        case = self._case(status=SurgicalCase.Status.CONFIRMADA)
        intraop.confirm_checklist(case, SurgicalChecklist.Phase.SIGN_IN, {"a": True})
        intraop.confirm_checklist(case, SurgicalChecklist.Phase.TIME_OUT, {"b": True})
        intraop.confirm_checklist(case, SurgicalChecklist.Phase.SIGN_OUT, {"c": True})
        assert case.checklists.count() == 3


# ── Team API (writable CRUD) ──────────────────────────────────────────────────


class TestTeamAPI(IntraOpTestBase):
    def test_add_team_member(self):
        case = self._case()
        resp = self._client(self.manager).post(
            f"{BASE}/surgical-team/",
            {
                "case": str(case.id),
                "professional": str(self.surgeon.id),
                "role": SurgicalTeamMember.Role.CIRURGIAO,
            },
            format="json",
        )
        assert resp.status_code == 201, resp.content
        assert case.team.count() == 1

    def test_duplicate_role_rejected(self):
        case = self._case()
        SurgicalTeamMember.objects.create(
            case=case, professional=self.surgeon, role=SurgicalTeamMember.Role.CIRURGIAO
        )
        resp = self._client(self.manager).post(
            f"{BASE}/surgical-team/",
            {
                "case": str(case.id),
                "professional": str(self.surgeon.id),
                "role": SurgicalTeamMember.Role.CIRURGIAO,
            },
            format="json",
        )
        assert resp.status_code == 400, resp.content

    def test_same_professional_different_role_ok(self):
        case = self._case()
        SurgicalTeamMember.objects.create(
            case=case, professional=self.surgeon, role=SurgicalTeamMember.Role.CIRURGIAO
        )
        resp = self._client(self.manager).post(
            f"{BASE}/surgical-team/",
            {
                "case": str(case.id),
                "professional": str(self.surgeon.id),
                "role": SurgicalTeamMember.Role.PRIMEIRO_AUXILIAR,
            },
            format="json",
        )
        assert resp.status_code == 201, resp.content

    def test_remove_team_member(self):
        case = self._case()
        member = SurgicalTeamMember.objects.create(
            case=case, professional=self.surgeon, role=SurgicalTeamMember.Role.CIRURGIAO
        )
        resp = self._client(self.manager).delete(f"{BASE}/surgical-team/{member.id}/")
        assert resp.status_code == 204, resp.content
        assert case.team.count() == 0

    def test_list_filtered_by_case(self):
        case = self._case()
        other = self._case()
        SurgicalTeamMember.objects.create(
            case=case, professional=self.surgeon, role=SurgicalTeamMember.Role.CIRURGIAO
        )
        SurgicalTeamMember.objects.create(
            case=other, professional=self.anesthetist, role=SurgicalTeamMember.Role.ANESTESISTA
        )
        resp = self._client(self.reader).get(f"{BASE}/surgical-team/?case={case.id}")
        assert resp.status_code == 200, resp.content
        assert resp.data["count"] == 1

    def test_add_team_requires_manage(self):
        case = self._case()
        resp = self._client(self.reader).post(
            f"{BASE}/surgical-team/",
            {
                "case": str(case.id),
                "professional": str(self.surgeon.id),
                "role": SurgicalTeamMember.Role.CIRURGIAO,
            },
            format="json",
        )
        assert resp.status_code == 403, resp.content

    def test_read_team_requires_read(self):
        case = self._case()
        resp = self._client(self.nobody).get(f"{BASE}/surgical-team/?case={case.id}")
        assert resp.status_code == 403, resp.content


# ── record-time API ───────────────────────────────────────────────────────────


class TestRecordTimeAPI(IntraOpTestBase):
    def test_record_time_endpoint_advances_status(self):
        case = self._case(status=SurgicalCase.Status.CONFIRMADA)
        resp = self._client(self.manager).post(
            f"{BASE}/surgical-cases/{case.id}/record-time/",
            {"event": SurgicalTime.Event.SALA_ENTRADA},
            format="json",
        )
        assert resp.status_code == 200, resp.content
        assert resp.data["status"] == SurgicalCase.Status.EM_SALA
        case.refresh_from_db()
        assert case.times.count() == 1

    def test_out_of_order_returns_409(self):
        case = self._case(status=SurgicalCase.Status.CONFIRMADA)
        resp = self._client(self.manager).post(
            f"{BASE}/surgical-cases/{case.id}/record-time/",
            {"event": SurgicalTime.Event.INCISAO},
            format="json",
        )
        assert resp.status_code == 409, resp.content
        assert "detail" in resp.data

    def test_record_time_requires_manage(self):
        case = self._case(status=SurgicalCase.Status.CONFIRMADA)
        resp = self._client(self.reader).post(
            f"{BASE}/surgical-cases/{case.id}/record-time/",
            {"event": SurgicalTime.Event.SALA_ENTRADA},
            format="json",
        )
        assert resp.status_code == 403, resp.content


# ── checklist API ─────────────────────────────────────────────────────────────


class TestChecklistAPI(IntraOpTestBase):
    def test_checklist_endpoint_creates_phase(self):
        case = self._case(status=SurgicalCase.Status.CONFIRMADA)
        resp = self._client(self.manager).post(
            f"{BASE}/surgical-cases/{case.id}/checklist/",
            {"phase": SurgicalChecklist.Phase.SIGN_IN, "items": {"id_ok": True}},
            format="json",
        )
        assert resp.status_code == 201, resp.content
        assert resp.data["phase"] == SurgicalChecklist.Phase.SIGN_IN
        assert case.checklists.count() == 1

    def test_reconfirm_phase_returns_409(self):
        case = self._case(status=SurgicalCase.Status.CONFIRMADA)
        SurgicalChecklist.objects.create(
            case=case, phase=SurgicalChecklist.Phase.SIGN_IN, items={"a": True}
        )
        resp = self._client(self.manager).post(
            f"{BASE}/surgical-cases/{case.id}/checklist/",
            {"phase": SurgicalChecklist.Phase.SIGN_IN, "items": {"a": True}},
            format="json",
        )
        assert resp.status_code == 409, resp.content

    def test_checklist_requires_manage(self):
        case = self._case(status=SurgicalCase.Status.CONFIRMADA)
        resp = self._client(self.reader).post(
            f"{BASE}/surgical-cases/{case.id}/checklist/",
            {"phase": SurgicalChecklist.Phase.SIGN_IN, "items": {"a": True}},
            format="json",
        )
        assert resp.status_code == 403, resp.content


# ── timeline + append-only read viewsets ──────────────────────────────────────


class TestTimelineAndReadOnly(IntraOpTestBase):
    def test_timeline_returns_times_checklists_team(self):
        case = self._case(status=SurgicalCase.Status.CONFIRMADA)
        intraop.record_time(case, SurgicalTime.Event.SALA_ENTRADA)
        intraop.confirm_checklist(case, SurgicalChecklist.Phase.SIGN_IN, {"a": True})
        SurgicalTeamMember.objects.create(
            case=case, professional=self.surgeon, role=SurgicalTeamMember.Role.CIRURGIAO
        )
        resp = self._client(self.reader).get(f"{BASE}/surgical-cases/{case.id}/timeline/")
        assert resp.status_code == 200, resp.content
        assert len(resp.data["times"]) == 1
        assert len(resp.data["checklists"]) == 1
        assert len(resp.data["team"]) == 1

    def test_timeline_requires_read(self):
        case = self._case()
        resp = self._client(self.nobody).get(f"{BASE}/surgical-cases/{case.id}/timeline/")
        assert resp.status_code == 403, resp.content

    def test_times_viewset_is_read_only(self):
        case = self._case(status=SurgicalCase.Status.CONFIRMADA)
        intraop.record_time(case, SurgicalTime.Event.SALA_ENTRADA)
        c = self._client(self.manager)
        # list ok
        listing = c.get(f"{BASE}/surgical-times/?case={case.id}")
        assert listing.status_code == 200, listing.content
        assert listing.data["count"] == 1
        # POST rejected (append-only → recorded via the action)
        post = c.post(
            f"{BASE}/surgical-times/",
            {"case": str(case.id), "event": SurgicalTime.Event.INCISAO},
            format="json",
        )
        assert post.status_code == 405, post.content

    def test_checklists_viewset_is_read_only(self):
        case = self._case(status=SurgicalCase.Status.CONFIRMADA)
        SurgicalChecklist.objects.create(
            case=case, phase=SurgicalChecklist.Phase.SIGN_IN, items={"a": True}
        )
        c = self._client(self.manager)
        listing = c.get(f"{BASE}/surgical-checklists/?case={case.id}")
        assert listing.status_code == 200, listing.content
        assert listing.data["count"] == 1
        post = c.post(
            f"{BASE}/surgical-checklists/",
            {"case": str(case.id), "phase": SurgicalChecklist.Phase.SIGN_OUT, "items": {}},
            format="json",
        )
        assert post.status_code == 405, post.content
