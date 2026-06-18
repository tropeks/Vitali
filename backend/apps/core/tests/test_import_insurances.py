import os
from io import StringIO
from django.core.management import call_command
from django.core.management.base import CommandError
from apps.test_utils import TenantTestCase
from apps.billing.models import InsuranceProvider

class TestImportInsurances(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.csv_content = "codigo_ans;nome;cnpj;ativo\n123456;Plano A;00.000.000/0001-00;true\n654321;Plano B;;false\n"
        self.csv_file = "/tmp/" + self.tenant.schema_name + "_test_ins.csv"
        with open(self.csv_file, "w") as f:
            f.write(self.csv_content)

    def tearDown(self):
        if os.path.exists(self.csv_file):
            os.remove(self.csv_file)
        super().tearDown()

    def test_import_insurances_success(self):
        out = StringIO()
        call_command("import_insurances", file=self.csv_file, tenant=self.tenant.schema_name, stdout=out)
        self.assertIn("Done: 2 created", out.getvalue())
        self.assertEqual(InsuranceProvider.objects.count(), 2)
        p = InsuranceProvider.objects.get(ans_code="123456")
        self.assertEqual(p.name, "Plano A")
        self.assertTrue(p.is_active)

    def test_import_insurances_update(self):
        InsuranceProvider.objects.create(ans_code="123456", name="Old Name")
        out = StringIO()
        call_command("import_insurances", file=self.csv_file, tenant=self.tenant.schema_name, stdout=out)
        p = InsuranceProvider.objects.get(ans_code="123456")
        self.assertEqual(p.name, "Plano A")
        self.assertIn("1 created, 1 updated", out.getvalue())

    def test_import_insurances_error(self):
        with open(self.csv_file, "w") as f:
            f.write("nome;ativo\nPlano C;true\n")
        with self.assertRaises(CommandError) as e:
            call_command("import_insurances", file=self.csv_file, tenant=self.tenant.schema_name)
        self.assertIn("ans_code missing", str(e.exception))
