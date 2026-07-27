"""
L1 — ADT/Leitos bed-structure DRF API: CRUD, filtering, and the
beds.read / beds.manage permission split.

A gestor de leitos carries beds.read + beds.manage (manages the structure); a
reader carries only beds.read (list/retrieve) and is 403 on any write; a no-perm
user is 403 everywhere. The Bed ``bed_type_code`` writable accessor resolves a
governed FK, or marks the row unmatched on an unknown code — mirroring
test_sae_api.py::test_create_diagnosis_by_nanda_code_resolves_fk.
"""

from rest_framework.test import APIClient

from apps.core.models import BedType, Role, User
from apps.emr.models import Bed, InpatientUnit, Room
from apps.organization.models import Facility, LegalEntity
from apps.test_utils import TenantTestCase

BASE = "/api/v1"

MANAGE_PERMS = ["beds.read", "beds.manage"]
READ_PERMS = ["beds.read"]


class BedsAPITestBase(TenantTestCase):
    def setUp(self):
        self.manage_role = Role.objects.create(name="gestor_leitos", permissions=MANAGE_PERMS)
        self.read_role = Role.objects.create(name="leitor_leitos", permissions=READ_PERMS)
        self.none_role = Role.objects.create(name="sem_perm", permissions=[])
        self.manager = User.objects.create_user(
            email="nir@t.com", password="pw", role=self.manage_role
        )
        self.reader = User.objects.create_user(
            email="enf@t.com", password="pw", role=self.read_role
        )
        self.nobody = User.objects.create_user(
            email="none@t.com", password="pw", role=self.none_role
        )

        self.legal = LegalEntity.objects.create(code="LE1", name="Hospital SA")
        self.facility = Facility.objects.create(
            code="FAC1", name="Hospital Central", legal_entity=self.legal
        )
        self.bed_type = BedType.objects.create(
            code="74", display="UTI adulto tipo II", category="Complementar"
        )
        self.unit = InpatientUnit.objects.create(facility=self.facility, name="Ala A", code="ALA-A")
        self.room = Room.objects.create(unit=self.unit, name="101")

    def _client(self, user):
        c = APIClient()
        c.defaults["SERVER_NAME"] = self.__class__.domain.domain
        c.force_authenticate(user)
        return c

    @staticmethod
    def _rows(resp):
        return resp.data["results"] if "results" in resp.data else resp.data


class TestInpatientUnitAPI(BedsAPITestBase):
    def test_manager_can_create_unit(self):
        resp = self._client(self.manager).post(
            f"{BASE}/inpatient-units/",
            {"facility": str(self.facility.id), "name": "Ala B", "code": "ALA-B"},
            format="json",
        )
        assert resp.status_code == 201, resp.content
        assert InpatientUnit.objects.filter(code="ALA-B").exists()

    def test_reader_can_list_but_not_create(self):
        reader = self._client(self.reader)
        list_resp = reader.get(f"{BASE}/inpatient-units/")
        assert list_resp.status_code == 200
        assert len(self._rows(list_resp)) >= 1
        write_resp = reader.post(
            f"{BASE}/inpatient-units/",
            {"facility": str(self.facility.id), "name": "Ala C", "code": "ALA-C"},
            format="json",
        )
        assert write_resp.status_code == 403, write_resp.content

    def test_no_perm_forbidden(self):
        nobody = self._client(self.nobody)
        assert nobody.get(f"{BASE}/inpatient-units/").status_code == 403
        assert (
            nobody.post(
                f"{BASE}/inpatient-units/",
                {"facility": str(self.facility.id), "name": "X", "code": "X"},
                format="json",
            ).status_code
            == 403
        )

    def test_filter_by_facility(self):
        other_fac = Facility.objects.create(code="FAC2", name="Anexo", legal_entity=self.legal)
        InpatientUnit.objects.create(facility=other_fac, name="Ala Z", code="ALA-Z")
        resp = self._client(self.reader).get(f"{BASE}/inpatient-units/?facility={self.facility.id}")
        assert resp.status_code == 200
        assert len(self._rows(resp)) == 1


