"""Tests for Patient Rights (Export and Deletion Request)."""

from __future__ import annotations

from rest_framework.test import APIClient

from apps.core.models import AuditLog, FeatureFlag, Role, User
from apps.emr.models import Patient
from apps.patient_portal.models import PatientPortalAccess
from apps.test_utils import TenantTestCase

EXPORT_URL = "/api/v1/portal/me/export/"
DELETE_REQ_URL = "/api/v1/portal/me/delete-request/"


def _make_user(*, role_name: str, perms: list[str], email: str, full_name: str) -> User:
    role, _ = Role.objects.get_or_create(name=role_name, defaults={"permissions": perms})
    role.permissions = perms
    role.save()
    return User.objects.create_user(email=email, password="pw", role=role, full_name=full_name)


class PatientRightsTest(TenantTestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key="patient_portal",
            defaults={"is_enabled": True},
        )

        self.patient = Patient.objects.create(
            full_name="Carlos Mendes", cpf="99988877766", birth_date="1980-01-01"
        )
        self.portal_user = _make_user(
            role_name="portal_user",
            perms=["portal.self_access"],
            email="carlos@test.com",
            full_name="Carlos Mendes",
        )
        self.access = PatientPortalAccess.objects.create(
            user=self.portal_user,
            patient=self.patient,
        )
        self.access.activate()  # Status -> active
        self.client.force_authenticate(user=self.portal_user)

    def test_export_json(self):
        res = self.client.get(f"{EXPORT_URL}?export_format=json")
        self.assertEqual(res.status_code, 200)
        self.assertIn("patient", res.data)
        self.assertIn("appointments", res.data)
        self.assertEqual(res.data["patient"]["full_name"], "Carlos Mendes")

    def test_export_pdf(self):
        res = self.client.get(f"{EXPORT_URL}?export_format=pdf")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res["Content-Type"], "application/pdf")
        self.assertIn('attachment; filename="patient_export_', res["Content-Disposition"])

    def test_exportar_o_prontuario_deixa_trilha_apontando_o_titular(self):
        """Ordem 030: o export LGPD é a cópia mais ampla do prontuário que sai do
        sistema (cadastro, agenda, atendimentos, receitas, alergias) e não
        deixava rastro. O leitor é o próprio titular; o alvo em `resource_id` é
        o paciente dele, para `/audit-trail/?patient=` achar a leitura."""
        res = self.client.get(f"{EXPORT_URL}?export_format=json")
        self.assertEqual(res.status_code, 200)

        log = AuditLog.objects.get(action="view_record_list", resource_type="PortalExport")
        self.assertEqual(log.resource_id, str(self.patient.pk))
        self.assertEqual(log.user, self.portal_user)
        self.assertEqual(log.new_data, {"export_format": "json"})

    def test_exportar_em_pdf_tambem_deixa_trilha(self):
        """O ramo PDF devolve `HttpResponse` cru, não `Response` do DRF — a
        trilha passa pelo mesmo `finalize_response` (revisão da 030)."""
        res = self.client.get(f"{EXPORT_URL}?export_format=pdf")
        self.assertEqual(res.status_code, 200)

        log = AuditLog.objects.get(action="view_record_list", resource_type="PortalExport")
        self.assertEqual(log.resource_id, str(self.patient.pk))
        self.assertEqual(log.new_data, {"export_format": "pdf"})

    def test_deletion_request(self):
        self.assertEqual(AuditLog.objects.filter(action="patient_deletion_requested").count(), 0)
        res = self.client.post(DELETE_REQ_URL, {"reason": "Privacy concerns"})
        self.assertEqual(res.status_code, 200)
        self.assertIn("retenção legal", res.data["detail"].lower())

        logs = AuditLog.objects.filter(action="patient_deletion_requested")
        self.assertEqual(logs.count(), 1)
        log = logs.first()
        self.assertEqual(log.resource_type, "Patient")
        self.assertEqual(log.resource_id, str(self.patient.id))
        self.assertEqual(log.new_data["reason"], "Privacy concerns")
