import datetime
from concurrent.futures import ThreadPoolExecutor

from django.db import close_old_connections
from django_tenants.utils import schema_context

from apps.test_utils import TenantTestCase


def _cpf(seed):
    return f"{90000000000 + seed:011d}"


class TestPatientMRNGeneration(TenantTestCase):
    def test_concurrent_patient_creation_generates_unique_mrns(self):
        from apps.emr.models import Patient

        schema_name = self.__class__.tenant.schema_name

        def create_patient(index):
            close_old_connections()
            try:
                with schema_context(schema_name):
                    patient = Patient.objects.create(
                        full_name=f"Paciente Concorrente {index}",
                        cpf=_cpf(index),
                        birth_date=datetime.date(1990, 1, 1),
                        gender="F",
                    )
                    return patient.medical_record_number
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=8) as executor:
            mrns = list(executor.map(create_patient, range(1, 9)))

        self.assertEqual(len(mrns), 8)
        self.assertEqual(len(set(mrns)), 8)
        for mrn in mrns:
            self.assertRegex(mrn, r"^PAC-\d{4}-\d{5}$")
