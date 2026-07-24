"""E2-T4 — REST contract for problems / allergies / immunizations.

Covers, for each of the three viewsets: 201 on create (emr.write), list scoped
by ?patient (emr.read), 403 when the caller lacks emr.write, and 401 when
unauthenticated. Matches the rest of the EMR API's permission split + tenant
scoping, and confirms the create path writes an audit row.
"""

from rest_framework.test import APIClient

from apps.core.models import AuditLog, Role, User
from apps.emr.models import Allergy, Immunization, Patient, ProblemListItem
from apps.test_utils import TenantTestCase


class _ProblemAPIBase(TenantTestCase):
    def setUp(self):
        self.rw_role = Role.objects.create(name="emr_rw_e2", permissions=["emr.read", "emr.write"])
        self.ro_role = Role.objects.create(name="emr_ro_e2", permissions=["emr.read"])
        self.rw_user = User.objects.create_user(
            email="rw_e2@t.com", password="pw", role=self.rw_role
        )
        self.ro_user = User.objects.create_user(
            email="ro_e2@t.com", password="pw", role=self.ro_role
        )
        self.patient = Patient.objects.create(
            full_name="API E2 Patient", birth_date="1980-01-01", gender="F", cpf="99999999999"
        )

    def _client(self, user=None):
        c = APIClient()
        c.defaults["SERVER_NAME"] = self.__class__.domain.domain
        if user is not None:
            c.force_authenticate(user=user)
        return c


class TestProblemAPI(_ProblemAPIBase):
    URL = "/api/v1/problems/"

    def test_create_returns_201_and_audits(self):
        resp = self._client(self.rw_user).post(
            self.URL,
            {"patient": str(self.patient.id), "condition": "Hipertensão", "cid10_code": "I10"},
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(ProblemListItem.objects.filter(patient=self.patient).count(), 1)
        self.assertTrue(AuditLog.objects.filter(action="problem_create").exists())

    def test_list_scoped_by_patient(self):
        other = Patient.objects.create(
            full_name="Other", birth_date="1980-01-01", gender="M", cpf="99999999998"
        )
        ProblemListItem.objects.create(patient=self.patient, condition="A")
        ProblemListItem.objects.create(patient=other, condition="B")
        resp = self._client(self.rw_user).get(self.URL, {"patient": str(self.patient.id)})
        self.assertEqual(resp.status_code, 200)
        rows = resp.data["results"] if "results" in resp.data else resp.data
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["condition"], "A")

    def test_write_forbidden_without_emr_write(self):
        resp = self._client(self.ro_user).post(
            self.URL,
            {"patient": str(self.patient.id), "condition": "X"},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_unauthenticated_rejected(self):
        resp = self._client().get(self.URL)
        self.assertEqual(resp.status_code, 401)


class TestAllergyAPI(_ProblemAPIBase):
    URL = "/api/v1/allergies/"

    def test_create_returns_201(self):
        resp = self._client(self.rw_user).post(
            self.URL,
            {
                "patient": str(self.patient.id),
                "substance": "penicilina",
                "severity": "severe",
                "criticality": "high",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(Allergy.objects.filter(patient=self.patient).count(), 1)

    def test_list_scoped_by_patient(self):
        Allergy.objects.create(patient=self.patient, substance="camarão", severity="mild")
        resp = self._client(self.ro_user).get(self.URL, {"patient": str(self.patient.id)})
        self.assertEqual(resp.status_code, 200)
        rows = resp.data["results"] if "results" in resp.data else resp.data
        self.assertEqual(len(rows), 1)

    def test_write_forbidden_without_emr_write(self):
        resp = self._client(self.ro_user).post(
            self.URL,
            {"patient": str(self.patient.id), "substance": "x", "severity": "mild"},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_unauthenticated_rejected(self):
        resp = self._client().get(self.URL)
        self.assertEqual(resp.status_code, 401)


class TestImmunizationAPI(_ProblemAPIBase):
    URL = "/api/v1/immunizations/"

    def test_create_returns_201(self):
        resp = self._client(self.rw_user).post(
            self.URL,
            {
                "patient": str(self.patient.id),
                "immunobiological": "BCG",
                "dose_number": "única",
                "date": "2020-01-05",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(Immunization.objects.filter(patient=self.patient).count(), 1)

    def test_list_scoped_by_patient(self):
        Immunization.objects.create(patient=self.patient, immunobiological="BCG", date="2020-01-05")
        resp = self._client(self.ro_user).get(self.URL, {"patient": str(self.patient.id)})
        self.assertEqual(resp.status_code, 200)
        rows = resp.data["results"] if "results" in resp.data else resp.data
        self.assertEqual(len(rows), 1)

    def test_write_forbidden_without_emr_write(self):
        resp = self._client(self.ro_user).post(
            self.URL,
            {"patient": str(self.patient.id), "immunobiological": "BCG", "date": "2020-01-05"},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_unauthenticated_rejected(self):
        resp = self._client().get(self.URL)
        self.assertEqual(resp.status_code, 401)
