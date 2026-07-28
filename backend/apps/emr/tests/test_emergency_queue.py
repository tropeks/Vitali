"""
E3 — Fila por gravidade + desfecho (com internação → ADT) tests.

Covers, strict-TDD, the E3 surface built on the E2 boletim + Manchester
classification:

* queue ordering: unclassified first, then acuity rank (vermelho<amarelo<verde),
  then arrival_at (oldest first); encerrado excluded.
* overdue flag: classified AND waited_minutes > target_minutes (now controlled).
* board: counts by acuity level + overdue count + unclassified/total.
* next_patient: skips aguardando (triage ≠ attendance) → first classificado.
* start_attendance: classificado → em_atendimento; illegal from other states → 409.
* close: sets disposition + encerrado; illegal transition → 409.
* internação bridge: close(disposition=internacao)+livre bed calls adt.admit
  (bed→ocupado, Admission created, boletim.admission set); without bed →
  admission null; occupied bed → 409.
* RBAC: board=emergency.read, start/close=emergency.manage, no-perm 403.
"""

from datetime import timedelta

from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.manchester_catalog_models import (
    ACUITY_RANK,
    ManchesterDiscriminator,
    ManchesterFlowchart,
    acuity_rank,
)
from apps.core.models import BedType, Role, User
from apps.emr.emergency_models import EmergencyEncounter
from apps.emr.models import Admission, Bed, InpatientUnit, Patient, Professional, Room
from apps.emr.services import emergency_classify as classify_service
from apps.emr.services import emergency_lifecycle as lifecycle
from apps.emr.services import emergency_queue as queue_service
from apps.organization.models import Facility, LegalEntity
from apps.test_utils import TenantTestCase

BASE = "/api/v1"

MANAGE_PERMS = ["emergency.read", "emergency.manage"]
READ_PERMS = ["emergency.read"]


class QueueTestBase(TenantTestCase):
    def setUp(self):
        self.manage_role = Role.objects.create(name="ps_manage", permissions=MANAGE_PERMS)
        self.read_role = Role.objects.create(name="ps_read", permissions=READ_PERMS)
        self.none_role = Role.objects.create(name="ps_none", permissions=[])

        self.manager = User.objects.create_user(
            email="mgr@t.com", password="pw", role=self.manage_role
        )
        self.reader = User.objects.create_user(
            email="rdr@t.com", password="pw", role=self.read_role
        )
        self.nobody = User.objects.create_user(
            email="none@t.com", password="pw", role=self.none_role
        )

        self.prof = Professional.objects.create(
            user=self.manager, council_type="CRM", council_number="12345", council_state="SP"
        )
        self.patient = Patient.objects.create(
            full_name="José da Urgência", birth_date="1975-05-05", gender="M", cpf="52998224725"
        )

        # SHARED Manchester catalog fixture (one flowchart, one discriminator per level).
        self.flowchart = ManchesterFlowchart.objects.create(code="FL01", display="Dor torácica")
        self.disc = {
            level: ManchesterDiscriminator.objects.create(
                flowchart=self.flowchart, code=f"D-{level}", name=level, acuity_level=level
            )
            for level in ("vermelho", "laranja", "amarelo", "verde", "azul")
        }

        # ADT structure for the internação bridge.
        self.legal = LegalEntity.objects.create(code="LE1", name="Hospital SA")
        self.facility = Facility.objects.create(
            code="FAC1", name="Hospital Central", legal_entity=self.legal
        )
        self.bed_type = BedType.objects.create(
            code="74", display="UTI adulto", category="Complementar"
        )
        self.unit = InpatientUnit.objects.create(facility=self.facility, name="Ala A", code="ALA-A")
        self.room = Room.objects.create(unit=self.unit, name="101")
        self.bed = Bed.objects.create(
            room=self.room, unit=self.unit, identifier="101-A", bed_type=self.bed_type
        )

    def _client(self, user):
        c = APIClient()
        c.defaults["SERVER_NAME"] = self.__class__.domain.domain
        c.force_authenticate(user)
        return c

    def _patient(self, cpf, name="Paciente"):
        return Patient.objects.create(full_name=name, birth_date="1980-01-01", gender="M", cpf=cpf)

    def _boletim(self, *, patient=None, arrival_at=None, **kw):
        defaults = {
            "patient": patient or self.patient,
            "mode_of_arrival": "ambulante",
            "chief_complaint": "Queixa",
            "created_by": self.manager,
        }
        if arrival_at is not None:
            defaults["arrival_at"] = arrival_at
        defaults.update(kw)
        return EmergencyEncounter.objects.create(**defaults)

    def _classify(self, boletim, level):
        return classify_service.classify(boletim, self.disc[level], by=self.manager)


