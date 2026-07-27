"""
C1 — Centro Cirúrgico structure DRF API: CRUD, filtering, the
surgery.read / surgery.manage permission split, and cross-schema TUSS protection.

A gestor cirúrgico carries surgery.read + surgery.manage (manages the structure);
a reader carries only surgery.read (list/retrieve) and is 403 on any write; a
no-perm user is 403 everywhere. Attaching a SurgicalProcedure resolves the
cross-schema FK to core.TUSSCode (an unknown pk → 400). A TUSSCode referenced by
a SurgicalProcedure cannot be hard-deleted — mirroring
test_encounter_procedure.py::test_delete_blocked_when_referenced_by_procedure.
"""

from django.db import transaction
from django.db.models.deletion import ProtectedError
from rest_framework.test import APIClient

from apps.core.models import Role, TUSSCode, User
from apps.emr.models import (
    OperatingRoom,
    Patient,
    Professional,
    SurgicalCase,
    SurgicalProcedure,
)
from apps.organization.models import Facility, LegalEntity
from apps.test_utils import TenantTestCase

BASE = "/api/v1"

MANAGE_PERMS = ["surgery.read", "surgery.manage"]
READ_PERMS = ["surgery.read"]


def _make_tuss(code="30602246", active=True):
    return TUSSCode.objects.create(
        code=code,
        description="Colecistectomia videolaparoscópica",
        group="procedimento",
        version="2024-01",
        active=active,
    )


