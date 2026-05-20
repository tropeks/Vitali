"""Integration tests for the patient portal backend primitive."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import FeatureFlag, Role, User
from apps.emr.models import Allergy, Appointment, Encounter, Patient, Professional
from apps.patient_portal.models import PatientPortalAccess
from apps.test_utils import TenantTestCase

ACCESS_URL = "/api/v1/portal/access/"
ACTIVATE_URL = "/api/v1/portal/access/activate/"
ME_URL = "/api/v1/portal/me/"
ME_APPTS_URL = "/api/v1/portal/me/appointments/"
ME_ENC_URL = "/api/v1/portal/me/encounters/"
ME_RX_URL = "/api/v1/portal/me/prescriptions/"
ME_ALLERGIES_URL = "/api/v1/portal/me/allergies/"


def _access_detail_url(pk):
    return f"/api/v1/portal/access/{pk}/"


def _access_revoke_url(pk):
    return f"/api/v1/portal/access/{pk}/revoke/"


def _make_user(*, role_name: str, perms: list[str], email: str, full_name: str) -> User:
    role, _ = Role.objects.get_or_create(name=role_name, defaults={"permissions": perms})
    role.permissions = perms
    role.save()
    return User.objects.create_user(email=email, password="pw", role=role, full_name=full_name)


class PatientPortalViewsTest(TenantTestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key="patient_portal",
            defaults={"is_enabled": True},
        )

        # Clinic staff for admin surface
        self.admin = _make_user(
            role_name="portal_admin",
            perms=["users.read", "users.write"],
            email="admin_p@test.com",
            full_name="Admin",
        )

        # Patient + linked portal user
        self.patient = Patient.objects.create(
            full_name="Ana Maria Souza",
            cpf="12345678909",
            birth_date=date(1985, 7, 14),
            gender="F",
        )
        self.patient_user = _make_user(
            role_name="portal_self",
            perms=["portal.self_access"],
            email="ana_portal@test.com",
            full_name="Ana Maria Souza",
        )

        # Another patient + their portal user — used to assert tenant
        # isolation at the API layer (one portal user must never see
        # another patient's data).
        self.other_patient = Patient.objects.create(
            full_name="Bruno Lima",
            cpf="98765432100",
            birth_date=date(1990, 3, 1),
            gender="M",
        )
        self.other_user = _make_user(
            role_name="portal_self_b",
            perms=["portal.self_access"],
            email="bruno_portal@test.com",
            full_name="Bruno Lima",
        )

        # MD
        self.md_user = _make_user(
            role_name="md_portal",
            perms=["users.read"],
            email="md_portal@test.com",
            full_name="Dra Bia",
        )
        self.md = Professional.objects.create(
            user=self.md_user,
            council_type="CRM",
            council_number="700500",
            council_state="SP",
        )

        # Pre-existing clinical data for Ana
        self.encounter_signed = Encounter.objects.create(
            patient=self.patient,
            professional=self.md,
            status="signed",
            encounter_date=datetime(2026, 5, 10, 10, 0, tzinfo=UTC),
            signed_at=datetime(2026, 5, 10, 10, 30, tzinfo=UTC),
        )
        self.encounter_draft = Encounter.objects.create(
            patient=self.patient,
            professional=self.md,
            status="open",
            encounter_date=datetime(2026, 5, 15, 10, 0, tzinfo=UTC),
        )
        self.appointment = Appointment.objects.create(
            patient=self.patient,
            professional=self.md,
            start_time=timezone.now() + timedelta(days=2),
            end_time=timezone.now() + timedelta(days=2, hours=1),
            status="scheduled",
        )
        self.allergy = Allergy.objects.create(
            patient=self.patient,
            substance="Penicilina",
            severity="severe",
            status="active",
        )

    def _mint_invite(self, user=None, patient=None) -> PatientPortalAccess:
        return PatientPortalAccess.objects.create(
            user=user or self.patient_user,
            patient=patient or self.patient,
            created_by=self.admin,
        )

    # ─── Admin surface ────────────────────────────────────────────────────────

    def test_admin_can_create_portal_invite(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.post(
            ACCESS_URL,
            {"user": self.patient_user.pk, "patient": str(self.patient.pk)},
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data["status"], "invited")
        self.assertTrue(resp.data["invite_token"])
        self.assertEqual(resp.data["created_by"], self.admin.pk)

    def test_admin_list_filters_by_status(self):
        active_access = self._mint_invite()
        active_access.activate()
        revoked_access = self._mint_invite(user=self.other_user, patient=self.other_patient)
        revoked_access.revoke()

        self.client.force_authenticate(user=self.admin)
        resp = self.client.get(ACCESS_URL, {"status": "active"})
        ids = {entry["id"] for entry in resp.data}
        self.assertIn(str(active_access.pk), ids)
        self.assertNotIn(str(revoked_access.pk), ids)

    def test_revoke_endpoint_flips_status(self):
        access = self._mint_invite()
        self.client.force_authenticate(user=self.admin)
        resp = self.client.post(_access_revoke_url(access.pk))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["status"], "revoked")

    def test_admin_create_blocked_without_users_write(self):
        reader = _make_user(
            role_name="portal_reader",
            perms=["users.read"],
            email="read_p@test.com",
            full_name="Reader",
        )
        self.client.force_authenticate(user=reader)
        resp = self.client.post(
            ACCESS_URL,
            {"user": self.patient_user.pk, "patient": str(self.patient.pk)},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)

    # ─── Activate ────────────────────────────────────────────────────────────

    def test_activate_consumes_invite_token(self):
        access = self._mint_invite()
        self.client.force_authenticate(user=self.patient_user)
        resp = self.client.post(ACTIVATE_URL, {"invite_token": access.invite_token}, format="json")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data["status"], "active")

    def test_activate_rejects_wrong_user(self):
        access = self._mint_invite()
        # other_user owns a different access record; using Ana's token from
        # Bruno's account must be rejected.
        self.client.force_authenticate(user=self.other_user)
        resp = self.client.post(ACTIVATE_URL, {"invite_token": access.invite_token}, format="json")
        self.assertEqual(resp.status_code, 403)

    def test_activate_rejects_expired_token(self):
        access = self._mint_invite()
        access.invite_expires_at = timezone.now() - timedelta(minutes=1)
        access.save(update_fields=["invite_expires_at"])
        self.client.force_authenticate(user=self.patient_user)
        resp = self.client.post(ACTIVATE_URL, {"invite_token": access.invite_token}, format="json")
        self.assertEqual(resp.status_code, 409)

    def test_activate_invalid_token_returns_400(self):
        self.client.force_authenticate(user=self.patient_user)
        resp = self.client.post(ACTIVATE_URL, {"invite_token": "nope"}, format="json")
        self.assertEqual(resp.status_code, 400)

    # ─── Self-data surface ────────────────────────────────────────────────────

    def _activate_ana(self) -> PatientPortalAccess:
        access = self._mint_invite()
        access.activate()
        return access

    def test_me_returns_own_patient_record(self):
        self._activate_ana()
        self.client.force_authenticate(user=self.patient_user)
        resp = self.client.get(ME_URL)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["id"], str(self.patient.pk))
        self.assertEqual(resp.data["full_name"], "Ana Maria Souza")

    def test_me_appointments_only_own(self):
        # Other patient must have an appointment too — it must NOT come back.
        other_appt = Appointment.objects.create(
            patient=self.other_patient,
            professional=self.md,
            start_time=timezone.now() + timedelta(days=3),
            end_time=timezone.now() + timedelta(days=3, hours=1),
            status="scheduled",
        )
        self._activate_ana()
        self.client.force_authenticate(user=self.patient_user)
        resp = self.client.get(ME_APPTS_URL)
        self.assertEqual(resp.status_code, 200)
        ids = {entry["id"] for entry in resp.data}
        self.assertIn(str(self.appointment.pk), ids)
        self.assertNotIn(str(other_appt.pk), ids)

    def test_me_encounters_only_signed(self):
        self._activate_ana()
        self.client.force_authenticate(user=self.patient_user)
        resp = self.client.get(ME_ENC_URL)
        ids = {entry["id"] for entry in resp.data}
        self.assertIn(str(self.encounter_signed.pk), ids)
        self.assertNotIn(str(self.encounter_draft.pk), ids)

    def test_me_allergies_only_own(self):
        # Plant an allergy on the OTHER patient — must not leak.
        Allergy.objects.create(patient=self.other_patient, substance="Iodo", severity="moderate")
        self._activate_ana()
        self.client.force_authenticate(user=self.patient_user)
        resp = self.client.get(ME_ALLERGIES_URL)
        substances = {entry["substance"] for entry in resp.data}
        self.assertIn("Penicilina", substances)
        self.assertNotIn("Iodo", substances)

    def test_me_blocked_for_invited_status(self):
        # Mint but don't activate — `status=invited` must NOT grant access.
        self._mint_invite()
        self.client.force_authenticate(user=self.patient_user)
        resp = self.client.get(ME_URL)
        self.assertEqual(resp.status_code, 403)

    def test_me_blocked_for_revoked_status(self):
        access = self._activate_ana()
        access.revoke()
        self.client.force_authenticate(user=self.patient_user)
        resp = self.client.get(ME_URL)
        self.assertEqual(resp.status_code, 403)

    def test_me_blocked_for_user_without_self_access_permission(self):
        # admin user has no portal.self_access permission and no access row;
        # /portal/me/ must reject.
        self.client.force_authenticate(user=self.admin)
        resp = self.client.get(ME_URL)
        self.assertEqual(resp.status_code, 403)

    # ─── Module + auth gates ──────────────────────────────────────────────────

    def test_me_blocked_when_module_disabled(self):
        self._activate_ana()
        FeatureFlag.objects.filter(
            tenant=self.__class__.tenant, module_key="patient_portal"
        ).update(is_enabled=False)
        self.client.force_authenticate(user=self.patient_user)
        resp = self.client.get(ME_URL)
        self.assertEqual(resp.status_code, 403)

    def test_admin_blocked_when_module_disabled(self):
        FeatureFlag.objects.filter(
            tenant=self.__class__.tenant, module_key="patient_portal"
        ).update(is_enabled=False)
        self.client.force_authenticate(user=self.admin)
        resp = self.client.get(ACCESS_URL)
        self.assertEqual(resp.status_code, 403)

    def test_me_unauthenticated_returns_401(self):
        resp = self.client.get(ME_URL)
        self.assertIn(resp.status_code, [401, 403])
