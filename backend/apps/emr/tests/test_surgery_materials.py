"""
C6 — Centro Cirúrgico OPME / materiais + consumo de sala (rastreabilidade).

Covers:
* SurgicalMaterial CRUD (add OPME with lot/serial) gated surgery.manage;
  reader (surgery.read only) is 403 on writes, 200 on reads.
* record_consumption service: increments quantity_consumed atomically and — IF a
  stock_item is linked — creates a StockMovement (movement_type="dispense",
  negative quantity) traced to the surgical_case, decrementing the catalogued
  stock per the existing StockMovement conventions.
* Consuming WITHOUT a stock_item just tracks quantity_consumed (uncatalogued
  OPME): no StockMovement is created.
* consume action endpoint (POST /surgical-materials/{id}/consume/) gated
  surgery.manage.
* list filter ?case=.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.core.models import Role, User
from apps.emr.models import (
    OperatingRoom,
    Patient,
    Professional,
    SurgicalCase,
    SurgicalMaterial,
)
from apps.emr.services import surgery_materials as materials_service
from apps.organization.models import Facility, LegalEntity
from apps.pharmacy.models import Material, StockItem, StockMovement
from apps.test_utils import TenantTestCase

BASE = "/api/v1"

MANAGE_PERMS = ["surgery.read", "surgery.manage"]
READ_PERMS = ["surgery.read"]


class MaterialsTestBase(TenantTestCase):
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
        self.patient = Patient.objects.create(
            full_name="Maria Operada", birth_date="1980-01-01", gender="F", cpf="52998224725"
        )
        self.room = OperatingRoom.objects.create(facility=self.facility, code="SO-1", name="Sala 1")

    def _case(self, **kw):
        defaults = {"patient": self.patient, "surgeon": self.surgeon}
        defaults.update(kw)
        return SurgicalCase.objects.create(**defaults)

    def _stock_item(self, quantity=Decimal("100")):
        material = Material.objects.create(name="Placa de titânio", unit_of_measure="un")
        return StockItem.objects.create(
            material=material, quantity=quantity, lot_number="LOT-OPME-1"
        )

    def _client(self, user):
        c = APIClient()
        c.defaults["SERVER_NAME"] = self.__class__.domain.domain
        c.force_authenticate(user)
        return c


# ── record_consumption service ────────────────────────────────────────────────


class TestRecordConsumptionService(MaterialsTestBase):
    def test_consume_increments_quantity_consumed(self):
        case = self._case()
        mat = SurgicalMaterial.objects.create(
            case=case,
            kind=SurgicalMaterial.Kind.OPME,
            description="Parafuso ortopédico",
            quantity_planned=3,
        )
        out = materials_service.record_consumption(mat, 2, actor=self.manager)
        out.refresh_from_db()
        assert out.quantity_consumed == 2
        out = materials_service.record_consumption(mat, 1, actor=self.manager)
        out.refresh_from_db()
        assert out.quantity_consumed == 3

    def test_consume_without_stock_item_creates_no_movement(self):
        case = self._case()
        mat = SurgicalMaterial.objects.create(
            case=case, kind=SurgicalMaterial.Kind.OPME, description="Enxerto (não catalogado)"
        )
        materials_service.record_consumption(mat, 1, actor=self.manager)
        mat.refresh_from_db()
        assert mat.quantity_consumed == 1
        assert StockMovement.objects.count() == 0

    def test_consume_with_stock_item_creates_traced_movement(self):
        case = self._case()
        item = self._stock_item(quantity=Decimal("10"))
        mat = SurgicalMaterial.objects.create(
            case=case,
            kind=SurgicalMaterial.Kind.MATERIAL,
            stock_item=item,
            description="Placa de titânio",
        )
        materials_service.record_consumption(mat, 4, actor=self.manager)

        mat.refresh_from_db()
        assert mat.quantity_consumed == 4

        # StockMovement created, traced to the case, stock decremented.
        movements = StockMovement.objects.filter(stock_item=item)
        assert movements.count() == 1
        mv = movements.first()
        assert mv.movement_type == "dispense"
        assert mv.quantity == Decimal("-4")
        assert mv.surgical_case_id == case.id
        assert mv.performed_by_id == self.manager.id
        assert str(case.id) in mv.reference

        item.refresh_from_db()
        assert item.quantity == Decimal("6")

        # Reverse relation on the case.
        assert case.surgical_movements.count() == 1

    def test_consume_zero_or_negative_rejected(self):
        case = self._case()
        mat = SurgicalMaterial.objects.create(case=case, kind=SurgicalMaterial.Kind.OUTRO)
        with pytest.raises(ValidationError):
            materials_service.record_consumption(mat, 0, actor=self.manager)
        with pytest.raises(ValidationError):
            materials_service.record_consumption(mat, -1, actor=self.manager)


# ── SurgicalMaterial CRUD API ─────────────────────────────────────────────────


class TestMaterialsAPI(MaterialsTestBase):
    def test_add_opme_with_lot_serial(self):
        case = self._case()
        resp = self._client(self.manager).post(
            f"{BASE}/surgical-materials/",
            {
                "case": str(case.id),
                "kind": SurgicalMaterial.Kind.OPME,
                "description": "Prótese de quadril",
                "quantity_planned": 1,
                "laterality": "direita",
                "lot": "LOTE-XYZ",
                "serial": "SN-0001",
                "manufacturer": "Acme Ortho",
            },
            format="json",
        )
        assert resp.status_code == 201, resp.content
        assert case.materials.count() == 1
        mat = case.materials.first()
        assert mat.lot == "LOTE-XYZ"
        assert mat.serial == "SN-0001"
        assert mat.quantity_consumed == 0

    def test_add_material_requires_manage(self):
        case = self._case()
        resp = self._client(self.reader).post(
            f"{BASE}/surgical-materials/",
            {"case": str(case.id), "kind": SurgicalMaterial.Kind.MATERIAL, "description": "Gaze"},
            format="json",
        )
        assert resp.status_code == 403, resp.content

    def test_list_filtered_by_case(self):
        case = self._case()
        other = self._case()
        SurgicalMaterial.objects.create(case=case, kind=SurgicalMaterial.Kind.OPME)
        SurgicalMaterial.objects.create(case=other, kind=SurgicalMaterial.Kind.MATERIAL)
        resp = self._client(self.reader).get(f"{BASE}/surgical-materials/?case={case.id}")
        assert resp.status_code == 200, resp.content
        assert resp.data["count"] == 1

    def test_read_requires_read_perm(self):
        case = self._case()
        resp = self._client(self.nobody).get(f"{BASE}/surgical-materials/?case={case.id}")
        assert resp.status_code == 403, resp.content

    def test_consume_endpoint_tracks_and_traces(self):
        case = self._case()
        item = self._stock_item(quantity=Decimal("10"))
        mat = SurgicalMaterial.objects.create(
            case=case, kind=SurgicalMaterial.Kind.MATERIAL, stock_item=item
        )
        resp = self._client(self.manager).post(
            f"{BASE}/surgical-materials/{mat.id}/consume/",
            {"quantity": 3},
            format="json",
        )
        assert resp.status_code == 200, resp.content
        assert resp.data["quantity_consumed"] == 3
        item.refresh_from_db()
        assert item.quantity == Decimal("7")
        assert StockMovement.objects.filter(surgical_case=case).count() == 1

    def test_consume_requires_manage(self):
        case = self._case()
        mat = SurgicalMaterial.objects.create(case=case, kind=SurgicalMaterial.Kind.OPME)
        resp = self._client(self.reader).post(
            f"{BASE}/surgical-materials/{mat.id}/consume/",
            {"quantity": 1},
            format="json",
        )
        assert resp.status_code == 403, resp.content

    def test_consume_invalid_quantity_returns_400(self):
        case = self._case()
        mat = SurgicalMaterial.objects.create(case=case, kind=SurgicalMaterial.Kind.OPME)
        resp = self._client(self.manager).post(
            f"{BASE}/surgical-materials/{mat.id}/consume/",
            {"quantity": 0},
            format="json",
        )
        assert resp.status_code == 400, resp.content
