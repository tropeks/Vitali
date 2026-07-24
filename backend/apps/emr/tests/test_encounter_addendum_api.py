"""
Sprint E6-T2 — EncounterAddendum REST surface.

Contract:
- POST /api/v1/encounter-addenda/ on a signed doc → 201 + appears in the chain
- POST on an unsigned doc → 4xx
- GET  /api/v1/encounter-addenda/?target_type=&target_id= → lists the chain
- append-only: no PATCH/PUT/DELETE routes are exposed
- permission split matches the rest of the EMR API (emr.write required)
"""

from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import Role, User
from apps.core.permissions import DEFAULT_ROLES
from apps.emr.models import ClinicalDocument, Encounter, EncounterAddendum, Patient, Professional
from apps.test_utils import TenantTestCase


def _make_infra():
    role_md = Role.objects.create(name="medico_addendum_api", permissions=DEFAULT_ROLES["medico"])
    role_enf = Role.objects.create(
        name="enfermeiro_addendum_api", permissions=DEFAULT_ROLES["enfermeiro"]
    )
    medico_user = User.objects.create_user(
        email="md_addendum_api@t.com", password="pw", role=role_md
    )
    enf_user = User.objects.create_user(
        email="enf_addendum_api@t.com", password="pw", role=role_enf
    )
    patient = Patient.objects.create(
        full_name="Adendo API Patient", birth_date="1975-11-02", gender="F", cpf="22233344455"
    )
    prof = Professional.objects.create(
        user=medico_user, council_type="CRM", council_number="2020", council_state="RJ"
    )
    return medico_user, enf_user, patient, prof


def _make_encounter(patient, prof, signed=True):
    encounter = Encounter.objects.create(
        patient=patient, professional=prof, chief_complaint="Tosse"
    )
    if signed:
        encounter.status = "signed"
        encounter.signed_at = timezone.now()
        encounter.signed_by = prof.user
        encounter.signature_hash = "apihash"
        encounter.save(update_fields=["status", "signed_at", "signed_by", "signature_hash"])
    return encounter


def _make_document(encounter, signed=True):
    doc = ClinicalDocument.objects.create(
        encounter=encounter, doc_type="referral", content="Encaminhar para cardiologia"
    )
    if signed:
        doc.sign(encounter.professional.user, signature_hash="dochash")
    return doc


