"""
N2-T1 — SAE executable domain models + cross-schema catalog PROTECT.

Covers the tenant-side SAE graph (diagnóstico → planejamento(NOC) → intervenção(NIC)
→ prescrição → evolução) built on the SHARED NANDA/NIC/NOC catalogs, the governed
cross-schema FKs with backward-compatible ``*_code`` accessors (matched → FK,
unmatched → legacy text + flag), and the three ``pre_delete`` PROTECT signals that
block hard-deleting a catalog row any tenant references (mirrors CBO/CNES).
"""

from django.db import transaction
from django.db.models.deletion import ProtectedError

from apps.core.models import NandaDiagnosis, NicIntervention, NocOutcome, Role, User
from apps.emr.models import (
    Encounter,
    NursingCareplan,
    NursingCareplanIntervention,
    NursingDiagnosis,
    NursingEvolution,
    NursingPrescriptionItem,
    Patient,
    Professional,
)
from apps.test_utils import TenantTestCase


def _user(email):
    role = Role.objects.create(name=f"role-{email}", permissions=[])
    return User.objects.create_user(email=email, password="pw", role=role)


def _infra(email="enf@x.com"):
    user = _user(email)
    patient = Patient.objects.create(
        full_name="SAE Patient", birth_date="1990-01-01", gender="F", cpf="33333333333"
    )
    prof = Professional.objects.create(
        user=user, council_type="COREN", council_number="9", council_state="SP"
    )
    encounter = Encounter.objects.create(patient=patient, professional=prof)
    return user, patient, encounter


class TestSAEGraph(TenantTestCase):
    def test_full_graph_diagnosis_to_evolution(self):
        user, patient, encounter = _infra()
        nanda = NandaDiagnosis.objects.create(code="00132", display="Dor aguda")
        noc = NocOutcome.objects.create(code="2102", display="Nível de dor")
        nic = NicIntervention.objects.create(code="1400", display="Controle da dor")

        dx = NursingDiagnosis.objects.create(
            patient=patient,
            encounter=encounter,
            nanda=nanda,
            related_factors="agente lesivo",
            priority=NursingDiagnosis.Priority.HIGH,
            created_by=user,
        )
        plan = NursingCareplan.objects.create(
            diagnosis=dx, noc=noc, target="dor ≤ 2 em 48h", created_by=user
        )
        interv = NursingCareplanIntervention.objects.create(careplan=plan, nic=nic)
        item = NursingPrescriptionItem.objects.create(
            intervention=interv,
            description="Verificar sinais vitais",
            frequency_hours=6,
            start_at="2026-07-24T08:00:00Z",
            created_by=user,
        )
        evo = NursingEvolution.objects.create(
            patient=patient, encounter=encounter, text="Paciente refere melhora.", created_by=user
        )

        dx.refresh_from_db()
        self.assertEqual(dx.nanda_id, nanda.pk)
        self.assertEqual(dx.status, "active")
        self.assertEqual(dx.priority, "high")
        self.assertEqual(dx.careplans.get().noc_id, noc.pk)
        self.assertEqual(plan.interventions.get().nic_id, nic.pk)
        self.assertEqual(interv.prescription_items.get().frequency_hours, 6)
        self.assertEqual(item.intervention_id, interv.pk)
        evo.refresh_from_db()
        self.assertEqual(evo.text, "Paciente refere melhora.")

    def test_catalog_fks_nullable_and_code_accessor_default(self):
        user, patient, encounter = _infra("enf2@x.com")
        dx = NursingDiagnosis.objects.create(patient=patient, encounter=encounter, created_by=user)
        self.assertIsNone(dx.nanda_id)
        self.assertEqual(dx.nanda_code, "")

    def test_nanda_code_setter_matches_and_preserves_unmatched(self):
        user, patient, encounter = _infra("enf3@x.com")
        NandaDiagnosis.objects.create(code="00132", display="Dor aguda")

        matched = NursingDiagnosis(patient=patient, encounter=encounter, created_by=user)
        matched.nanda_code = "00132"
        matched.save()
        matched.refresh_from_db()
        self.assertEqual(matched.nanda_id, NandaDiagnosis.objects.get(code="00132").pk)
        self.assertFalse(matched.nanda_unmatched)
        self.assertEqual(matched.nanda_code, "00132")

        unmatched = NursingDiagnosis(patient=patient, encounter=encounter, created_by=user)
        unmatched.nanda_code = "99999"
        unmatched.save()
        unmatched.refresh_from_db()
        self.assertIsNone(unmatched.nanda_id)
        self.assertEqual(unmatched.legacy_nanda_text, "99999")
        self.assertTrue(unmatched.nanda_unmatched)
        self.assertEqual(unmatched.nanda_code, "99999")

    def test_noc_and_nic_code_setters(self):
        user, patient, encounter = _infra("enf4@x.com")
        NocOutcome.objects.create(code="2102", display="Nível de dor")
        NicIntervention.objects.create(code="1400", display="Controle da dor")
        dx = NursingDiagnosis.objects.create(patient=patient, encounter=encounter, created_by=user)

        plan = NursingCareplan(diagnosis=dx, created_by=user)
        plan.noc_code = "2102"
        plan.save()
        plan.refresh_from_db()
        self.assertEqual(plan.noc_id, NocOutcome.objects.get(code="2102").pk)
        self.assertEqual(plan.noc_code, "2102")

        interv = NursingCareplanIntervention(careplan=plan)
        interv.nic_code = "1400"
        interv.save()
        interv.refresh_from_db()
        self.assertEqual(interv.nic_id, NicIntervention.objects.get(code="1400").pk)
        self.assertEqual(interv.nic_code, "1400")


