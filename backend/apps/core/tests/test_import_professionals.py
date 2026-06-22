import os
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError

from apps.core.models import Role, User
from apps.hr.models import Employee
from apps.test_utils import TenantTestCase


class TestImportProfessionals(TenantTestCase):
    def setUp(self):
        super().setUp()
        Role.objects.create(name="medico")
        self.csv_content = "email;nome;cargo;data_contratacao;conselho;numero_conselho;uf_conselho\nteste1@example.com;Medico A;medico;2024-01-01;CRM;12345;SP\n"
        self.csv_file = "/tmp/" + self.tenant.schema_name + "_test_prof.csv"
        with open(self.csv_file, "w") as f:
            f.write(self.csv_content)

    def tearDown(self):
        if os.path.exists(self.csv_file):
            os.remove(self.csv_file)
        super().tearDown()

    def test_import_professionals_success(self):
        out = StringIO()
        # Ensure we have a requesting user
        if not User.objects.filter(email="admin@example.com").exists():
            u = User.objects.create(email="admin@example.com", full_name="Admin")
            from apps.core.models import UserTenantMembership
            UserTenantMembership.objects.create(user=u, tenant=self.tenant)
        call_command("import_professionals", file=self.csv_file, tenant=self.tenant.schema_name, stdout=out)
        self.assertIn("Done: 1 created", out.getvalue())
        self.assertEqual(Employee.objects.count(), 1)
        e = Employee.objects.first()
        self.assertEqual(e.user.email, "teste1@example.com")

    def test_import_professionals_error(self):
        with open(self.csv_file, "w") as f:
            f.write("nome;cargo\nIncompleto;medico\n")
        with self.assertRaises(CommandError) as e:
            call_command("import_professionals", file=self.csv_file, tenant=self.tenant.schema_name)
        self.assertIn("email missing", str(e.exception))