# ─── ACUITY_RANK ──────────────────────────────────────────────────────────────


class TestAcuityRank(QueueTestBase):
    def test_rank_orders_vermelho_first_azul_last(self):
        assert ACUITY_RANK["vermelho"] < ACUITY_RANK["laranja"] < ACUITY_RANK["amarelo"]
        assert ACUITY_RANK["amarelo"] < ACUITY_RANK["verde"] < ACUITY_RANK["azul"]
        assert acuity_rank("vermelho") == 1
        assert acuity_rank("azul") == 5


# ─── queue ordering ───────────────────────────────────────────────────────────


class TestQueueOrdering(QueueTestBase):
    def test_unclassified_first_then_acuity_then_arrival(self):
        now = timezone.now()
        # An unclassified boletim that arrived LATE — must still head the queue.
        unclassified = self._boletim(
            patient=self._patient("15350946056", "Sem triagem"),
            arrival_at=now - timedelta(minutes=1),
        )
        # verde arrived first, amarelo second, vermelho last — acuity must win over arrival.
        b_verde = self._boletim(
            patient=self._patient("11144477735", "Verde"), arrival_at=now - timedelta(minutes=90)
        )
        self._classify(b_verde, "verde")
        b_amarelo = self._boletim(
            patient=self._patient("39053344705", "Amarelo"), arrival_at=now - timedelta(minutes=60)
        )
        self._classify(b_amarelo, "amarelo")
        b_vermelho = self._boletim(
            patient=self._patient("48374483733", "Vermelho"), arrival_at=now - timedelta(minutes=5)
        )
        self._classify(b_vermelho, "vermelho")

        rows = queue_service.queue(now=now)
        order = [r["boletim_id"] for r in rows]
        assert order == [unclassified.id, b_vermelho.id, b_amarelo.id, b_verde.id]

    def test_two_same_acuity_ordered_by_arrival_oldest_first(self):
        now = timezone.now()
        older = self._boletim(
            patient=self._patient("11144477735", "A"), arrival_at=now - timedelta(minutes=40)
        )
        self._classify(older, "laranja")
        newer = self._boletim(
            patient=self._patient("39053344705", "B"), arrival_at=now - timedelta(minutes=10)
        )
        self._classify(newer, "laranja")
        rows = queue_service.queue(now=now)
        assert [r["boletim_id"] for r in rows] == [older.id, newer.id]

    def test_encerrado_excluded_from_queue(self):
        active = self._boletim()
        self._classify(active, "amarelo")
        closed = self._boletim(patient=self._patient("15350946056"))
        self._classify(closed, "vermelho")
        lifecycle.close(closed, disposition="alta")
        rows = queue_service.queue()
        ids = [r["boletim_id"] for r in rows]
        assert active.id in ids
        assert closed.id not in ids


# ─── overdue ──────────────────────────────────────────────────────────────────


class TestOverdue(QueueTestBase):
    def test_overdue_true_when_waited_exceeds_target(self):
        now = timezone.now()
        # amarelo target = 60 min; arrived 90 min ago → overdue.
        b = self._boletim(arrival_at=now - timedelta(minutes=90))
        self._classify(b, "amarelo")
        row = queue_service.queue(now=now)[0]
        assert row["target_minutes"] == 60
        assert row["waited_minutes"] == 90
        assert row["overdue"] is True

    def test_not_overdue_within_target(self):
        now = timezone.now()
        b = self._boletim(arrival_at=now - timedelta(minutes=20))
        self._classify(b, "amarelo")
        row = queue_service.queue(now=now)[0]
        assert row["overdue"] is False

    def test_unclassified_never_overdue(self):
        now = timezone.now()
        self._boletim(arrival_at=now - timedelta(minutes=500))
        row = queue_service.queue(now=now)[0]
        assert row["acuity_level"] is None
        assert row["target_minutes"] is None
        assert row["overdue"] is False


# ─── board + next_patient ─────────────────────────────────────────────────────