class TestSAECatalogDeleteProtection(TenantTestCase):
    def test_nanda_delete_blocked_when_referenced(self):
        user, patient, encounter = _infra("del1@x.com")
        nanda = NandaDiagnosis.objects.create(code="00132", display="Dor aguda")
        NursingDiagnosis.objects.create(
            patient=patient, encounter=encounter, nanda=nanda, created_by=user
        )
        with self.assertRaises(ProtectedError) as ctx, transaction.atomic():
            nanda.delete()
        self.assertIn("NandaDiagnosis", str(ctx.exception))
        self.assertIn("NursingDiagnosis", str(ctx.exception))
        self.assertTrue(NandaDiagnosis.objects.filter(pk=nanda.pk).exists())

    def test_nanda_delete_allowed_when_unreferenced(self):
        nanda = NandaDiagnosis.objects.create(code="00001", display="Sem uso")
        nanda.delete()
        self.assertFalse(NandaDiagnosis.objects.filter(pk=nanda.pk).exists())

    def test_noc_delete_blocked_when_referenced(self):
        user, patient, encounter = _infra("del2@x.com")
        noc = NocOutcome.objects.create(code="2102", display="Nível de dor")
        dx = NursingDiagnosis.objects.create(patient=patient, encounter=encounter, created_by=user)
        NursingCareplan.objects.create(diagnosis=dx, noc=noc, created_by=user)
        with self.assertRaises(ProtectedError) as ctx, transaction.atomic():
            noc.delete()
        self.assertIn("NocOutcome", str(ctx.exception))
        self.assertIn("NursingCareplan", str(ctx.exception))
        self.assertTrue(NocOutcome.objects.filter(pk=noc.pk).exists())

    def test_nic_delete_blocked_when_referenced(self):
        user, patient, encounter = _infra("del3@x.com")
        nic = NicIntervention.objects.create(code="1400", display="Controle da dor")
        dx = NursingDiagnosis.objects.create(patient=patient, encounter=encounter, created_by=user)
        plan = NursingCareplan.objects.create(diagnosis=dx, created_by=user)
        NursingCareplanIntervention.objects.create(careplan=plan, nic=nic)
        with self.assertRaises(ProtectedError) as ctx, transaction.atomic():
            nic.delete()
        self.assertIn("NicIntervention", str(ctx.exception))
        self.assertIn("NursingCareplanIntervention", str(ctx.exception))
        self.assertTrue(NicIntervention.objects.filter(pk=nic.pk).exists())
