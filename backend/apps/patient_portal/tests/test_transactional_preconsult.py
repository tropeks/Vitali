"""S5-T3 — pre-consult clinical forms through the patient portal."""

from __future__ import annotations

from datetime import date, timedelta

from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import AuditLog, FeatureFlag, Role, User
from apps.emr.models import (
    Appointment,
    ClinicalFormResponse,
    ClinicalFormTemplate,
    Patient,
    Professional,
)
from apps.patient_portal.models import PatientPortalAccess, PortalConsent
from apps.patient_portal.transactional_models import PortalPreConsultForm
from apps.test_utils import TenantTestCase


def _form_url(appt_pk):
    return f"/api/v1/portal/me/appointments/{appt_pk}/pre-consult-form/"


def _make_user(*, role_name, perms, email, full_name):
    role, _ = Role.objects.get_or_create(name=role_name, defaults={"permissions": perms})
    role.permissions = perms
    role.save()
    return User.objects.create_user(email=email, password="pw", role=role, full_name=full_name)


SCHEMA = [
    {"key": "peso", "label": "Peso (kg)", "type": "number", "required": True},
    {"key": "queixa", "label": "Queixa principal", "type": "text", "required": False},
]


class PortalPreConsultTest(TenantTestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key="patient_portal",
            defaults={"is_enabled": True},
        )
        self.admin = _make_user(
            role_name="pc_admin",
            perms=["users.read", "users.write"],
            email="admin_pc@test.com",
            full_name="Admin",
        )
        self.md_user = _make_user(
            role_name="md_pc", perms=["users.read"], email="md_pc@test.com", full_name="Dra Bia"
        )
        self.md = Professional.objects.create(
            user=self.md_user, council_type="CRM", council_number="700502", council_state="SP"
        )
        self.template = ClinicalFormTemplate.objects.create(
            name="Pré-consulta", specialty="clinica", schema=SCHEMA
        )
        self.template.publish()

        self.patient = Patient.objects.create(
            full_name="Ana Souza", cpf="12345678909", birth_date=date(1985, 7, 14), gender="F"
        )
        self.patient_user = _make_user(
            role_name="pc_self",
            perms=["portal.self_access"],
            email="ana_pc@test.com",
            full_name="Ana Souza",
        )
        access = PatientPortalAccess.objects.create(
            user=self.patient_user, patient=self.patient, created_by=self.admin
        )
        access.activate()
        self.consent = PortalConsent.objects.create(
            patient=self.patient,
            granted_by=self.patient_user,
            purpose="portal_pre_consult",
            policy_version="1.0",
        )
        self.appointment = self._make_appt(self.patient, offset_h=1)
        self.assignment = PortalPreConsultForm.objects.create(
            appointment=self.appointment, template=self.template
        )

        self.other_patient = Patient.objects.create(
            full_name="Bruno Lima", cpf="98765432100", birth_date=date(1990, 3, 1), gender="M"
        )
        self.other_appt = self._make_appt(self.other_patient, offset_h=5)
        PortalPreConsultForm.objects.create(appointment=self.other_appt, template=self.template)

        self.client.force_authenticate(user=self.patient_user)

    def _make_appt(self, patient, offset_h):
        return Appointment.objects.create(
            patient=patient,
            professional=self.md,
            start_time=timezone.now() + timedelta(days=2, hours=offset_h),
            end_time=timezone.now() + timedelta(days=2, hours=offset_h + 1),
            status="scheduled",
        )

    # ── fetch ─────────────────────────────────────────────────────────────────

    def test_fetch_assigned_template(self):
        resp = self.client.get(_form_url(self.appointment.pk))
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data["template"]["id"], str(self.template.pk))
        self.assertEqual(resp.data["template"]["schema"], SCHEMA)
        self.assertEqual(resp.data["status"], "assigned")

    # ── submit ────────────────────────────────────────────────────────────────

    def test_submit_valid_response_encrypts_answers(self):
        resp = self.client.post(
            _form_url(self.appointment.pk),
            {"answers": {"peso": 70, "queixa": "Dor de cabeça"}},
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        response = ClinicalFormResponse.objects.get(pk=resp.data["id"])
        self.assertEqual(response.patient_id, self.patient.pk)
        self.assertEqual(response.answers["peso"], 70)
        self.assertEqual(response.filled_by_id, self.patient_user.pk)
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.status, "submitted")
        self.assertEqual(self.assignment.response_id, response.pk)
        self.assertTrue(AuditLog.objects.filter(action="portal_pre_consult_submitted").exists())

    def test_encrypted_at_rest(self):
        self.client.post(
            _form_url(self.appointment.pk),
            {"answers": {"peso": 55}},
            format="json",
        )
        response = ClinicalFormResponse.objects.get(patient=self.patient)
        # The encrypted DB column must not contain the plaintext answer value.
        from django.db import connection

        with connection.cursor() as cur:
            cur.execute("SELECT answers FROM emr_clinicalformresponse WHERE id = %s", [response.pk])
            raw = cur.fetchone()[0]
        self.assertNotIn("55", str(raw))

    def test_invalid_answers_rejected(self):
        resp = self.client.post(
            _form_url(self.appointment.pk),
            {"answers": {"peso": "não é número"}},
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertFalse(ClinicalFormResponse.objects.filter(patient=self.patient).exists())

    def test_missing_required_field_rejected(self):
        resp = self.client.post(
            _form_url(self.appointment.pk),
            {"answers": {"queixa": "só isso"}},
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.data)

    def test_cannot_submit_for_other_patients_appointment(self):
        resp = self.client.post(
            _form_url(self.other_appt.pk),
            {"answers": {"peso": 70}},
            format="json",
        )
        self.assertEqual(resp.status_code, 404, resp.data)
        self.assertFalse(ClinicalFormResponse.objects.filter(patient=self.patient).exists())

    def test_submit_requires_lgpd_consent(self):
        self.consent.revoked_at = timezone.now()
        self.consent.save(update_fields=["revoked_at"])
        resp = self.client.post(
            _form_url(self.appointment.pk),
            {"answers": {"peso": 70}},
            format="json",
        )
        self.assertEqual(resp.status_code, 403, resp.data)