class SurgeryAPITestBase(TenantTestCase):
    def setUp(self):
        self.manage_role = Role.objects.create(name="gestor_cc", permissions=MANAGE_PERMS)
        self.read_role = Role.objects.create(name="enf_cc", permissions=READ_PERMS)
        self.none_role = Role.objects.create(name="sem_perm", permissions=[])
        self.manager = User.objects.create_user(
            email="cir@t.com", password="pw", role=self.manage_role
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
        self.patient = Patient.objects.create(
            full_name="Maria Operada", birth_date="1980-01-01", gender="F", cpf="52998224725"
        )
        self.room = OperatingRoom.objects.create(facility=self.facility, code="SO-1", name="Sala 1")

    def _client(self, user):
        c = APIClient()
        c.defaults["SERVER_NAME"] = self.__class__.domain.domain
        c.force_authenticate(user)
        return c

    @staticmethod
    def _rows(resp):
        return resp.data["results"] if "results" in resp.data else resp.data


class TestOperatingRoomAPI(SurgeryAPITestBase):
    def test_manager_can_create_room(self):
        resp = self._client(self.manager).post(
            f"{BASE}/operating-rooms/",
            {"facility": str(self.facility.id), "code": "SO-2", "name": "Sala 2"},
            format="json",
        )
        assert resp.status_code == 201, resp.content
        assert OperatingRoom.objects.filter(code="SO-2").exists()

    def test_reader_can_list_but_not_create(self):
        reader = self._client(self.reader)
        list_resp = reader.get(f"{BASE}/operating-rooms/")
        assert list_resp.status_code == 200
        assert len(self._rows(list_resp)) >= 1
        write_resp = reader.post(
            f"{BASE}/operating-rooms/",
            {"facility": str(self.facility.id), "code": "SO-3", "name": "Sala 3"},
            format="json",
        )
        assert write_resp.status_code == 403, write_resp.content

    def test_no_perm_forbidden(self):
        nobody = self._client(self.nobody)
        assert nobody.get(f"{BASE}/operating-rooms/").status_code == 403
        assert (
            nobody.post(
                f"{BASE}/operating-rooms/",
                {"facility": str(self.facility.id), "code": "X", "name": "X"},
                format="json",
            ).status_code
            == 403
        )

    def test_filter_by_facility(self):
        other_fac = Facility.objects.create(code="FAC2", name="Anexo", legal_entity=self.legal)
        OperatingRoom.objects.create(facility=other_fac, code="SO-Z", name="Sala Z")
        resp = self._client(self.reader).get(f"{BASE}/operating-rooms/?facility={self.facility.id}")
        assert resp.status_code == 200
        assert len(self._rows(resp)) == 1


class TestSurgicalCaseAPI(SurgeryAPITestBase):
    def test_manager_creates_case_defaults_agendada_and_created_by_set(self):
        resp = self._client(self.manager).post(
            f"{BASE}/surgical-cases/",
            {
                "patient": str(self.patient.id),
                "surgeon": str(self.surgeon.id),
                "operating_room": str(self.room.id),
            },
            format="json",
        )
        assert resp.status_code == 201, resp.content
        case = SurgicalCase.objects.get(pk=resp.data["id"])
        assert case.status == SurgicalCase.Status.AGENDADA  # default
        assert case.priority == SurgicalCase.Priority.ELETIVA  # default
        assert case.scheduled_start is None  # C2 sets it
        assert case.created_by_id == self.manager.id  # server-set

    def test_reader_cannot_create_case(self):
        resp = self._client(self.reader).post(
            f"{BASE}/surgical-cases/",
            {"patient": str(self.patient.id), "surgeon": str(self.surgeon.id)},
            format="json",
        )
        assert resp.status_code == 403, resp.content

    def test_filter_cases(self):
        c1 = SurgicalCase.objects.create(
            patient=self.patient, surgeon=self.surgeon, operating_room=self.room
        )
        other_patient = Patient.objects.create(
            full_name="Outro", birth_date="1990-02-02", gender="M", cpf="11144477735"
        )
        SurgicalCase.objects.create(
            patient=other_patient, surgeon=self.surgeon, status=SurgicalCase.Status.CANCELADA
        )
        c = self._client(self.reader)
        by_patient = c.get(f"{BASE}/surgical-cases/?patient={self.patient.id}")
        assert by_patient.status_code == 200
        assert {r["id"] for r in self._rows(by_patient)} == {str(c1.id)}
        by_status = c.get(f"{BASE}/surgical-cases/?status=cancelada")
        assert len(self._rows(by_status)) == 1
        by_room = c.get(f"{BASE}/surgical-cases/?operating_room={self.room.id}")
        assert {r["id"] for r in self._rows(by_room)} == {str(c1.id)}
        by_surgeon = c.get(f"{BASE}/surgical-cases/?surgeon={self.surgeon.id}")
        assert len(self._rows(by_surgeon)) == 2


class TestSurgicalProcedureAPI(SurgeryAPITestBase):
    def setUp(self):
        super().setUp()
        self.tuss = _make_tuss()
        self.case = SurgicalCase.objects.create(
            patient=self.patient, surgeon=self.surgeon, operating_room=self.room
        )

    def test_attach_procedure_resolves_tuss_fk(self):
        resp = self._client(self.manager).post(
            f"{BASE}/surgical-procedures/",
            {
                "case": str(self.case.id),
                "tuss_code": str(self.tuss.id),
                "quantity": 1,
                "laterality": "direita",
            },
            format="json",
        )
        assert resp.status_code == 201, resp.content
        proc = SurgicalProcedure.objects.get(pk=resp.data["id"])
        assert proc.tuss_code_id == self.tuss.id
        assert resp.data["tuss_code_value"] == self.tuss.code

    def test_attach_procedure_unknown_tuss_rejected(self):
        import uuid as _uuid

        resp = self._client(self.manager).post(
            f"{BASE}/surgical-procedures/",
            {"case": str(self.case.id), "tuss_code": str(_uuid.uuid4())},
            format="json",
        )
        assert resp.status_code == 400, resp.content
        assert "tuss_code" in resp.data

    def test_reader_cannot_create_procedure(self):
        resp = self._client(self.reader).post(
            f"{BASE}/surgical-procedures/",
            {"case": str(self.case.id), "tuss_code": str(self.tuss.id)},
            format="json",
        )
        assert resp.status_code == 403, resp.content

    def test_filter_procedures_by_case(self):
        SurgicalProcedure.objects.create(case=self.case, tuss_code=self.tuss)
        other_case = SurgicalCase.objects.create(patient=self.patient, surgeon=self.surgeon)
        SurgicalProcedure.objects.create(case=other_case, tuss_code=self.tuss)
        resp = self._client(self.reader).get(f"{BASE}/surgical-procedures/?case={self.case.id}")
        assert resp.status_code == 200
        assert len(self._rows(resp)) == 1


class TestSurgicalProcedureTUSSProtection(SurgeryAPITestBase):
    """A TUSSCode referenced by a SurgicalProcedure cannot be hard-deleted — the
    cross-schema protect_tuss_code_deletion pre_delete signal blocks it."""

    def setUp(self):
        super().setUp()
        self.tuss = _make_tuss(code="30602300")
        self.case = SurgicalCase.objects.create(patient=self.patient, surgeon=self.surgeon)

    def test_delete_blocked_when_referenced_by_surgical_procedure(self):
        SurgicalProcedure.objects.create(case=self.case, tuss_code=self.tuss)
        # Wrap in a savepoint: the pre_delete signal raises mid-delete(), marking
        # the transaction for rollback; the inner atomic() keeps the assertion query valid.
        with self.assertRaises(ProtectedError) as ctx, transaction.atomic():
            self.tuss.delete()
        assert "SurgicalProcedure" in str(ctx.exception)
        assert TUSSCode.objects.filter(pk=self.tuss.pk).exists()

    def test_delete_allowed_when_not_referenced(self):
        unused = _make_tuss(code="30602399")
        unused.delete()
        assert not TUSSCode.objects.filter(pk=unused.pk).exists()
