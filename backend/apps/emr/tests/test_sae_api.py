"""
N2-T3 — SAE domain DRF API: list/create, ?patient=/?encounter= filtering, and the
sae.read/sae.write permission split (COFEN 736/2024 — diagnóstico/prescrição
privativos do enfermeiro).

enfermeiro carries sae.read + sae.write; medico carries only sae.read → medico can
read the SAE resources but is 403 on any write (diagnosis/careplan/prescription).
"""

from rest_framework.test import APIClient

from apps.core.models import NandaDiagnosis, NicIntervention, NocOutcome, Role, User
from apps.core.permissions import CLINICAL_PRESCRIBER_PERMISSIONS, NURSING_PERMISSIONS
from apps.emr.models import (
    Encounter,
    NursingCareplan,
    NursingCareplanIntervention,
    NursingDiagnosis,
    Patient,
    Professional,
)
from apps.test_utils import TenantTestCase

BASE = "/api/v1"


class SAEAPITestBase(TenantTestCase):
    def setUp(self):
        self.enf_role = Role.objects.create(name="enf_role", permissions=NURSING_PERMISSIONS)
        self.med_role = Role.objects.create(
            name="med_role", permissions=CLINICAL_PRESCRIBER_PERMISSIONS
        )
        self.enf = User.objects.create_user(email="enf@t.com", password="pw", role=self.enf_role)
        self.med = User.objects.create_user(email="med@t.com", password="pw", role=self.med_role)

        self.patient = Patient.objects.create(
            full_name="API SAE", birth_date="1990-01-01", gender="F", cpf="44444444444"
        )
        self.prof = Professional.objects.create(
            user=self.enf, council_type="COREN", council_number="7", council_state="SP"
        )
        self.encounter = Encounter.objects.create(patient=self.patient, professional=self.prof)
        self.nanda = NandaDiagnosis.objects.create(code="00132", display="Dor aguda")
        self.noc = NocOutcome.objects.create(code="2102", display="Nível de dor")
        self.nic = NicIntervention.objects.create(code="1400", display="Controle da dor")

    def _client(self, user):
        c = APIClient()
        c.defaults["SERVER_NAME"] = self.__class__.domain.domain
        c.force_authenticate(user)
        return c

    @staticmethod
    def _rows(resp):
        """Unwrap paginated (StandardResultsSetPagination) or plain list bodies."""
        return resp.data["results"] if "results" in resp.data else resp.data


class TestNursingDiagnosisAPI(SAEAPITestBase):
    def test_enfermeiro_can_create_diagnosis(self):
        resp = self._client(self.enf).post(
            f"{BASE}/nursing-diagnoses/",
            {
                "encounter": str(self.encounter.id),
                "nanda": self.nanda.pk,
                "related_factors": "agente lesivo",
                "priority": "high",
            },
            format="json",
        )
        assert resp.status_code == 201, resp.content
        dx = NursingDiagnosis.objects.get(pk=resp.data["id"])
        assert dx.patient_id == self.patient.id  # derived from encounter
        assert dx.created_by_id == self.enf.id  # stamped from request user
        assert dx.nanda_id == self.nanda.pk
        assert resp.data["nanda_code"] == "00132"

    def test_create_diagnosis_by_nanda_code_resolves_fk(self):
        # The terminology picker exposes only code/display (no catalog PK), so the
        # SAE workspace posts nanda_code. The writable *_code accessor must resolve
        # it to the governed FK — not silently drop the link.
        resp = self._client(self.enf).post(
            f"{BASE}/nursing-diagnoses/",
            {"encounter": str(self.encounter.id), "nanda_code": "00132", "priority": "high"},
            format="json",
        )
        assert resp.status_code == 201, resp.content
        dx = NursingDiagnosis.objects.get(pk=resp.data["id"])
        assert dx.nanda_id == self.nanda.pk
        assert dx.nanda_unmatched is False
        assert resp.data["nanda_code"] == "00132"

    def test_create_diagnosis_by_unknown_code_marks_unmatched(self):
        resp = self._client(self.enf).post(
            f"{BASE}/nursing-diagnoses/",
            {"encounter": str(self.encounter.id), "nanda_code": "99999"},
            format="json",
        )
        assert resp.status_code == 201, resp.content
        dx = NursingDiagnosis.objects.get(pk=resp.data["id"])
        assert dx.nanda_id is None
        assert dx.nanda_unmatched is True
        assert dx.legacy_nanda_text == "99999"

    def test_medico_can_read_but_not_write_diagnosis(self):
        NursingDiagnosis.objects.create(
            patient=self.patient, encounter=self.encounter, nanda=self.nanda, created_by=self.enf
        )
        med = self._client(self.med)
        # read allowed (sae.read)
        list_resp = med.get(f"{BASE}/nursing-diagnoses/")
        assert list_resp.status_code == 200
        assert len(self._rows(list_resp)) >= 1
        # write forbidden (needs sae.write — enfermeiro-privativo)
        write_resp = med.post(
            f"{BASE}/nursing-diagnoses/",
            {"encounter": str(self.encounter.id), "nanda": self.nanda.pk},
            format="json",
        )
        assert write_resp.status_code == 403, write_resp.content

    def test_filter_by_patient_and_encounter(self):
        NursingDiagnosis.objects.create(
            patient=self.patient, encounter=self.encounter, nanda=self.nanda, created_by=self.enf
        )
        other_patient = Patient.objects.create(
            full_name="Other", birth_date="1980-01-01", gender="M", cpf="55555555555"
        )
        other_enc = Encounter.objects.create(patient=other_patient, professional=self.prof)
        NursingDiagnosis.objects.create(
            patient=other_patient, encounter=other_enc, created_by=self.enf
        )
        c = self._client(self.enf)
        by_patient = c.get(f"{BASE}/nursing-diagnoses/?patient={self.patient.id}")
        assert by_patient.status_code == 200
        assert len(self._rows(by_patient)) == 1
        by_enc = c.get(f"{BASE}/nursing-diagnoses/?encounter={self.encounter.id}")
        assert len(self._rows(by_enc)) == 1


