"""Integration tests for the allergy-safety gate (allergy wedge A1).

Exercises the soft-stop at prescription sign + pharmacy dispense, the
allergy_safety feature flag (OFF → no-op), override-releases-gate, the SAFE and
inactive-allergy paths, and the generalized block payload (code reused from the
dose gate so the existing frontend modal fires).

The pure matching is covered in test_allergy_checker; here we test the wiring.
"""

from decimal import Decimal

from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import FeatureFlag, Role, User
from apps.core.permissions import DEFAULT_ROLES
from apps.emr.models import (
    AISafetyAlert,
    Allergy,
    Encounter,
    Patient,
    Prescription,
    PrescriptionItem,
    Professional,
)
from apps.pharmacy.models import Drug, StockItem, StockMovement
from apps.test_utils import TenantTestCase


class _Base(TenantTestCase):
    def setUp(self):
        self.tenant = self.__class__.tenant
        self._set_flag("allergy_safety", True)
        # Pharmacy module on so the dispense endpoint is reachable.
        FeatureFlag.objects.update_or_create(
            tenant=self.tenant, module_key="pharmacy", defaults={"is_enabled": True}
        )

        role_md = Role.objects.create(name="medico_a1", permissions=DEFAULT_ROLES["medico"])
        self.doctor = User.objects.create_user(email="a1_md@t.com", password="pw", role=role_md)
        role_ph = Role.objects.create(name="farma_a1", permissions=DEFAULT_ROLES["farmaceutico"])
        self.pharmacist = User.objects.create_user(email="a1_ph@t.com", password="pw", role=role_ph)

        self.patient = Patient.objects.create(
            full_name="Allergy Patient", birth_date="1980-01-01", gender="F", cpf="77788899900"
        )
        self.prof = Professional.objects.create(
            user=self.doctor, council_type="CRM", council_number="11", council_state="SP"
        )
        self.encounter = Encounter.objects.create(patient=self.patient, professional=self.prof)
        # Active allergy to Dipirona.
        self.allergy = Allergy.objects.create(
            patient=self.patient, substance="Dipirona", severity="severe", status="active"
        )
        self.dipirona = Drug.objects.create(
            name="Dipirona 500mg", generic_name="Dipirona", active_ingredients=["Dipirona"]
        )
        self.paracetamol = Drug.objects.create(
            name="Paracetamol 750mg", generic_name="Paracetamol", active_ingredients=["Paracetamol"]
        )

    def _set_flag(self, key, enabled):
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant, module_key=key, defaults={"is_enabled": enabled}
        )

    def _client(self, user):
        c = APIClient()
        c.defaults["SERVER_NAME"] = self.__class__.domain.domain
        c.force_authenticate(user=user)
        return c

    def _make_rx(self, *, drug=None, signed=False):
        drug = drug or self.dipirona
        rx = Prescription.objects.create(
            encounter=self.encounter, patient=self.patient, prescriber=self.prof
        )
        if signed:
            rx.sign(self.doctor)  # model method — bypasses the endpoint gate
        item = PrescriptionItem.objects.create(
            prescription=rx, drug=drug, quantity=Decimal("1"), unit_of_measure="un"
        )
        return rx, item

    def _sign(self, rx):
        return self._client(self.doctor).post(f"/api/v1/prescriptions/{rx.id}/sign/")


class TestSignGate(_Base):
    def test_sign_blocks_on_active_allergy(self):
        rx, item = self._make_rx(drug=self.dipirona)
        resp = self._sign(rx)
        assert resp.status_code == 409
        assert resp.data["code"] == "dose_safety_block"
        kinds = {a["blocking_kind"] for a in resp.data["alerts"]}
        assert "allergy_conflict" in kinds
        alert = AISafetyAlert.objects.get(
            prescription_item=item, alert_type="allergy", source=AISafetyAlert.Source.ENGINE
        )
        assert alert.severity == "contraindication"
        assert alert.status == "flagged"
        rx.refresh_from_db()
        assert rx.is_signed is False

    def test_flag_off_signs_through(self):
        self._set_flag("allergy_safety", False)
        rx, item = self._make_rx(drug=self.dipirona)
        resp = self._sign(rx)
        assert resp.status_code == 200
        assert not AISafetyAlert.objects.filter(
            prescription_item=item, alert_type="allergy", source=AISafetyAlert.Source.ENGINE
        ).exists()

    def test_acknowledge_releases_gate(self):
        rx, item = self._make_rx(drug=self.dipirona)
        assert self._sign(rx).status_code == 409
        alert = AISafetyAlert.objects.get(
            prescription_item=item, alert_type="allergy", source=AISafetyAlert.Source.ENGINE
        )
        resp = self._client(self.doctor).post(
            f"/api/v1/safety-alerts/{alert.id}/acknowledge/",
            {"reason": "Alergia antiga, leve; benefício supera o risco."},
            format="json",
        )
        assert resp.status_code == 200
        # Gate released: re-sign succeeds (override preserved on re-evaluation).
        assert self._sign(rx).status_code == 200

    def test_non_conflicting_drug_signs(self):
        rx, _item = self._make_rx(drug=self.paracetamol)
        assert self._sign(rx).status_code == 200

    def test_inactive_allergy_is_ignored(self):
        self.allergy.status = "inactive"
        self.allergy.save(update_fields=["status"])
        rx, _item = self._make_rx(drug=self.dipirona)
        assert self._sign(rx).status_code == 200


class TestDispenseGate(_Base):
    def _make_lot(self, drug, qty):
        future = (timezone.now() + timezone.timedelta(days=90)).date()
        item = StockItem.objects.create(drug=drug, lot_number="L1", expiry_date=future)
        StockMovement(stock_item=item, movement_type="entry", quantity=qty).save()
        return item

    def test_dispense_blocks_on_active_allergy(self):
        # Sign directly (bypassing the endpoint gate), then dispense must re-catch it.
        self._make_lot(self.dipirona, Decimal("10"))
        rx, item = self._make_rx(drug=self.dipirona, signed=True)
        resp = self._client(self.pharmacist).post(
            "/api/v1/pharmacy/dispense/",
            {"prescription_item_id": str(item.id), "quantity": "1"},
            format="json",
        )
        assert resp.status_code == 409
        assert resp.data["code"] == "dose_safety_block"
        assert any(a["blocking_kind"] == "allergy_conflict" for a in resp.data["alerts"])
