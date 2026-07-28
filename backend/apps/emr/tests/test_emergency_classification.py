"""
E2 — Boletim de emergência + classificação de risco (Manchester) tests.

Covers the tenant-side PS/Emergência domain (apps.emr.emergency_models) built on
the E1 SHARED Manchester catalog:

* EmergencyEncounter (boletim) CRUD + RBAC (emergency.manage writes,
  emergency.read reads; reader-only 403 on create).
* classify THROUGH the ``apps.emr.services.emergency_classify`` service: copies
  acuity_level + target_minutes from the chosen discriminator's catalog row and
  advances the boletim status aguardando_classificacao → classificado. Gated
  ``emergency.classify`` (a reader/manager without classify → 403).
* re-classify APPENDS a second RiskClassification (history is never mutated) and
  ``current_classification`` is the latest.
* risk-classifications is append-only (no PATCH/DELETE → 405).
* cross-schema catalog delete-protection: a ManchesterDiscriminator/Flowchart
  referenced by a RiskClassification cannot be hard-deleted (ProtectedError),
  mirroring protect_bed_type_deletion.
"""

from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.manchester_catalog_models import (
    ManchesterDiscriminator,
    ManchesterFlowchart,
)
from apps.core.models import Role, User
from apps.emr.emergency_models import EmergencyEncounter, RiskClassification
from apps.emr.models import Encounter, Patient, Professional, VitalSigns
from apps.emr.services import emergency_classify as classify_service
from apps.test_utils import TenantTestCase

BASE = "/api/v1"

MANAGE_PERMS = ["emergency.read", "emergency.manage"]
CLASSIFY_PERMS = ["emergency.read", "emergency.classify"]
READ_PERMS = ["emergency.read"]


class EmergencyTestBase(TenantTestCase):
    def setUp(self):
        self.manage_role = Role.objects.create(name="recep_ps", permissions=MANAGE_PERMS)
        self.classify_role = Role.objects.create(name="enf_class", permissions=CLASSIFY_PERMS)
        self.read_role = Role.objects.create(name="leitor_ps", permissions=READ_PERMS)
        self.none_role = Role.objects.create(name="sem_perm", permissions=[])

        self.manager = User.objects.create_user(
            email="mgr@t.com", password="pw", role=self.manage_role
        )
        self.classifier = User.objects.create_user(
            email="cls@t.com", password="pw", role=self.classify_role
        )
        self.reader = User.objects.create_user(
            email="rdr@t.com", password="pw", role=self.read_role
        )
        self.nobody = User.objects.create_user(
            email="none@t.com", password="pw", role=self.none_role
        )

        self.prof = Professional.objects.create(
            user=self.classifier,
            council_type="COREN",
            council_number="99999",
            council_state="SP",
        )
        self.patient = Patient.objects.create(
            full_name="José da Urgência", birth_date="1975-05-05", gender="M", cpf="52998224725"
        )

        # SHARED Manchester catalog fixture (created in-test like the catalog tests).
        self.flowchart = ManchesterFlowchart.objects.create(code="FL01", display="Dor torácica")
        self.disc_laranja = ManchesterDiscriminator.objects.create(
            flowchart=self.flowchart, code="D001", name="Dor pré-cordial", acuity_level="laranja"
        )
        self.disc_vermelho = ManchesterDiscriminator.objects.create(
            flowchart=self.flowchart, code="D002", name="Choque", acuity_level="vermelho"
        )

    def _client(self, user):
        c = APIClient()
        c.defaults["SERVER_NAME"] = self.__class__.domain.domain
        c.force_authenticate(user)
        return c

    def _boletim(self, **kw):
        defaults = {
            "patient": self.patient,
            "mode_of_arrival": "ambulante",
            "chief_complaint": "Dor no peito",
            "created_by": self.manager,
        }
        defaults.update(kw)
        return EmergencyEncounter.objects.create(**defaults)

    @staticmethod
    def _rows(resp):
        return resp.data["results"] if "results" in resp.data else resp.data


# ─── Service-level ────────────────────────────────────────────────────────────


class TestClassifyService(EmergencyTestBase):
    def test_classify_copies_acuity_and_advances_status(self):
        boletim = self._boletim()
        assert boletim.status == EmergencyEncounter.Status.AGUARDANDO_CLASSIFICACAO
        rc = classify_service.classify(
            boletim, self.disc_laranja, by=self.classifier, notes="triagem inicial"
        )
        assert rc.acuity_level == "laranja"
        assert rc.target_minutes == 10
        assert rc.flowchart_id == self.flowchart.pk
        assert rc.discriminator_id == self.disc_laranja.pk
        assert rc.classified_by_id == self.classifier.id
        boletim.refresh_from_db()
        assert boletim.status == EmergencyEncounter.Status.CLASSIFICADO
        assert boletim.current_classification.pk == rc.pk

    def test_reclassify_appends_and_current_is_latest(self):
        boletim = self._boletim()
        first = classify_service.classify(boletim, self.disc_laranja, by=self.classifier)
        second = classify_service.classify(boletim, self.disc_vermelho, by=self.classifier)
        assert RiskClassification.objects.filter(boletim=boletim).count() == 2
        assert first.pk != second.pk
        boletim.refresh_from_db()
        # Re-triagem keeps status classificado (idempotent) and current = latest.
        assert boletim.status == EmergencyEncounter.Status.CLASSIFICADO
        current = boletim.current_classification
        assert current.pk == second.pk
        assert current.acuity_level == "vermelho"
        assert current.target_minutes == 0

    def test_classify_with_vitals_snapshot(self):
        boletim = self._boletim()
        enc = Encounter.objects.create(
            patient=self.patient,
            professional=self.prof,
            encounter_type="emergencia",
            encounter_date=timezone.now(),
        )
        vitals = VitalSigns.objects.create(
            encounter=enc, heart_rate=120, blood_pressure_systolic=90
        )
        rc = classify_service.classify(
            boletim, self.disc_laranja, vitals=vitals, by=self.classifier
        )
        assert rc.vitals_id == vitals.id