class TestSAEChainAPI(SAEAPITestBase):
    def test_enfermeiro_builds_full_chain(self):
        c = self._client(self.enf)
        dx = NursingDiagnosis.objects.create(
            patient=self.patient, encounter=self.encounter, nanda=self.nanda, created_by=self.enf
        )
        plan_resp = c.post(
            f"{BASE}/nursing-careplans/",
            {"diagnosis": str(dx.id), "noc": self.noc.pk, "target": "dor ≤ 2"},
            format="json",
        )
        assert plan_resp.status_code == 201, plan_resp.content
        assert plan_resp.data["noc_code"] == "2102"

        interv_resp = c.post(
            f"{BASE}/nursing-care-interventions/",
            {"careplan": plan_resp.data["id"], "nic": self.nic.pk},
            format="json",
        )
        assert interv_resp.status_code == 201, interv_resp.content

        rx_resp = c.post(
            f"{BASE}/nursing-prescription-items/",
            {
                "intervention": interv_resp.data["id"],
                "description": "Verificar sinais vitais",
                "frequency_hours": 6,
                "start_at": "2026-07-24T08:00:00Z",
            },
            format="json",
        )
        assert rx_resp.status_code == 201, rx_resp.content
        assert rx_resp.data["frequency_hours"] == 6
        assert str(rx_resp.data["created_by"]) == str(self.enf.id)

    def test_medico_cannot_write_prescription_item(self):
        dx = NursingDiagnosis.objects.create(
            patient=self.patient, encounter=self.encounter, created_by=self.enf
        )
        plan = NursingCareplan.objects.create(diagnosis=dx, noc=self.noc, created_by=self.enf)
        interv = NursingCareplanIntervention.objects.create(careplan=plan, nic=self.nic)
        resp = self._client(self.med).post(
            f"{BASE}/nursing-prescription-items/",
            {
                "intervention": str(interv.id),
                "frequency_hours": 8,
                "start_at": "2026-07-24T08:00:00Z",
            },
            format="json",
        )
        assert resp.status_code == 403, resp.content


class TestNursingEvolutionAPI(SAEAPITestBase):
    def test_enfermeiro_creates_evolution_patient_derived(self):
        resp = self._client(self.enf).post(
            f"{BASE}/nursing-evolutions/",
            {"encounter": str(self.encounter.id), "text": "Paciente estável."},
            format="json",
        )
        assert resp.status_code == 201, resp.content
        assert str(resp.data["patient"]) == str(self.patient.id)

    def test_filter_evolutions_by_patient(self):
        self._client(self.enf).post(
            f"{BASE}/nursing-evolutions/",
            {"encounter": str(self.encounter.id), "text": "Nota 1"},
            format="json",
        )
        resp = self._client(self.enf).get(f"{BASE}/nursing-evolutions/?patient={self.patient.id}")
        assert resp.status_code == 200
        assert len(self._rows(resp)) == 1
