"""API-surface tests for the controlled-diversion compliance panel (PR C3).

Covers ControlledAlertsView + AcknowledgeControlledAlertView: flag on/off,
newest-first ordering, signal_kind filter, acked excluded, ack flips status +
409 re-ack + 404 unknown, and the pharmacy.read permission floor.
"""

import datetime
from decimal import Decimal

from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import FeatureFlag, Role, User
from apps.core.permissions import DEFAULT_ROLES
from apps.emr.models import Encounter, Patient, Prescription, PrescriptionItem, Professional
from apps.pharmacy.models import ControlledAlert, Dispensation, Drug
from apps.test_utils import TenantTestCase

LIST_URL = "/api/v1/pharmacy/controlled/alerts/"


def _ack_url(alert_id):
    return f"/api/v1/pharmacy/controlled/alerts/{alert_id}/acknowledge/"


class _Base(TenantTestCase):
    def setUp(self):
        self.tenant = self.__class__.tenant
        self._set_flag("controlled_safety", True)
        self._set_flag("pharmacy", True)
        self.now = timezone.now()

        role_ph = Role.objects.create(name="farma_cd", permissions=DEFAULT_ROLES["farmaceutico"])
        self.pharmacist = User.objects.create_user(email="cd_ph@t.com", password="pw", role=role_ph)
        role_rec = Role.objects.create(name="recep_cd", permissions=DEFAULT_ROLES["recepcao"])
        self.reception = User.objects.create_user(
            email="cd_rec@t.com", password="pw", role=role_rec
        )

        self.patient = Patient.objects.create(
            full_name="Paciente CD", birth_date="1980-01-01", gender="M", cpf="66677788899"
        )
        self.prof = Professional.objects.create(
            user=self.pharmacist, council_type="CRM", council_number="9", council_state="SP"
        )
        self.drug = Drug.objects.create(name="Clonazepam 2mg", controlled_class="B1")
        self._slot = 0

    def _set_flag(self, key, enabled):
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant, module_key=key, defaults={"is_enabled": enabled}
        )

    def _client(self, user):
        c = APIClient()
        c.defaults["SERVER_NAME"] = self.__class__.domain.domain
        c.force_authenticate(user=user)
        return c

    def _alert(self, *, signal_kind="refill_too_soon", status="open"):
        self._slot += 1
        rx = Prescription.objects.create(
            encounter=Encounter.objects.create(patient=self.patient, professional=self.prof),
            patient=self.patient,
            prescriber=self.prof,
        )
        item = PrescriptionItem.objects.create(
            prescription=rx, drug=self.drug, quantity=Decimal("10"), unit_of_measure="un"
        )
        disp = Dispensation.objects.create(
            prescription=rx,
            prescription_item=item,
            patient=self.patient,
            dispensed_by=self.pharmacist,
        )
        # Distinct created_at ordering for the newest-first assertion.
        Dispensation.objects.filter(pk=disp.pk).update(
            dispensed_at=self.now - datetime.timedelta(hours=self._slot)
        )
        return ControlledAlert.objects.create(
            dispensation=disp,
            patient=self.patient,
            drug=self.drug,
            signal_kind=signal_kind,
            detail={"gap_days": 5},
            status=status,
            engine_version="controlled-c1",
        )


class TestList(_Base):
    def test_empty_when_flag_off(self):
        self._alert()
        self._set_flag("controlled_safety", False)
        body = self._client(self.pharmacist).get(LIST_URL).json()
        assert body["alerts"] == []
        assert body["controlled_safety_enabled"] is False

    def test_lists_open_alerts(self):
        self._alert(signal_kind="refill_too_soon")
        self._alert(signal_kind="quantity_escalation")
        body = self._client(self.pharmacist).get(LIST_URL).json()
        assert body["controlled_safety_enabled"] is True
        assert len(body["alerts"]) == 2
        assert body["alerts"][0]["patient_name"] == "Paciente CD"
        assert body["truncated"] is False

    def test_excludes_acknowledged(self):
        self._alert(status="acknowledged")
        body = self._client(self.pharmacist).get(LIST_URL).json()
        assert body["alerts"] == []

    def test_signal_kind_filter(self):
        self._alert(signal_kind="refill_too_soon")
        esc = self._alert(signal_kind="quantity_escalation")
        body = (
            self._client(self.pharmacist)
            .get(LIST_URL, {"signal_kind": "quantity_escalation"})
            .json()
        )
        assert len(body["alerts"]) == 1
        assert body["alerts"][0]["id"] == str(esc.id)

    def test_list_requires_pharmacy_read(self):
        resp = self._client(self.reception).get(LIST_URL)
        assert resp.status_code == 403


class TestAck(_Base):
    def test_ack_open_alert(self):
        alert = self._alert()
        resp = self._client(self.pharmacist).post(_ack_url(alert.id), {"note": "ok"}, format="json")
        assert resp.status_code == 200
        alert.refresh_from_db()
        assert alert.status == ControlledAlert.Status.ACKNOWLEDGED
        assert alert.acknowledged_by_id == self.pharmacist.id

    def test_reack_returns_409(self):
        alert = self._alert(status="acknowledged")
        resp = self._client(self.pharmacist).post(_ack_url(alert.id), {}, format="json")
        assert resp.status_code == 409

    def test_ack_unknown_404(self):
        resp = self._client(self.pharmacist).post(
            _ack_url("00000000-0000-0000-0000-000000000000"), {}, format="json"
        )
        assert resp.status_code == 404

    def test_ack_requires_pharmacy_read(self):
        alert = self._alert()
        resp = self._client(self.reception).post(_ack_url(alert.id), {}, format="json")
        assert resp.status_code == 403
