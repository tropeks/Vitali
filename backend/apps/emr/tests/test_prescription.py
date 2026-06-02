"""
S-015 Prescription — sign action, status transition, generic_name auto-population.
"""

from decimal import Decimal

from rest_framework.test import APIClient

from apps.core.permissions import DEFAULT_ROLES
from apps.emr.models import Encounter, Patient, Prescription, PrescriptionItem, Professional
from apps.pharmacy.models import Drug
from apps.test_utils import TenantTestCase


def _make_infra():
    from apps.core.models import Role, User

    role_md = Role.objects.create(name="medico_px", permissions=DEFAULT_ROLES["medico"])
    role_enf = Role.objects.create(name="enfermeiro_px", permissions=DEFAULT_ROLES["enfermeiro"])
    medico_user = User.objects.create_user(email="md_px@t.com", password="pw", role=role_md)
    enf_user = User.objects.create_user(email="enf_px@t.com", password="pw", role=role_enf)
    patient = Patient.objects.create(
        full_name="Prescription Patient", birth_date="1985-06-15", gender="F", cpf="22222222222"
    )
    prescriber = Professional.objects.create(
        user=medico_user, council_type="CRM", council_number="5", council_state="RJ"
    )
    encounter = Encounter.objects.create(patient=patient, professional=prescriber)
    return medico_user, enf_user, patient, prescriber, encounter


