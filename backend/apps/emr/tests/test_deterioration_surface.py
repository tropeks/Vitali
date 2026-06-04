"""API-surface tests for the clinical-deterioration wedge (PR D3a).

Covers the read dashboard (DeteriorationAlertsView) and the ack endpoint
(AcknowledgeDeteriorationAlertView):
  * list is EMPTY when the deterioration_safety flag is OFF;
  * list returns OPEN alerts (score-desc), excludes acked ones, ?encounter_id filter;
  * ack flips status + records who/when/note; re-ack → 409; unknown → 404;
  * permissions: list needs emr.read, ack needs emr.write.

The alerts are created directly (the engine/orchestrator are tested in
test_deterioration_safety); here we exercise the HTTP surface only.

Run: python manage.py test apps.emr.tests.test_deterioration_surface
"""

from decimal import Decimal

from rest_framework.test import APIClient

from apps.core.models import FeatureFlag, Role, User
from apps.core.permissions import DEFAULT_ROLES
from apps.emr.models import DeteriorationAlert, Encounter, Patient, Professional, VitalSigns
from apps.test_utils import TenantTestCase

LIST_URL = "/api/v1/deterioration-alerts/"


def _ack_url(alert_id):
    return f"/api/v1/deterioration-alerts/{alert_id}/acknowledge/"


class _Base(TenantTestCase):
    def setUp(self):
        self.tenant = self.__class__.tenant
        self._set_flag(True)

        role_md = Role.objects.create(name="medico_d3", permissions=DEFAULT_ROLES["medico"])
        self.doctor = User.objects.create_user(email="d3_md@t.com", password="pw", role=role_md)
        role_rec = Role.objects.create(name="recep_d3", permissions=DEFAULT_ROLES["recepcao"])
        self.reception = User.objects.create_user(
            email="d3_rec@t.com", password="pw", role=role_rec
        )
        role_nur = Role.objects.create(name="enf_d3", permissions=DEFAULT_ROLES["enfermeiro"])
        self.nurse = User.objects.create_user(email="d3_nur@t.com", password="pw", role=role_nur)

        self.patient = Patient.objects.create(
            full_name="Paciente D3", birth_date="1980-01-01", gender="M", cpf="33344455566"
        )
        self.prof = Professional.objects.create(
            user=self.doctor, council_type="CRM", council_number="7", council_state="SP"
        )
        self.encounter = Encounter.objects.create(patient=self.patient, professional=self.prof)

    def _set_flag(self, enabled):
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key="deterioration_safety",
            defaults={"is_enabled": enabled},
        )

    def _client(self, user):
        c = APIClient()
        c.defaults["SERVER_NAME"] = self.__class__.domain.domain
        c.force_authenticate(user=user)
        return c

    def _alert(self, *, encounter=None, score=7, band="high", severity="escalation", status="open"):
        vs = VitalSigns.objects.create(
            encounter=encounter or self.encounter,
            respiratory_rate=28,
            oxygen_saturation=90,
            on_supplemental_oxygen=True,
            blood_pressure_systolic=100,
            heart_rate=120,
            temperature_celsius=Decimal("39.2"),
            consciousness="A",
        )
        return DeteriorationAlert.objects.create(
            encounter=encounter or self.encounter,
            vital_signs=vs,
            score=score,
            band=band,
            breakdown={"respiratory_rate": 3, "heart_rate": 2, "temperature": 2},
            any_param_three=True,
            spo2_scale=1,
            severity=severity,
            status=status,
            engine_version="news2-rcp-2017-v1",
            message=f"NEWS2 {score}",
        )


class TestList(_Base):
    def test_empty_when_flag_off(self):
        self._alert()
        self._set_flag(False)
        resp = self._client(self.doctor).get(LIST_URL)
        assert resp.status_code == 200
        body = resp.json()
        assert body["alerts"] == []
        assert body["deterioration_safety_enabled"] is False

    def test_lists_open_alerts_score_desc(self):
        self._alert(score=5, band="medium", severity="advise")
        # second encounter, higher score → must sort first
        enc2 = Encounter.objects.create(patient=self.patient, professional=self.prof)
        self._alert(encounter=enc2, score=9, band="high", severity="escalation")
        resp = self._client(self.doctor).get(LIST_URL)
        body = resp.json()
        assert body["deterioration_safety_enabled"] is True
        assert [a["score"] for a in body["alerts"]] == [9, 5]
        assert body["alerts"][0]["band_display"]
        assert body["alerts"][0]["patient_name"] == "Paciente D3"

    def test_excludes_acknowledged(self):
        self._alert(status="acknowledged")
        resp = self._client(self.doctor).get(LIST_URL)
        assert resp.json()["alerts"] == []

    def test_filter_by_encounter(self):
        self._alert(score=5, band="medium")
        enc2 = Encounter.objects.create(patient=self.patient, professional=self.prof)
        a2 = self._alert(encounter=enc2, score=8)
        resp = self._client(self.doctor).get(LIST_URL, {"encounter_id": str(enc2.id)})
        alerts = resp.json()["alerts"]
        assert len(alerts) == 1
        assert alerts[0]["id"] == str(a2.id)

    def test_list_requires_emr_read(self):
        # recepcao has no emr.read → forbidden.
        resp = self._client(self.reception).get(LIST_URL)
        assert resp.status_code == 403


class TestAck(_Base):
    def test_ack_open_alert(self):
        alert = self._alert()
        resp = self._client(self.doctor).post(
            _ack_url(alert.id), {"note": "avaliado"}, format="json"
        )
        assert resp.status_code == 200
        alert.refresh_from_db()
        assert alert.status == DeteriorationAlert.Status.ACKNOWLEDGED
        assert alert.acknowledged_by_id == self.doctor.id
        assert alert.acknowledged_at is not None
        assert alert.note == "avaliado"

    def test_reack_returns_409(self):
        alert = self._alert(status="acknowledged")
        resp = self._client(self.doctor).post(_ack_url(alert.id), {}, format="json")
        assert resp.status_code == 409

    def test_ack_unknown_returns_404(self):
        resp = self._client(self.doctor).post(
            _ack_url("00000000-0000-0000-0000-000000000000"), {}, format="json"
        )
        assert resp.status_code == 404

    def test_ack_requires_emr_write(self):
        # Nursing has emr.read (+partial_write) but NOT emr.write → forbidden.
        alert = self._alert()
        resp = self._client(self.nurse).post(_ack_url(alert.id), {}, format="json")
        assert resp.status_code == 403
        alert.refresh_from_db()
        assert alert.status == DeteriorationAlert.Status.OPEN