# ─── API + RBAC ───────────────────────────────────────────────────────────────


class TestEmergencyEncounterAPI(EmergencyTestBase):
    def _payload(self, **kw):
        payload = {
            "patient": str(self.patient.id),
            "mode_of_arrival": "ambulancia",
            "chief_complaint": "Dispneia",
        }
        payload.update(kw)
        return payload

    def test_manage_can_create_boletim(self):
        resp = self._client(self.manager).post(
            f"{BASE}/emergency-encounters/", self._payload(), format="json"
        )
        assert resp.status_code == 201, resp.content
        boletim = EmergencyEncounter.objects.get(pk=resp.data["id"])
        assert boletim.status == EmergencyEncounter.Status.AGUARDANDO_CLASSIFICACAO
        assert boletim.created_by_id == self.manager.id

    def test_reader_cannot_create_boletim(self):
        resp = self._client(self.reader).post(
            f"{BASE}/emergency-encounters/", self._payload(), format="json"
        )
        assert resp.status_code == 403, resp.content
        assert not EmergencyEncounter.objects.exists()

    def test_reader_can_list_and_filter(self):
        self._boletim()
        c = self._client(self.reader)
        resp = c.get(f"{BASE}/emergency-encounters/?patient={self.patient.id}")
        assert resp.status_code == 200
        assert len(self._rows(resp)) == 1
        by_status = c.get(f"{BASE}/emergency-encounters/?status=aguardando_classificacao")
        assert len(self._rows(by_status)) == 1

    def test_classify_action_requires_classify_permission(self):
        boletim = self._boletim()
        body = {"discriminator": str(self.disc_laranja.pk), "notes": "x"}
        # manager has emergency.manage but NOT emergency.classify → 403
        forbidden = self._client(self.manager).post(
            f"{BASE}/emergency-encounters/{boletim.pk}/classify/", body, format="json"
        )
        assert forbidden.status_code == 403, forbidden.content
        # classifier carries emergency.classify → 200/201
        ok = self._client(self.classifier).post(
            f"{BASE}/emergency-encounters/{boletim.pk}/classify/", body, format="json"
        )
        assert ok.status_code in (200, 201), ok.content
        boletim.refresh_from_db()
        assert boletim.status == EmergencyEncounter.Status.CLASSIFICADO
        assert boletim.current_classification.acuity_level == "laranja"
        assert boletim.current_classification.target_minutes == 10

    def test_reader_only_cannot_classify(self):
        boletim = self._boletim()
        resp = self._client(self.reader).post(
            f"{BASE}/emergency-encounters/{boletim.pk}/classify/",
            {"discriminator": str(self.disc_laranja.pk)},
            format="json",
        )
        assert resp.status_code == 403, resp.content
        assert not RiskClassification.objects.exists()


class TestRiskClassificationAPI(EmergencyTestBase):
    def test_history_readable_and_append_only(self):
        boletim = self._boletim()
        classify_service.classify(boletim, self.disc_laranja, by=self.classifier)
        classify_service.classify(boletim, self.disc_vermelho, by=self.classifier)
        c = self._client(self.reader)
        resp = c.get(f"{BASE}/risk-classifications/?boletim={boletim.pk}")
        assert resp.status_code == 200, resp.content
        rows = self._rows(resp)
        assert len(rows) == 2

    def test_no_post_patch_delete_on_risk_classifications(self):
        boletim = self._boletim()
        rc = classify_service.classify(boletim, self.disc_laranja, by=self.classifier)
        c = self._client(self.classifier)
        post = c.post(f"{BASE}/risk-classifications/", {}, format="json")
        assert post.status_code in (403, 405), post.content
        patch = c.patch(f"{BASE}/risk-classifications/{rc.pk}/", {"notes": "z"}, format="json")
        assert patch.status_code in (403, 405), patch.content
        delete = c.delete(f"{BASE}/risk-classifications/{rc.pk}/")
        assert delete.status_code in (403, 405), delete.content


# ─── cross-schema catalog delete-protection ───────────────────────────────────


class TestCatalogDeleteProtection(EmergencyTestBase):
    def test_discriminator_referenced_by_classification_cannot_be_deleted(self):
        boletim = self._boletim()
        classify_service.classify(boletim, self.disc_laranja, by=self.classifier)
        # Wrap in a savepoint: the pre_delete signal raises mid-delete(), marking
        # the transaction for rollback; the inner atomic() keeps the assertion query valid.
        with self.assertRaises(ProtectedError) as ctx, transaction.atomic():
            self.disc_laranja.delete()
        assert "RiskClassification" in str(ctx.exception)
        assert ManchesterDiscriminator.objects.filter(pk=self.disc_laranja.pk).exists()

    def test_flowchart_referenced_by_classification_cannot_be_deleted(self):
        boletim = self._boletim()
        classify_service.classify(boletim, self.disc_laranja, by=self.classifier)
        with self.assertRaises(ProtectedError), transaction.atomic():
            self.flowchart.delete()
        assert ManchesterFlowchart.objects.filter(pk=self.flowchart.pk).exists()