class TestPrescriptionModel(TenantTestCase):
    def setUp(self):
        self.medico_user, self.enf_user, self.patient, self.prescriber, self.encounter = (
            _make_infra()
        )

    def test_prescription_status_transition_draft_to_signed(self):
        rx = Prescription.objects.create(
            encounter=self.encounter, patient=self.patient, prescriber=self.prescriber
        )
        self.assertEqual(rx.status, "draft")
        self.assertFalse(rx.is_signed)
        rx.sign(self.medico_user)
        self.assertEqual(rx.status, "signed")
        self.assertTrue(rx.is_signed)
        self.assertIsNotNone(rx.signed_at)

    def test_prescription_item_generic_name_auto_populated(self):
        drug = Drug.objects.create(
            name="Amoxicilina 500mg", generic_name="amoxicilina tri-hidratada"
        )
        rx = Prescription.objects.create(
            encounter=self.encounter, patient=self.patient, prescriber=self.prescriber
        )
        item = PrescriptionItem.objects.create(prescription=rx, drug=drug, quantity=Decimal("21"))
        self.assertEqual(item.generic_name, "amoxicilina tri-hidratada")

    def test_prescription_item_serializer_exposes_structured_dose_fields(self):
        """PR C/3: the serializer must expose the structured dose fields as
        writable so the deterministic dose engine receives real values."""
        from apps.emr.serializers import PrescriptionItemSerializer

        fields = PrescriptionItemSerializer().get_fields()
        for name in ("dose_amount", "dose_unit", "route", "frequency_per_day"):
            self.assertIn(name, fields)
            self.assertFalse(fields[name].read_only, f"{name} must be writable")

        drug = Drug.objects.create(name="Vancomicina", generic_name="vancomicina")
        rx = Prescription.objects.create(
            encounter=self.encounter, patient=self.patient, prescriber=self.prescriber
        )
        # `prescription` is read-only (set by the viewset via save(prescription=...)),
        # mirroring PrescriptionItemViewSet.perform_create.
        serializer = PrescriptionItemSerializer(
            data={
                "drug": str(drug.id),
                "quantity": "1",
                "dose_amount": "500",
                "dose_unit": "mg",
                "route": "IV",
                "frequency_per_day": 3,
            }
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        item = serializer.save(prescription=rx)
        self.assertEqual(item.dose_amount, Decimal("500"))
        self.assertEqual(item.dose_unit, "mg")
        self.assertEqual(item.route, "IV")
        self.assertEqual(item.frequency_per_day, 3)


class TestPrescriptionSignAPI(TenantTestCase):
    def setUp(self):
        self.medico_user, self.enf_user, self.patient, self.prescriber, self.encounter = (
            _make_infra()
        )

    def _client(self, user):
        c = APIClient()
        c.defaults["SERVER_NAME"] = self.__class__.domain.domain
        c.force_authenticate(user=user)
        return c

    def test_prescription_sign_action_requires_emr_sign_role(self):
        """Enfermeiro (no emr.sign) must get 403 on sign."""
        rx = Prescription.objects.create(
            encounter=self.encounter, patient=self.patient, prescriber=self.prescriber
        )
        resp = self._client(self.enf_user).post(f"/api/v1/prescriptions/{rx.id}/sign/")
        self.assertEqual(resp.status_code, 403)

    def test_prescription_sign_action_succeeds_for_medico(self):
        """Médico (has emr.sign) can sign the prescription."""
        rx = Prescription.objects.create(
            encounter=self.encounter, patient=self.patient, prescriber=self.prescriber
        )
        resp = self._client(self.medico_user).post(f"/api/v1/prescriptions/{rx.id}/sign/")
        self.assertEqual(resp.status_code, 200)
        rx.refresh_from_db()
        self.assertEqual(rx.status, "signed")

    def test_add_item_to_signed_prescription_rejected(self):
        """Adding a PrescriptionItem to a signed Rx must return 400."""
        drug = Drug.objects.create(name="Drug For Signed Rx Test")
        rx = Prescription.objects.create(
            encounter=self.encounter, patient=self.patient, prescriber=self.prescriber
        )
        rx.sign(self.medico_user)
        resp = self._client(self.medico_user).post(
            "/api/v1/prescription-items/",
            {
                "prescription": str(rx.id),
                "drug": str(drug.id),
                "quantity": "2",
                "unit_of_measure": "un",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        import json

        body = json.dumps(resp.data).lower()
        self.assertIn("assinada", body)

    def test_patch_item_on_signed_prescription_rejected(self):
        """PATCHing an item on an ALREADY-SIGNED Rx must be rejected (signature
        integrity — no post-sign dose edit)."""
        drug = Drug.objects.create(name="Drug Patch Signed")
        rx = Prescription.objects.create(
            encounter=self.encounter, patient=self.patient, prescriber=self.prescriber
        )
        item = PrescriptionItem.objects.create(
            prescription=rx, drug=drug, quantity=2, unit_of_measure="un", dose_amount=5
        )
        rx.sign(self.medico_user)
        resp = self._client(self.medico_user).patch(
            f"/api/v1/prescription-items/{item.id}/",
            {"dose_amount": "999"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        import json

        self.assertIn("assinada", json.dumps(resp.data).lower())
        item.refresh_from_db()
        self.assertEqual(item.dose_amount, 5)

    def test_delete_item_on_signed_prescription_rejected(self):
        """DELETEing an item on an ALREADY-SIGNED Rx must be rejected."""
        drug = Drug.objects.create(name="Drug Delete Signed")
        rx = Prescription.objects.create(
            encounter=self.encounter, patient=self.patient, prescriber=self.prescriber
        )
        item = PrescriptionItem.objects.create(
            prescription=rx, drug=drug, quantity=2, unit_of_measure="un"
        )
        rx.sign(self.medico_user)
        resp = self._client(self.medico_user).delete(f"/api/v1/prescription-items/{item.id}/")
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(PrescriptionItem.objects.filter(id=item.id).exists())

    def test_patch_and_delete_item_on_draft_succeed(self):
        """On a DRAFT Rx, PATCH and DELETE of items work normally."""
        drug = Drug.objects.create(name="Drug Draft Edit")
        rx = Prescription.objects.create(
            encounter=self.encounter, patient=self.patient, prescriber=self.prescriber
        )
        item = PrescriptionItem.objects.create(
            prescription=rx, drug=drug, quantity=2, unit_of_measure="un", dose_amount=5
        )
        patch_resp = self._client(self.medico_user).patch(
            f"/api/v1/prescription-items/{item.id}/",
            {"dose_amount": "7"},
            format="json",
        )
        self.assertEqual(patch_resp.status_code, 200)
        item.refresh_from_db()
        self.assertEqual(item.dose_amount, 7)

        del_resp = self._client(self.medico_user).delete(f"/api/v1/prescription-items/{item.id}/")
        self.assertEqual(del_resp.status_code, 204)
        self.assertFalse(PrescriptionItem.objects.filter(id=item.id).exists())

    def test_patch_cannot_reparent_draft_item_onto_signed_prescription(self):
        """A PATCH must not move a draft item onto a SIGNED prescription
        (`prescription` is read-only) — otherwise it would mutate signed content
        past the signed-status guard."""
        drug = Drug.objects.create(name="Drug Reparent")
        draft_rx = Prescription.objects.create(
            encounter=self.encounter, patient=self.patient, prescriber=self.prescriber
        )
        signed_rx = Prescription.objects.create(
            encounter=self.encounter, patient=self.patient, prescriber=self.prescriber
        )
        signed_rx.sign(self.medico_user)
        item = PrescriptionItem.objects.create(
            prescription=draft_rx, drug=drug, quantity=1, unit_of_measure="un", dose_amount=5
        )
        self._client(self.medico_user).patch(
            f"/api/v1/prescription-items/{item.id}/",
            {"prescription": str(signed_rx.id), "dose_amount": "7"},
            format="json",
        )
        # The reparent is silently ignored (read-only field): the item stays on the
        # draft and no signed content is mutated.
        item.refresh_from_db()
        self.assertEqual(item.prescription_id, draft_rx.id)
        self.assertEqual(signed_rx.items.count(), 0)

    def test_prescription_create_infers_patient_and_prescriber_from_encounter(self):
        """Creating an Rx from CPOE only needs encounter; patient/prescriber come from it."""
        resp = self._client(self.medico_user).post(
            "/api/v1/prescriptions/",
            {"encounter": str(self.encounter.id)},
            format="json",
        )

        self.assertEqual(resp.status_code, 201)
        rx = Prescription.objects.get(id=resp.data["id"])
        self.assertEqual(rx.patient_id, self.patient.id)
        self.assertEqual(rx.prescriber_id, self.prescriber.id)

    def test_add_item_to_draft_prescription_saves_prescription_link(self):
        """CPOE item creation must persist the prescription FK from the request."""
        drug = Drug.objects.create(
            name="Dipirona 1g/mL",
            generic_name="Dipirona sódica",
            unit_of_measure="ampola",
        )
        rx = Prescription.objects.create(
            encounter=self.encounter, patient=self.patient, prescriber=self.prescriber
        )

        resp = self._client(self.medico_user).post(
            "/api/v1/prescription-items/",
            {
                "prescription": str(rx.id),
                "drug": str(drug.id),
                "quantity": "1",
                "unit_of_measure": "ampola",
                "dosage_instructions": "EV a cada 6h se dor ou febre",
            },
            format="json",
        )

        self.assertEqual(resp.status_code, 201)
        item = PrescriptionItem.objects.get(id=resp.data["id"])
        self.assertEqual(item.prescription_id, rx.id)
        self.assertEqual(item.generic_name, "Dipirona sódica")
