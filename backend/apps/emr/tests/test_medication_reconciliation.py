"""Sprint M1-S3-T1 — MedicationReconciliation + MedicationReconciliationItem.

Covers:
- a reconciliation is created for a patient's continuous-use meds, one decision
  item per medication, each recording an action + reason;
- the per-encounter/moment query returns the reconciliations for an encounter;
- completing freezes the reconciliation: its decision items become immutable
  (append-only clinical trail) and it cannot be re-completed.
"""

from django.core.exceptions import ValidationError

from apps.core.models import Role, User
from apps.core.permissions import DEFAULT_ROLES
from apps.emr.models import (
    Encounter,
    MedicationReconciliation,
    MedicationReconciliationItem,
    Patient,
    Professional,
)
from apps.test_utils import TenantTestCase


class MedicationReconciliationTests(TenantTestCase):
    def setUp(self):
        role = Role.objects.create(name="medico_recon", permissions=DEFAULT_ROLES["medico"])
        self.author = User.objects.create_user(email="recon_doc@t.com", password="pw", role=role)
        self.patient = Patient.objects.create(
            full_name="Recon Patient", birth_date="1970-05-10", gender="M", cpf="11122233344"
        )
        self.prof = Professional.objects.create(
            user=self.author, council_type="CRM", council_number="2020", council_state="SP"
        )
        self.encounter = Encounter.objects.create(
            patient=self.patient, professional=self.prof, chief_complaint="Internação"
        )

    def _reconciliation(self, moment=MedicationReconciliation.Moment.ADMISSION):
        return MedicationReconciliation.objects.create(
            patient=self.patient,
            encounter=self.encounter,
            moment=moment,
            author=self.author,
        )

    def test_reconciliation_captures_action_and_reason_per_medication(self):
        recon = self._reconciliation()
        MedicationReconciliationItem.objects.create(
            reconciliation=recon,
            medication_name="Losartana 50mg",
            action=MedicationReconciliationItem.Action.CONTINUE,
            reason="Manter anti-hipertensivo de uso contínuo.",
        )
        MedicationReconciliationItem.objects.create(
            reconciliation=recon,
            medication_name="Ibuprofeno 600mg",
            action=MedicationReconciliationItem.Action.STOP,
            reason="Suspender AINE por risco renal na internação.",
        )
        self.assertEqual(recon.items.count(), 2)
        stop = recon.items.get(medication_name="Ibuprofeno 600mg")
        self.assertEqual(stop.action, "stop")
        self.assertTrue(stop.reason)

    def test_per_encounter_query(self):
        adm = self._reconciliation(MedicationReconciliation.Moment.ADMISSION)
        dis = self._reconciliation(MedicationReconciliation.Moment.DISCHARGE)
        other_enc = Encounter.objects.create(
            patient=self.patient, professional=self.prof, chief_complaint="Outro"
        )
        MedicationReconciliation.objects.create(
            patient=self.patient,
            encounter=other_enc,
            moment=MedicationReconciliation.Moment.ADMISSION,
            author=self.author,
        )
        qs = MedicationReconciliation.objects.filter(encounter=self.encounter)
        self.assertEqual(set(qs.values_list("id", flat=True)), {adm.id, dis.id})

    def test_completed_reconciliation_is_immutable(self):
        recon = self._reconciliation()
        item = MedicationReconciliationItem.objects.create(
            reconciliation=recon,
            medication_name="Metformina 850mg",
            action=MedicationReconciliationItem.Action.CONTINUE,
            reason="Manter.",
        )
        recon.complete()
        self.assertTrue(recon.is_completed)

        # No new decisions after completion.
        with self.assertRaises(ValidationError):
            MedicationReconciliationItem.objects.create(
                reconciliation=recon,
                medication_name="AAS 100mg",
                action=MedicationReconciliationItem.Action.START,
            )
        # Existing decisions cannot be mutated or deleted.
        item.action = MedicationReconciliationItem.Action.STOP
        with self.assertRaises(ValidationError):
            item.save()
        with self.assertRaises(ValidationError):
            item.delete()

    def test_cannot_re_complete(self):
        recon = self._reconciliation()
        recon.complete()
        with self.assertRaises(ValidationError):
            recon.complete()
