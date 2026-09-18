"""CFM Res. 1.821 — clinical record READ access must be audited (view_record)."""

import datetime

from rest_framework.test import APIRequestFactory, force_authenticate

from apps.test_utils import TenantTestCase


class TestAuditReadLogging(TenantTestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model

        from apps.emr.models import Patient

        User = get_user_model()
        # Superuser so HasPermission("emr.read") passes without role wiring.
        self.user = User.objects.create_user(
            email="auditor@clinic.test",
            password="TestPass123!",
            full_name="Auditor",
            is_staff=True,
            is_superuser=True,
        )
        self.patient = Patient.objects.create(
            full_name="Paciente Auditado",
            cpf="99999999901",
            birth_date=datetime.date(1990, 1, 1),
            gender="F",
        )

    def test_retrieve_patient_writes_view_record_audit(self):
        from apps.core.models import AuditLog
        from apps.emr.views import PatientViewSet

        request = APIRequestFactory().get(f"/api/v1/patients/{self.patient.id}/")
        force_authenticate(request, user=self.user)
        response = PatientViewSet.as_view({"get": "retrieve"})(request, pk=str(self.patient.id))

        self.assertEqual(response.status_code, 200)
        logs = AuditLog.objects.filter(
            action="view_record",
            resource_type="Patient",
            resource_id=str(self.patient.id),
        )
        self.assertEqual(logs.count(), 1)
        self.assertEqual(logs.first().user, self.user)

    def test_list_does_not_write_view_record_audit(self):
        """Listar não é `retrieve`: nunca grava `view_record` (grava, isto sim,
        `view_record_list` — ver `test_unfiltered_list_writes_view_record_list_audit`
        abaixo, ordem 019 item 1)."""
        from apps.core.models import AuditLog
        from apps.emr.views import PatientViewSet

        request = APIRequestFactory().get("/api/v1/patients/")
        force_authenticate(request, user=self.user)
        response = PatientViewSet.as_view({"get": "list"})(request)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(AuditLog.objects.filter(action="view_record").exists())

    def test_unfiltered_list_writes_view_record_list_audit(self):
        """Ordem 019 item 1 — `PatientViewSet.AUDIT_LIST_ALWAYS = True`: passear
        pelo rol de pacientes SEM filtro passa a deixar rastro, porque o próprio
        listar já é o acesso sensível (nome, prontuário de cada linha)."""
        from apps.core.models import AuditLog
        from apps.emr.views import PatientViewSet

        request = APIRequestFactory().get("/api/v1/patients/")
        force_authenticate(request, user=self.user)
        response = PatientViewSet.as_view({"get": "list"})(request)

        self.assertEqual(response.status_code, 200)
        log = AuditLog.objects.get(action="view_record_list", resource_type="Patient")
        self.assertEqual(log.user, self.user)
        # Sem critério — new_data fica vazio, resource_id fica vazio: o que
        # importa é QUE o rol inteiro foi listado, não um paciente específico.
        self.assertEqual(log.new_data, {})
        self.assertEqual(log.resource_id, "")

    def test_filtered_list_still_logs_the_criterion(self):
        """`AUDIT_LIST_ALWAYS` não apaga o comportamento anterior — o critério
        continua indo para `new_data` quando presente."""
        from apps.core.models import AuditLog
        from apps.emr.views import PatientViewSet

        request = APIRequestFactory().get(f"/api/v1/patients/?search={self.patient.full_name}")
        force_authenticate(request, user=self.user)
        response = PatientViewSet.as_view({"get": "list"})(request)

        self.assertEqual(response.status_code, 200)
        log = AuditLog.objects.get(action="view_record_list", resource_type="Patient")
        self.assertEqual(log.new_data, {"search": self.patient.full_name})

    def test_timeline_allergies_medical_history_insurance_write_view_record_audit(self):
        """Ordem 019 item 2 — as quatro `@action` de detalhe de PatientViewSet
        que leem prontuário e não são `retrieve`/`list`.

        `AuditLog` é append-only (ordem 020 — trigger bloqueia DELETE), então em
        vez de limpar a tabela entre iterações, cada rodada compara pelo maior
        `id` visto até então — a linha nova é a que ficou acima da marca.
        """
        from apps.core.models import AuditLog
        from apps.emr.views import PatientViewSet

        for action_name in ("timeline", "allergies", "medical_history", "insurance"):
            with self.subTest(action=action_name):
                marca = AuditLog.objects.order_by("-id").values_list("id", flat=True).first() or 0
                url_path = action_name.replace("_", "-")
                request = APIRequestFactory().get(f"/api/v1/patients/{self.patient.id}/{url_path}/")
                force_authenticate(request, user=self.user)
                response = PatientViewSet.as_view({"get": action_name})(
                    request, pk=str(self.patient.id)
                )
                self.assertEqual(response.status_code, 200, response.data)
                log = AuditLog.objects.get(
                    action="view_record", resource_type="Patient", id__gt=marca
                )
                self.assertEqual(log.resource_id, str(self.patient.id))
                self.assertEqual(log.new_data, {"action": action_name})
