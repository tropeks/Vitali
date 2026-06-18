import os
from io import StringIO
from django.core.management import call_command
from django.core.management.base import CommandError
from apps.test_utils import TenantTestCase
from apps.emr.models import Patient

class TestImportPatients(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.csv_content = "cpf;nome;data_nascimento;sexo\n11111111111;Joao Silva;1990-01-01;M\n22222222222;Maria Souza;1985-12-31;F\n"
        self.csv_file = "/tmp/" + self.tenant.schema_name + "_test_pat.csv"
        with open(self.csv_file, "w") as f:
            f.write(self.csv_content)

    def tearDown(self):
        if os.path.exists(self.csv_file):
            os.remove(self.csv_file)
        super().tearDown()

    def test_import_patients_success(self):
        out = StringIO()
        call_command("import_patients", file=self.csv_file, tenant=self.tenant.schema_name, stdout=out)
        self.assertIn("Done: 2 created", out.getvalue())
        p = Patient.objects.all()
        cpfs = [x.cpf for x in p]
        self.assertIn("11111111111", cpfs)
        self.assertIn("22222222222", cpfs)

    def test_import_patients_update(self):
        Patient.objects.create(cpf="11111111111", full_name="Old Name", birth_date="1990-01-01", gender="M")
        out = StringIO()
        call_command("import_patients", file=self.csv_file, tenant=self.tenant.schema_name, stdout=out)
        self.assertIn("1 created, 1 updated", out.getvalue())
        p = [x for x in Patient.objects.all() if x.cpf == "11111111111"][0]
        self.assertEqual(p.full_name, "Joao Silva")

    def test_import_patients_error(self):
        with open(self.csv_file, "w") as f:
            f.write("nome;data_nascimento\nJoao Silva;1990-01-01\n")
        with self.assertRaises(CommandError) as e:
            call_command("import_patients", file=self.csv_file, tenant=self.tenant.schema_name)
        self.assertIn("cpf missing", str(e.exception))
