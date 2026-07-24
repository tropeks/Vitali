"""
E1-T5 — loose CID-10 usage migrated to governed FK/M2M on core.CID10Code.

Covers: attach via FK (MedicalHistory) and M2M (SOAPNote); the cid10_code /
cid10_codes backward-compat shims (matched → FK/M2M, unmatched → legacy + flag);
the cross-schema delete-protection signal (referenced CID cannot be deleted); and
the reconcile helpers used by the data migration (matched + unmatched preserved).
"""

from django.db import transaction
from django.db.models.deletion import ProtectedError

from apps.core.models import CID10Code
from apps.emr.cid_backfill import reconcile_medical_history, reconcile_soap_note
from apps.emr.models import (
    Encounter,
    MedicalHistory,
    Patient,
    Professional,
    SOAPNote,
    SOAPNoteCID10,
)
from apps.test_utils import TenantTestCase


def _patient():
    return Patient.objects.create(
        full_name="CID FK Patient", birth_date="1980-01-01", gender="F", cpf="44444444444"
    )


def _encounter(patient):
    from apps.core.models import Role, User

    role = Role.objects.create(name="medico_cidfk", permissions=["emr.read", "emr.write"])
    user = User.objects.create_user(email="cidfk@t.com", password="pw", role=role)
    prof = Professional.objects.create(
        user=user, council_type="CRM", council_number="123", council_state="SP"
    )
    return Encounter.objects.create(patient=patient, professional=prof)


class TestMedicalHistoryFK(TenantTestCase):
    def test_attach_valid_cid_via_fk(self):
        cid = CID10Code.objects.create(code="J45", description="Asma")
        mh = MedicalHistory.objects.create(
            patient=_patient(), condition="Asma", type="chronic", cid10=cid
        )
        mh.refresh_from_db()
        self.assertEqual(mh.cid10_id, cid.id)
        self.assertEqual(mh.cid10_code, "J45")  # compat property

    def test_cid10_code_setter_matches_governed_code(self):
        CID10Code.objects.create(code="J45", description="Asma")
        mh = MedicalHistory.objects.create(
            patient=_patient(), condition="Asma", type="chronic", cid10_code="J45"
        )
        mh.refresh_from_db()
        self.assertIsNotNone(mh.cid10_id)
        self.assertEqual(mh.legacy_cid_text, "")
        self.assertFalse(mh.cid_unmatched)

    def test_cid10_code_setter_preserves_unmatched(self):
        # No CID10Code seeded → the raw code is preserved, never lost.
        mh = MedicalHistory.objects.create(
            patient=_patient(), condition="Cond", type="chronic", cid10_code="ZZZ99"
        )
        mh.refresh_from_db()
        self.assertIsNone(mh.cid10_id)
        self.assertEqual(mh.legacy_cid_text, "ZZZ99")
        self.assertTrue(mh.cid_unmatched)
        self.assertEqual(mh.cid10_code, "ZZZ99")  # still readable

    def test_blank_cid_clears(self):
        mh = MedicalHistory.objects.create(
            patient=_patient(), condition="Cond", type="chronic", cid10_code=""
        )
        self.assertIsNone(mh.cid10_id)
        self.assertEqual(mh.legacy_cid_text, "")
        self.assertFalse(mh.cid_unmatched)


class TestSOAPNoteM2M(TenantTestCase):
    def setUp(self):
        self.encounter = _encounter(_patient())

    def test_attach_cids_via_m2m(self):
        c1 = CID10Code.objects.create(code="J45", description="Asma")
        c2 = CID10Code.objects.create(code="E11", description="Diabetes")
        soap = SOAPNote.objects.create(encounter=self.encounter)
        soap.cid10.add(c1, c2)
        codes = set(soap.cid10_codes)
        self.assertIn("J45", codes)
        self.assertIn("E11", codes)
        self.assertEqual(SOAPNoteCID10.objects.filter(soap_note=soap).count(), 2)

    def test_compat_list_includes_legacy(self):
        c1 = CID10Code.objects.create(code="J45", description="Asma")
        soap = SOAPNote.objects.create(
            encounter=self.encounter, legacy_cid_codes=["XYZ00"], cid_unmatched=True
        )
        soap.cid10.add(c1)
        self.assertIn("J45", soap.cid10_codes)
        self.assertIn("XYZ00", soap.cid10_codes)


class TestCID10DeleteProtection(TenantTestCase):
    def test_delete_blocked_when_referenced_by_medical_history(self):
        cid = CID10Code.objects.create(code="J45", description="Asma")
        MedicalHistory.objects.create(
            patient=_patient(), condition="Asma", type="chronic", cid10=cid
        )
        with self.assertRaises(ProtectedError) as ctx, transaction.atomic():
            cid.delete()
        self.assertIn("MedicalHistory", str(ctx.exception))
        self.assertTrue(CID10Code.objects.filter(pk=cid.pk).exists())

    def test_delete_blocked_when_referenced_by_soap(self):
        cid = CID10Code.objects.create(code="E11", description="Diabetes")
        soap = SOAPNote.objects.create(encounter=_encounter(_patient()))
        soap.cid10.add(cid)
        with self.assertRaises(ProtectedError) as ctx, transaction.atomic():
            cid.delete()
        self.assertIn("SOAPNote", str(ctx.exception))
        self.assertTrue(CID10Code.objects.filter(pk=cid.pk).exists())

    def test_delete_allowed_when_unreferenced(self):
        cid = CID10Code.objects.create(code="Z00", description="Unreferenced")
        cid.delete()
        self.assertFalse(CID10Code.objects.filter(pk=cid.pk).exists())


class TestReconcileHelpers(TenantTestCase):
    def test_reconcile_medical_history_matches_and_preserves(self):
        CID10Code.objects.create(code="J45", description="Asma")
        matched = MedicalHistory.objects.create(
            patient=_patient(), condition="Asma", type="chronic", legacy_cid_text="J45"
        )
        unmatched = MedicalHistory.objects.create(
            patient=_patient(), condition="Outro", type="chronic", legacy_cid_text="ZZZ99"
        )
        linked, unmatched_count = reconcile_medical_history(MedicalHistory, CID10Code)
        self.assertEqual((linked, unmatched_count), (1, 1))
        matched.refresh_from_db()
        unmatched.refresh_from_db()
        self.assertEqual(matched.cid10.code, "J45")
        self.assertEqual(matched.legacy_cid_text, "")
        self.assertFalse(matched.cid_unmatched)
        self.assertIsNone(unmatched.cid10_id)
        self.assertEqual(unmatched.legacy_cid_text, "ZZZ99")
        self.assertTrue(unmatched.cid_unmatched)

    def test_reconcile_soap_note_matches_and_preserves(self):
        CID10Code.objects.create(code="J45", description="Asma")
        soap = SOAPNote.objects.create(
            encounter=_encounter(_patient()), legacy_cid_codes=["J45", "ZZZ99"]
        )
        linked, unmatched = reconcile_soap_note(SOAPNote, CID10Code, SOAPNoteCID10)
        self.assertEqual((linked, unmatched), (1, 1))
        soap.refresh_from_db()
        self.assertEqual([c.code for c in soap.cid10.all()], ["J45"])
        self.assertEqual(soap.legacy_cid_codes, ["ZZZ99"])
        self.assertTrue(soap.cid_unmatched)