class TestRoomAPI(BedsAPITestBase):
    def test_manager_creates_room(self):
        resp = self._client(self.manager).post(
            f"{BASE}/rooms/",
            {"unit": str(self.unit.id), "name": "102", "isolation": True},
            format="json",
        )
        assert resp.status_code == 201, resp.content
        assert resp.data["isolation"] is True

    def test_filter_rooms_by_unit(self):
        resp = self._client(self.reader).get(f"{BASE}/rooms/?unit={self.unit.id}")
        assert resp.status_code == 200
        assert len(self._rows(resp)) == 1


class TestBedAPI(BedsAPITestBase):
    def test_manager_creates_bed_default_status_livre_and_unit_derived(self):
        resp = self._client(self.manager).post(
            f"{BASE}/beds/",
            {"room": str(self.room.id), "identifier": "101-A", "bed_type": self.bed_type.pk},
            format="json",
        )
        assert resp.status_code == 201, resp.content
        bed = Bed.objects.get(pk=resp.data["id"])
        assert bed.status == Bed.Status.LIVRE  # default
        assert bed.unit_id == self.unit.id  # derived from room
        assert bed.bed_type_id == self.bed_type.pk
        assert resp.data["bed_type_code"] == "74"

    def test_create_bed_by_bed_type_code_resolves_fk(self):
        # The terminology picker exposes only code/display (no catalog PK), so the
        # workspace posts bed_type_code. The writable *_code accessor must resolve
        # it to the governed FK — not silently drop the link.
        resp = self._client(self.manager).post(
            f"{BASE}/beds/",
            {"room": str(self.room.id), "identifier": "101-B", "bed_type_code": "74"},
            format="json",
        )
        assert resp.status_code == 201, resp.content
        bed = Bed.objects.get(pk=resp.data["id"])
        assert bed.bed_type_id == self.bed_type.pk
        assert bed.bed_type_unmatched is False
        assert resp.data["bed_type_code"] == "74"

    def test_create_bed_by_unknown_code_marks_unmatched(self):
        resp = self._client(self.manager).post(
            f"{BASE}/beds/",
            {"room": str(self.room.id), "identifier": "101-C", "bed_type_code": "ZZZ"},
            format="json",
        )
        assert resp.status_code == 201, resp.content
        bed = Bed.objects.get(pk=resp.data["id"])
        assert bed.bed_type_id is None
        assert bed.bed_type_unmatched is True
        assert bed.legacy_bed_type_text == "ZZZ"

    def test_status_transition_via_update(self):
        bed = Bed.objects.create(
            room=self.room, unit=self.unit, identifier="101-D", bed_type=self.bed_type
        )
        resp = self._client(self.manager).patch(
            f"{BASE}/beds/{bed.id}/",
            {"status": Bed.Status.HIGIENIZACAO},
            format="json",
        )
        assert resp.status_code == 200, resp.content
        bed.refresh_from_db()
        assert bed.status == Bed.Status.HIGIENIZACAO

    def test_reader_cannot_write_bed(self):
        Bed.objects.create(
            room=self.room, unit=self.unit, identifier="101-E", bed_type=self.bed_type
        )
        reader = self._client(self.reader)
        assert reader.get(f"{BASE}/beds/").status_code == 200
        write_resp = reader.post(
            f"{BASE}/beds/",
            {"room": str(self.room.id), "identifier": "101-F"},
            format="json",
        )
        assert write_resp.status_code == 403, write_resp.content

    def test_filter_beds_by_unit_and_status(self):
        Bed.objects.create(room=self.room, unit=self.unit, identifier="B1", status=Bed.Status.LIVRE)
        Bed.objects.create(
            room=self.room, unit=self.unit, identifier="B2", status=Bed.Status.OCUPADO
        )
        c = self._client(self.reader)
        by_unit = c.get(f"{BASE}/beds/?unit={self.unit.id}")
        assert by_unit.status_code == 200
        assert len(self._rows(by_unit)) == 2
        by_status = c.get(f"{BASE}/beds/?unit={self.unit.id}&status=ocupado")
        assert len(self._rows(by_status)) == 1
