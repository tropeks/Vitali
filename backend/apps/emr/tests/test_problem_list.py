"""E2-T1 — ProblemListItem: governed CID-10 FK + FHIR Condition semantics.

Covers: create with a valid governed CID; an invalid/absent CID is preserved as
legacy (never blocks, never lost) via the cid10_code shim; the cross-schema
delete-protection sibling signal blocks deleting a referenced CID; clinical /
verification status transitions; and the active-problem query for a patient.
"""

from django.db import transaction
from django.db.models.deletion import ProtectedError

from apps.core.models import CID10Code
from apps.emr.models import Patient, ProblemListItem
from apps.test_utils import TenantTestCase


def _patient(cpf="55555555555"):
    return Patient.objects.create(
        full_name="Problem Patient", birth_date="1980-01-01", gender="F", cpf=cpf
    )


class TestProblemListItemCID(TenantTestCase):
    def test_create_with_valid_cid_via_fk(self):
        cid = CID10Code.objects.create(code="I10", description="Hipertensão essencial")
        p = ProblemListItem.objects.create(patient=_patient(), condition="Hipertensão", cid10=cid)
        p.refresh_from_db()
        self.assertEqual(p.cid10_id, cid.id)
        self.assertEqual(p.cid10_code, "I10")

    def test_cid10_code_setter_matches_governed_code(self):
        CID10Code.objects.create(code="E11", description="Diabetes")
        p = ProblemListItem.objects.create(
            patient=_patient(), condition="Diabetes", cid10_code="E11"
        )
        p.refresh_from_db()
        self.assertIsNotNone(p.cid10_id)
        self.assertEqual(p.legacy_cid_text, "")
        self.assertFalse(p.cid_unmatched)

    def test_invalid_cid_is_preserved_as_legacy_not_lost(self):
        # No governed code seeded → the raw code is preserved, flagged, never lost.
        p = ProblemListItem.objects.create(patient=_patient(), condition="Algo", cid10_code="ZZZ99")
        p.refresh_from_db()
        self.assertIsNone(p.cid10_id)
        self.assertEqual(p.legacy_cid_text, "ZZZ99")
        self.assertTrue(p.cid_unmatched)
        self.assertEqual(p.cid10_code, "ZZZ99")


class TestProblemListItemStatus(TenantTestCase):
    def test_defaults_are_active_and_provisional(self):
        p = ProblemListItem.objects.create(patient=_patient(), condition="Cefaleia")
        self.assertEqual(p.clinical_status, ProblemListItem.ClinicalStatus.ACTIVE)
        self.assertEqual(p.verification_status, ProblemListItem.VerificationStatus.PROVISIONAL)
        self.assertTrue(p.is_active)

    def test_clinical_and_verification_transitions(self):
        p = ProblemListItem.objects.create(patient=_patient(), condition="Cefaleia")
        p.verification_status = ProblemListItem.VerificationStatus.CONFIRMED
        p.clinical_status = ProblemListItem.ClinicalStatus.RESOLVED
        p.abatement_date = "2026-07-01"
        p.save()
        p.refresh_from_db()
        self.assertEqual(p.verification_status, "confirmed")
        self.assertEqual(p.clinical_status, "resolved")
        self.assertFalse(p.is_active)
        self.assertIsNotNone(p.abatement_date)

    def test_active_problems_query_for_patient(self):
        patient = _patient()
        other = _patient(cpf="66666666666")
        ProblemListItem.objects.create(patient=patient, condition="Ativo 1")
        ProblemListItem.objects.create(
            patient=patient,
            condition="Resolvido",
            clinical_status=ProblemListItem.ClinicalStatus.RESOLVED,
        )
        ProblemListItem.objects.create(patient=other, condition="Outro paciente")

        active = ProblemListItem.objects.filter(
            patient=patient, clinical_status=ProblemListItem.ClinicalStatus.ACTIVE
        )
        self.assertEqual(active.count(), 1)
        self.assertEqual(active.first().condition, "Ativo 1")


class TestProblemListItemCIDDeleteProtection(TenantTestCase):
    def test_delete_blocked_when_referenced_by_problem(self):
        cid = CID10Code.objects.create(code="J45", description="Asma")
        ProblemListItem.objects.create(patient=_patient(), condition="Asma", cid10=cid)
        with self.assertRaises(ProtectedError) as ctx, transaction.atomic():
            cid.delete()
        self.assertIn("ProblemListItem", str(ctx.exception))
        self.assertTrue(CID10Code.objects.filter(pk=cid.pk).exists())

    def test_delete_allowed_when_unreferenced(self):
        cid = CID10Code.objects.create(code="Z00", description="Unreferenced")
        cid.delete()
        self.assertFalse(CID10Code.objects.filter(pk=cid.pk).exists())
