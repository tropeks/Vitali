"""API-surface tests for the no-show wedge (PR N3).

Covers the front-desk list (NoShowRiskView) and the ack endpoint
(AcknowledgeNoShowRiskView): flag on/off, score-desc ordering, band filter,
acked excluded, ack flips status + 409 on re-ack + 404 unknown, and the
emr.read (list) / emr.write (ack) permission floors.
"""

import datetime

from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import FeatureFlag, Role, User
from apps.core.permissions import DEFAULT_ROLES
from apps.emr.models import Appointment, NoShowRisk, Patient, Professional
from apps.test_utils import TenantTestCase

LIST_URL = "/api/v1/no-show-risk/"


def _ack_url(risk_id):
    return f"/api/v1/no-show-risk/{risk_id}/acknowledge/"


class _Base(TenantTestCase):
    def setUp(self):
        self.tenant = self.__class__.tenant
        self._set_flag(True)
        self.now = timezone.now()
        self._slot = 0

        role_md = Role.objects.create(name="medico_ns", permissions=DEFAULT_ROLES["medico"])
        self.doctor = User.objects.create_user(email="ns_md@t.com", password="pw", role=role_md)
        role_rec = Role.objects.create(name="recep_ns", permissions=DEFAULT_ROLES["recepcao"])
        self.reception = User.objects.create_user(
            email="ns_rec@t.com", password="pw", role=role_rec
        )
        role_nur = Role.objects.create(name="enf_ns", permissions=DEFAULT_ROLES["enfermeiro"])
        self.nurse = User.objects.create_user(email="ns_nur@t.com", password="pw", role=role_nur)

        self.prof = Professional.objects.create(
            user=self.doctor, council_type="CRM", council_number="3", council_state="SP"
        )

    def _set_flag(self, enabled):
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key="no_show_prediction",
            defaults={"is_enabled": enabled},
        )

    def _client(self, user):
        c = APIClient()
        c.defaults["SERVER_NAME"] = self.__class__.domain.domain
        c.force_authenticate(user=user)
        return c

    def _risk(self, *, score, band, status="open", cpf=None):
        self._slot += 1
        patient = Patient.objects.create(
            full_name=f"Paciente {self._slot}",
            birth_date="1980-01-01",
            gender="F",
            cpf=cpf or f"5550000{self._slot:04d}",
        )
        start = self.now + datetime.timedelta(days=1, hours=self._slot)
        appt = Appointment.objects.create(
            patient=patient,
            professional=self.prof,
            start_time=start,
            end_time=start + datetime.timedelta(minutes=30),
            status="scheduled",
        )
        return NoShowRisk.objects.create(
            appointment=appt,
            score=score,
            band=band,
            status=status,
            suggested_action="confirm_active",
            engine_version="noshow-n1",
        )


class TestList(_Base):
    def test_empty_when_flag_off(self):
        self._risk(score="0.6000", band="high")
        self._set_flag(False)
        body = self._client(self.doctor).get(LIST_URL).json()
        assert body["risks"] == []
        assert body["no_show_prediction_enabled"] is False

    def test_lists_open_risks_score_desc(self):
        self._risk(score="0.3000", band="medium")
        self._risk(score="0.7000", band="high")
        body = self._client(self.doctor).get(LIST_URL).json()
        assert body["no_show_prediction_enabled"] is True
        assert [r["score"] for r in body["risks"]] == ["0.7000", "0.3000"]
        assert body["risks"][0]["patient_name"]
        assert body["risks"][0]["appointment_start"]
        assert body["truncated"] is False

    def test_excludes_acknowledged(self):
        self._risk(score="0.6000", band="high", status="acknowledged")
        body = self._client(self.doctor).get(LIST_URL).json()
        assert body["risks"] == []

    def test_band_filter(self):
        self._risk(score="0.3000", band="medium")
        high = self._risk(score="0.8000", band="high")
        body = self._client(self.doctor).get(LIST_URL, {"band": "high"}).json()
        assert len(body["risks"]) == 1
        assert body["risks"][0]["id"] == str(high.id)

    def test_list_requires_emr_read(self):
        resp = self._client(self.reception).get(LIST_URL)
        assert resp.status_code == 403


class TestAck(_Base):
    def test_ack_open_risk(self):
        risk = self._risk(score="0.6000", band="high")
        resp = self._client(self.doctor).post(
            _ack_url(risk.id), {"note": "confirmei"}, format="json"
        )
        assert resp.status_code == 200
        risk.refresh_from_db()
        assert risk.status == NoShowRisk.Status.ACKNOWLEDGED
        assert risk.acknowledged_by_id == self.doctor.id
        assert risk.note == "confirmei"

    def test_reack_returns_409(self):
        risk = self._risk(score="0.6000", band="high", status="acknowledged")
        resp = self._client(self.doctor).post(_ack_url(risk.id), {}, format="json")
        assert resp.status_code == 409

    def test_ack_unknown_404(self):
        resp = self._client(self.doctor).post(
            _ack_url("00000000-0000-0000-0000-000000000000"), {}, format="json"
        )
        assert resp.status_code == 404

    def test_ack_requires_emr_write(self):
        risk = self._risk(score="0.6000", band="high")
        resp = self._client(self.nurse).post(_ack_url(risk.id), {}, format="json")
        assert resp.status_code == 403
        risk.refresh_from_db()
        assert risk.status == NoShowRisk.Status.OPEN
