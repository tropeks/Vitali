"""E2-T3 — Immunization: create/read + per-patient immunization history."""

from apps.emr.models import Immunization, Patient
from apps.test_utils import TenantTestCase


def _patient(cpf="88888888888"):
    return Patient.objects.create(
        full_name="Vaccine Patient", birth_date="2020-05-05", gender="F", cpf=cpf
    )


class TestImmunization(TenantTestCase):
    def test_create_and_read(self):
        p = _patient()
        imm = Immunization.objects.create(
            patient=p,
            immunobiological="Tríplice viral (SCR)",
            dose_number="1ª dose",
            lot="ABC123",
            manufacturer="Bio-Manguinhos",
            date="2021-05-05",
            pni_calendar_reference="SCR-12m",
        )
        imm.refresh_from_db()
        self.assertEqual(imm.immunobiological, "Tríplice viral (SCR)")
        self.assertEqual(imm.dose_number, "1ª dose")
        self.assertEqual(imm.lot, "ABC123")
        self.assertEqual(imm.pni_calendar_reference, "SCR-12m")

    def test_per_patient_history_ordered_by_date_desc(self):
        p = _patient()
        other = _patient(cpf="88888888889")
        Immunization.objects.create(patient=p, immunobiological="BCG", date="2020-05-06")
        Immunization.objects.create(patient=p, immunobiological="Hepatite B", date="2021-01-10")
        Immunization.objects.create(patient=other, immunobiological="BCG", date="2020-01-01")

        history = list(Immunization.objects.filter(patient=p))
        self.assertEqual(len(history), 2)
        # ordering = -date → most recent first
        self.assertEqual(history[0].immunobiological, "Hepatite B")
        self.assertEqual(history[1].immunobiological, "BCG")