class TestBoardAndNext(QueueTestBase):
    def test_board_counts_by_acuity_and_overdue(self):
        now = timezone.now()
        b1 = self._boletim(
            patient=self._patient("11144477735"), arrival_at=now - timedelta(minutes=90)
        )
        self._classify(b1, "amarelo")  # 90>60 → overdue
        b2 = self._boletim(
            patient=self._patient("39053344705"), arrival_at=now - timedelta(minutes=1)
        )
        self._classify(b2, "amarelo")  # not overdue
        b3 = self._boletim(
            patient=self._patient("48374483733"), arrival_at=now - timedelta(minutes=1)
        )
        self._classify(b3, "vermelho")
        self._boletim(patient=self._patient("15350946056"))  # unclassified

        data = queue_service.board()
        assert data["counts"]["amarelo"] == 2
        assert data["counts"]["vermelho"] == 1
        assert data["counts"]["azul"] == 0
        assert data["unclassified"] == 1
        assert data["total"] == 4
        # overdue only computable with runtime now; b1 arrived 90 min ago → overdue.
        assert data["overdue"] >= 1

    def test_next_patient_skips_unclassified_returns_top_classificado(self):
        self._boletim(patient=self._patient("15350946056"))  # unclassified — skipped
        b_vermelho = self._boletim(patient=self._patient("48374483733"))
        self._classify(b_vermelho, "vermelho")
        nxt = queue_service.next_patient()
        assert nxt is not None
        assert nxt["boletim_id"] == b_vermelho.id

    def test_next_patient_none_when_only_unclassified(self):
        self._boletim()
        assert queue_service.next_patient() is None


# ─── start_attendance ─────────────────────────────────────────────────────────


class TestStartAttendance(QueueTestBase):
    def test_classificado_to_em_atendimento(self):
        b = self._boletim()
        self._classify(b, "laranja")
        out = lifecycle.start_attendance(b, professional=self.prof, actor=self.manager)
        assert out.status == EmergencyEncounter.Status.EM_ATENDIMENTO
        b.refresh_from_db()
        assert b.status == EmergencyEncounter.Status.EM_ATENDIMENTO

    def test_illegal_from_aguardando_raises(self):
        b = self._boletim()  # aguardando_classificacao
        try:
            lifecycle.start_attendance(b)
            raise AssertionError("expected ValidationError")
        except DjangoValidationError:
            pass
        b.refresh_from_db()
        assert b.status == EmergencyEncounter.Status.AGUARDANDO_CLASSIFICACAO


# ─── close + disposition ──────────────────────────────────────────────────────


class TestClose(QueueTestBase):
    def test_close_sets_disposition_and_encerrado(self):
        b = self._boletim()
        self._classify(b, "verde")
        lifecycle.start_attendance(b)
        out = lifecycle.close(b, disposition="alta", actor=self.manager)
        assert out.status == EmergencyEncounter.Status.ENCERRADO
        assert out.disposition == "alta"
        assert out.admission_id is None

    def test_close_allowed_from_classificado(self):
        b = self._boletim()
        self._classify(b, "azul")
        out = lifecycle.close(b, disposition="evasao")
        assert out.status == EmergencyEncounter.Status.ENCERRADO
        assert out.disposition == "evasao"

    def test_close_illegal_from_encerrado_raises(self):
        b = self._boletim()
        self._classify(b, "verde")
        lifecycle.close(b, disposition="alta")
        try:
            lifecycle.close(b, disposition="alta")
            raise AssertionError("expected ValidationError")
        except DjangoValidationError:
            pass


# ─── internação bridge ────────────────────────────────────────────────────────


class TestInternacaoBridge(QueueTestBase):
    def test_close_internacao_with_bed_calls_adt_admit(self):
        b = self._boletim()
        self._classify(b, "vermelho")
        lifecycle.start_attendance(b)
        out = lifecycle.close(
            b,
            disposition="internacao",
            bed=self.bed,
            admitting_professional=self.prof,
            attending_professional=self.prof,
            actor=self.manager,
        )
        assert out.status == EmergencyEncounter.Status.ENCERRADO
        assert out.disposition == "internacao"
        assert out.admission_id is not None
        admission = Admission.objects.get(pk=out.admission_id)
        assert admission.status == Admission.Status.ADMITTED
        assert admission.current_bed_id == self.bed.id
        assert admission.admission_source == Admission.AdmissionSource.EMERGENCIA
        self.bed.refresh_from_db()
        assert self.bed.status == Bed.Status.OCUPADO

    def test_close_internacao_without_bed_leaves_admission_null(self):
        b = self._boletim()
        self._classify(b, "laranja")
        out = lifecycle.close(b, disposition="internacao")
        assert out.status == EmergencyEncounter.Status.ENCERRADO
        assert out.disposition == "internacao"
        assert out.admission_id is None

    def test_close_internacao_occupied_bed_raises(self):
        # Pre-occupy the bed.
        from apps.emr.services import adt as adt_service

        adt_service.admit(
            patient=self._patient("15350946056"),
            bed=self.bed,
            admitting_professional=self.prof,
            attending_professional=self.prof,
        )
        b = self._boletim()
        self._classify(b, "vermelho")
        try:
            lifecycle.close(
                b,
                disposition="internacao",
                bed=self.bed,
                admitting_professional=self.prof,
                attending_professional=self.prof,
            )
            raise AssertionError("expected ValidationError on occupied bed")
        except DjangoValidationError:
            pass
        b.refresh_from_db()
        # close rolled back — boletim not encerrado.
        assert b.status == EmergencyEncounter.Status.CLASSIFICADO