class TestEncounterAddendumAPI(TenantTestCase):
    def setUp(self):
        self.medico_user, self.enf_user, self.patient, self.prof = _make_infra()

    def _client(self, user):
        c = APIClient()
        c.defaults["SERVER_NAME"] = self.__class__.domain.domain
        c.force_authenticate(user=user)
        return c

    def _url(self):
        return "/api/v1/encounter-addenda/"

    def test_malformed_target_id_returns_400_not_500(self):
        # A non-UUID target_id must be a clean 400, never a 500 from the pk lookup.
        resp = self._client(self.medico_user).post(
            self._url(),
            {"target_type": "encounter", "target_id": "not-a-uuid", "reason": "x", "body": "y"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.data)

    # ── Create on signed doc → 201 + appears in chain ──────────────────────

    def test_create_addendum_on_signed_encounter_returns_201_and_in_chain(self):
        encounter = _make_encounter(self.patient, self.prof, signed=True)
        resp = self._client(self.medico_user).post(
            self._url(),
            {
                "target_type": "encounter",
                "target_id": str(encounter.id),
                "reason": "Correção de CID",
                "body": "CID correto: I10",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data["sequence"], 1)
        self.assertIsNone(resp.data["previous_addendum"])

        list_resp = self._client(self.medico_user).get(
            self._url(), {"target_type": "encounter", "target_id": str(encounter.id)}
        )
        self.assertEqual(list_resp.status_code, 200)
        self.assertEqual(
            len(list_resp.data["results"] if "results" in list_resp.data else list_resp.data), 1
        )

    def test_create_addendum_on_signed_clinical_document_returns_201(self):
        encounter = _make_encounter(self.patient, self.prof, signed=False)
        doc = _make_document(encounter, signed=True)
        resp = self._client(self.medico_user).post(
            self._url(),
            {
                "target_type": "clinical_document",
                "target_id": str(doc.id),
                "reason": "Ajuste de encaminhamento",
                "body": "Encaminhar para cardiologia pediátrica",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(
            EncounterAddendum.objects.filter(
                target_type="clinical_document", target_id=str(doc.id)
            ).count(),
            1,
        )

    # ── Create on unsigned doc → 4xx ────────────────────────────────────────

    def test_create_addendum_on_unsigned_encounter_returns_4xx(self):
        encounter = _make_encounter(self.patient, self.prof, signed=False)
        resp = self._client(self.medico_user).post(
            self._url(),
            {
                "target_type": "encounter",
                "target_id": str(encounter.id),
                "reason": "Correção",
                "body": "Complemento",
            },
            format="json",
        )
        self.assertGreaterEqual(resp.status_code, 400)
        self.assertLess(resp.status_code, 500)
        self.assertEqual(EncounterAddendum.objects.count(), 0)

    def test_create_addendum_on_unsigned_clinical_document_returns_4xx(self):
        encounter = _make_encounter(self.patient, self.prof, signed=False)
        doc = _make_document(encounter, signed=False)
        resp = self._client(self.medico_user).post(
            self._url(),
            {
                "target_type": "clinical_document",
                "target_id": str(doc.id),
                "reason": "Correção",
                "body": "Complemento",
            },
            format="json",
        )
        self.assertGreaterEqual(resp.status_code, 400)
        self.assertLess(resp.status_code, 500)

    def test_create_addendum_on_nonexistent_target_returns_4xx(self):
        import uuid

        resp = self._client(self.medico_user).post(
            self._url(),
            {
                "target_type": "encounter",
                "target_id": str(uuid.uuid4()),
                "reason": "Correção",
                "body": "Complemento",
            },
            format="json",
        )
        self.assertGreaterEqual(resp.status_code, 400)
        self.assertLess(resp.status_code, 500)

    # ── Chain ordering via the API ──────────────────────────────────────────

    def test_chain_lists_in_order_with_previous_link(self):
        encounter = _make_encounter(self.patient, self.prof, signed=True)
        client = self._client(self.medico_user)
        first = client.post(
            self._url(),
            {
                "target_type": "encounter",
                "target_id": str(encounter.id),
                "reason": "r1",
                "body": "b1",
            },
            format="json",
        )
        second = client.post(
            self._url(),
            {
                "target_type": "encounter",
                "target_id": str(encounter.id),
                "reason": "r2",
                "body": "b2",
            },
            format="json",
        )
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(second.status_code, 201, second.data)
        self.assertEqual(str(second.data["previous_addendum"]), str(first.data["id"]))
        self.assertEqual(second.data["sequence"], 2)

    # ── Append-only surface: no update/destroy routes ───────────────────────

    def test_patch_not_allowed(self):
        encounter = _make_encounter(self.patient, self.prof, signed=True)
        addendum = EncounterAddendum.objects.create_addendum(
            target=encounter, author=self.medico_user, reason="r", body="b"
        )
        resp = self._client(self.medico_user).patch(
            f"{self._url()}{addendum.id}/", {"body": "tampered"}, format="json"
        )
        self.assertEqual(resp.status_code, 405)

    def test_delete_not_allowed(self):
        encounter = _make_encounter(self.patient, self.prof, signed=True)
        addendum = EncounterAddendum.objects.create_addendum(
            target=encounter, author=self.medico_user, reason="r", body="b"
        )
        resp = self._client(self.medico_user).delete(f"{self._url()}{addendum.id}/")
        self.assertEqual(resp.status_code, 405)
        self.assertTrue(EncounterAddendum.objects.filter(id=addendum.id).exists())

    # ── Permission split ──────────────────────────────────────────────────

    def test_read_allowed_for_emr_write_role_only_not_read_only(self):
        """enfermeiro has no emr.write → POST forbidden (matches ClinicalDocumentViewSet)."""
        encounter = _make_encounter(self.patient, self.prof, signed=True)
        resp = self._client(self.enf_user).post(
            self._url(),
            {
                "target_type": "encounter",
                "target_id": str(encounter.id),
                "reason": "r",
                "body": "b",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_unauthenticated_rejected(self):
        encounter = _make_encounter(self.patient, self.prof, signed=True)
        client = APIClient()
        client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        resp = client.post(
            self._url(),
            {
                "target_type": "encounter",
                "target_id": str(encounter.id),
                "reason": "r",
                "body": "b",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 401)