# ─── API + RBAC ───────────────────────────────────────────────────────────────


class TestQueueAPI(QueueTestBase):
    def test_board_endpoint_read_permission(self):
        b = self._boletim()
        self._classify(b, "vermelho")
        resp = self._client(self.reader).get(f"{BASE}/emergency-encounters/board/")
        assert resp.status_code == 200, resp.content
        assert "queue" in resp.data
        assert "counts" in resp.data
        assert "overdue" in resp.data
        assert resp.data["queue"][0]["patient"]["id"] == str(self.patient.id)
        assert resp.data["queue"][0]["acuity_level"] == "vermelho"

    def test_board_forbidden_without_permission(self):
        resp = self._client(self.nobody).get(f"{BASE}/emergency-encounters/board/")
        assert resp.status_code == 403, resp.content

    def test_start_attendance_endpoint_requires_manage(self):
        b = self._boletim()
        self._classify(b, "laranja")
        # reader (emergency.read only) → 403
        forbidden = self._client(self.reader).post(
            f"{BASE}/emergency-encounters/{b.pk}/start-attendance/", {}, format="json"
        )
        assert forbidden.status_code == 403, forbidden.content
        ok = self._client(self.manager).post(
            f"{BASE}/emergency-encounters/{b.pk}/start-attendance/", {}, format="json"
        )
        assert ok.status_code == 200, ok.content
        b.refresh_from_db()
        assert b.status == EmergencyEncounter.Status.EM_ATENDIMENTO

    def test_start_attendance_illegal_transition_409(self):
        b = self._boletim()  # aguardando
        resp = self._client(self.manager).post(
            f"{BASE}/emergency-encounters/{b.pk}/start-attendance/", {}, format="json"
        )
        assert resp.status_code == 409, resp.content

    def test_close_endpoint_sets_disposition(self):
        b = self._boletim()
        self._classify(b, "verde")
        resp = self._client(self.manager).post(
            f"{BASE}/emergency-encounters/{b.pk}/close/",
            {"disposition": "alta"},
            format="json",
        )
        assert resp.status_code == 200, resp.content
        b.refresh_from_db()
        assert b.status == EmergencyEncounter.Status.ENCERRADO
        assert b.disposition == "alta"

    def test_close_reader_forbidden(self):
        b = self._boletim()
        self._classify(b, "verde")
        resp = self._client(self.reader).post(
            f"{BASE}/emergency-encounters/{b.pk}/close/",
            {"disposition": "alta"},
            format="json",
        )
        assert resp.status_code == 403, resp.content

    def test_close_internacao_with_bed_endpoint_admits(self):
        b = self._boletim()
        self._classify(b, "vermelho")
        resp = self._client(self.manager).post(
            f"{BASE}/emergency-encounters/{b.pk}/close/",
            {
                "disposition": "internacao",
                "bed": str(self.bed.id),
                "admitting_professional": str(self.prof.id),
                "attending_professional": str(self.prof.id),
            },
            format="json",
        )
        assert resp.status_code == 200, resp.content
        b.refresh_from_db()
        assert b.admission_id is not None
        self.bed.refresh_from_db()
        assert self.bed.status == Bed.Status.OCUPADO

    def test_close_internacao_occupied_bed_409(self):
        from apps.emr.services import adt as adt_service

        adt_service.admit(
            patient=self._patient("15350946056"),
            bed=self.bed,
            admitting_professional=self.prof,
            attending_professional=self.prof,
        )
        b = self._boletim()
        self._classify(b, "vermelho")
        resp = self._client(self.manager).post(
            f"{BASE}/emergency-encounters/{b.pk}/close/",
            {
                "disposition": "internacao",
                "bed": str(self.bed.id),
                "admitting_professional": str(self.prof.id),
                "attending_professional": str(self.prof.id),
            },
            format="json",
        )
        assert resp.status_code == 409, resp.content
