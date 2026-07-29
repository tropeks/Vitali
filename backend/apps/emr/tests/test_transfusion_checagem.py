"""
H4 — Checagem beira-leito ("certos" transfusionais) + administração +
reação transfusional / hemovigilância.

Covers:
  * verify_transfusion_rights (pure): all-5-right ok; wrong patient barcode →
    paciente False; wrong bag barcode → bolsa False; component mismatch →
    componente False; ABO-incompatible bag → compatibilidade False; expired bag
    → validade False; .mismatches / .as_dict shape.
  * checar_e_administrar happy path (liberada → 201-equivalent: administration
    recorded verified, request transfundida, bag transfundida).
  * a failing right without override → ChecagemFailedError carrying the breakdown
    (view → 422); override path → recorded checagem_verified=False.
  * checar on a non-liberada request → state error (view → 409).
  * registrar_reacao appends a TransfusionReaction (hemovigilância).
  * API: checar endpoint 201 / 422 shape / 409; reacao endpoint; append-only
    (PATCH/DELETE → 405) on administrations + reactions; RBAC
    (hemoterapia.transfuse to check, hemoterapia.read to list).

Mirrors setup from test_transfusion.py + test_bcma_verification patterns.
"""

from datetime import timedelta

from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import BloodComponentCatalog, Role, User
from apps.emr.models import (
    BloodBag,
    Encounter,
    Patient,
    Professional,
    TransfusionAdministration,
    TransfusionReaction,
    TransfusionRequest,
)
from apps.emr.services import transfusion as transfusion_service
from apps.emr.services import transfusion_admin as admin_service
from apps.emr.services.transfusion_admin import ChecagemFailedError, TransfusionStateError
from apps.emr.services.transfusion_checagem import (
    TransfusionRightsResult,
    verify_transfusion_rights,
)
from apps.test_utils import TenantTestCase

BASE = "/api/v1"

TRANSFUSE_PERMS = ["hemoterapia.read", "hemoterapia.transfuse"]
READ_PERMS = ["hemoterapia.read"]


class ChecagemTestBase(TenantTestCase):
    def setUp(self):
        self.transfuse_role = Role.objects.create(
            name="enfermeiro_hemo", permissions=TRANSFUSE_PERMS
        )
        self.read_role = Role.objects.create(name="leitor_hemo", permissions=READ_PERMS)
        self.none_role = Role.objects.create(name="sem_perm_hemo", permissions=[])

        self.nurse = User.objects.create_user(
            email="enf@t.com", password="pw", role=self.transfuse_role
        )
        self.witness_user = User.objects.create_user(
            email="enf2@t.com", password="pw", role=self.transfuse_role
        )
        self.reader = User.objects.create_user(
            email="leitor@t.com", password="pw", role=self.read_role
        )
        self.nobody = User.objects.create_user(
            email="none@t.com", password="pw", role=self.none_role
        )
        self.prof = Professional.objects.create(
            user=self.nurse, council_type="COREN", council_number="55555", council_state="SP"
        )
        # Recipient: O negativo, wristband barcode set.
        self.patient = Patient.objects.create(
            full_name="Maria Receptora",
            cpf="52998224725",
            birth_date="1980-01-01",
            gender="F",
            abo="O",
            rh_factor="negativo",
            wristband_barcode="WB-123",
        )
        self.encounter = Encounter.objects.create(patient=self.patient, professional=self.prof)
        self.component = BloodComponentCatalog.objects.create(
            code="CH", display="Concentrado de hemácias", default_validade_dias=42
        )
        self.other_component = BloodComponentCatalog.objects.create(
            code="PFC", display="Plasma fresco congelado", default_validade_dias=365
        )
        self.today = timezone.now().date()

    def _client(self, user):
        c = APIClient()
        c.defaults["SERVER_NAME"] = self.__class__.domain.domain
        c.force_authenticate(user)
        return c

    def _bag(self, **overrides):
        defaults = {
            "identifier": overrides.pop("identifier", "DIN-COMPAT"),
            "component": self.component,
            "abo": "O",
            "rh_factor": "negativo",
            "volume_ml": 450,
            "collection_date": self.today - timedelta(days=1),
            "expiry_date": self.today + timedelta(days=30),
            "serology_status": BloodBag.SerologyStatus.LIBERADA,
            "stock_status": BloodBag.StockStatus.DISPONIVEL,
        }
        defaults.update(overrides)
        return BloodBag.objects.create(**defaults)

    def _request(self, **overrides):
        defaults = {
            "patient": self.patient,
            "encounter": self.encounter,
            "component": self.component,
            "quantidade": 1,
            "indicacao": "Anemia sintomática",
            "requester": self.prof,
        }
        defaults.update(overrides)
        return TransfusionRequest.objects.create(**defaults)

    def _liberada(self, bag=None):
        """A request driven through reservar+liberar with a compatible bag."""
        req = self._request()
        bag = bag or self._bag()
        transfusion_service.reservar(req, bag, actor=self.nurse)
        transfusion_service.liberar(req, actor=self.nurse)
        req.refresh_from_db()
        bag.refresh_from_db()
        return req, bag


# ─── pure verifier ────────────────────────────────────────────────────────────


class TestVerifyTransfusionRights(ChecagemTestBase):
    def _verify(self, req, bag, **over):
        kwargs = {
            "patient_barcode": "WB-123",
            "bag_barcode": bag.identifier,
            "at_time": timezone.now(),
        }
        kwargs.update(over)
        return verify_transfusion_rights(req, bag, **kwargs)

    def test_all_five_ok(self):
        req = self._request()
        bag = self._bag()
        result = self._verify(req, bag)
        assert isinstance(result, TransfusionRightsResult)
        assert result.paciente
        assert result.bolsa
        assert result.componente
        assert result.compatibilidade
        assert result.validade
        assert result.ok
        assert result.mismatches == []
        d = result.as_dict()
        assert d["ok"] is True
        assert set(d) == {
            "paciente",
            "bolsa",
            "componente",
            "compatibilidade",
            "validade",
            "ok",
            "mismatches",
        }

    def test_wrong_patient_barcode(self):
        req = self._request()
        bag = self._bag()
        result = self._verify(req, bag, patient_barcode="WRONG")
        assert result.paciente is False
        assert not result.ok
        assert "paciente" in result.mismatches

    def test_patient_barcode_accepts_mrn(self):
        req = self._request()
        bag = self._bag()
        result = self._verify(req, bag, patient_barcode=self.patient.medical_record_number)
        assert result.paciente is True

    def test_wrong_bag_barcode(self):
        req = self._request()
        bag = self._bag()
        result = self._verify(req, bag, bag_barcode="DIN-OTHER")
        assert result.bolsa is False
        assert "bolsa" in result.mismatches

    def test_component_mismatch(self):
        req = self._request()
        bag = self._bag(component=self.other_component)
        result = self._verify(req, bag)
        assert result.componente is False
        assert "componente" in result.mismatches

    def test_abo_incompatible(self):
        req = self._request()
        # patient O; an A bag is ABO-incompatible.
        bag = self._bag(identifier="DIN-A", abo="A")
        result = self._verify(req, bag)
        assert result.compatibilidade is False
        assert "compatibilidade" in result.mismatches

    def test_expired_bag(self):
        req = self._request()
        bag = self._bag(
            identifier="DIN-EXP",
            collection_date=self.today - timedelta(days=60),
            expiry_date=self.today - timedelta(days=1),
        )
        result = self._verify(req, bag)
        assert result.validade is False
        assert "validade" in result.mismatches


# ─── service: checar_e_administrar ────────────────────────────────────────────


class TestChecarService(ChecagemTestBase):
    def test_happy_path_records_and_advances(self):
        req, bag = self._liberada()
        adm = admin_service.checar_e_administrar(
            req,
            bag,
            patient_barcode="WB-123",
            bag_barcode=bag.identifier,
            actor=self.nurse,
            witness=self.witness_user,
            at_time=timezone.now(),
        )
        assert isinstance(adm, TransfusionAdministration)
        assert adm.checagem_verified is True
        assert adm.witness_id == self.witness_user.id
        req.refresh_from_db()
        bag.refresh_from_db()
        assert req.status == TransfusionRequest.Status.TRANSFUNDIDA
        assert bag.stock_status == BloodBag.StockStatus.TRANSFUNDIDA

    def test_failing_right_without_override_raises(self):
        req, bag = self._liberada()
        with self.assertRaises(ChecagemFailedError) as ctx:
            admin_service.checar_e_administrar(
                req,
                bag,
                patient_barcode="WRONG",
                bag_barcode=bag.identifier,
                actor=self.nurse,
                at_time=timezone.now(),
            )
        assert ctx.exception.checagem["paciente"] is False
        assert ctx.exception.checagem["ok"] is False
        req.refresh_from_db()
        assert req.status == TransfusionRequest.Status.LIBERADA
        assert not TransfusionAdministration.objects.filter(request=req).exists()

    def test_override_path_records_unverified(self):
        req, bag = self._liberada()
        adm = admin_service.checar_e_administrar(
            req,
            bag,
            patient_barcode="WRONG",
            bag_barcode=bag.identifier,
            actor=self.nurse,
            override_reason="pulseira danificada, identidade confirmada verbalmente",
            at_time=timezone.now(),
        )
        assert adm.checagem_verified is False
        assert adm.checagem_override_reason
        req.refresh_from_db()
        assert req.status == TransfusionRequest.Status.TRANSFUNDIDA

    def test_checar_non_liberada_raises_state_error(self):
        req = self._request()  # solicitada
        bag = self._bag()
        with self.assertRaises(TransfusionStateError):
            admin_service.checar_e_administrar(
                req,
                bag,
                patient_barcode="WB-123",
                bag_barcode=bag.identifier,
                actor=self.nurse,
                at_time=timezone.now(),
            )

    def test_registrar_reacao_appends(self):
        req, bag = self._liberada()
        adm = admin_service.checar_e_administrar(
            req,
            bag,
            patient_barcode="WB-123",
            bag_barcode=bag.identifier,
            actor=self.nurse,
            at_time=timezone.now(),
        )
        reac = admin_service.registrar_reacao(
            adm,
            tipo=TransfusionReaction.Tipo.FEBRIL_NAO_HEMOLITICA,
            gravidade=TransfusionReaction.Gravidade.LEVE,
            descricao="Elevação térmica de 1.5°C durante a transfusão.",
            conduta="Interrompida a transfusão, antitérmico administrado.",
            actor=self.nurse,
            occurred_at=timezone.now(),
        )
        assert isinstance(reac, TransfusionReaction)
        assert reac.administration_id == adm.id
        assert reac.request_id == req.id
        assert adm.reactions.count() == 1


# ─── DRF API: endpoints + RBAC + append-only ──────────────────────────────────


class TestChecagemAPI(ChecagemTestBase):
    def test_checar_endpoint_verified_201(self):
        req, bag = self._liberada()
        resp = self._client(self.nurse).post(
            f"{BASE}/transfusion-requests/{req.pk}/checar/",
            {
                "bag": str(bag.pk),
                "patient_barcode": "WB-123",
                "bag_barcode": bag.identifier,
                "witness": str(self.witness_user.pk),
            },
            format="json",
        )
        assert resp.status_code == 201, resp.content
        assert resp.data["checagem_verified"] is True
        req.refresh_from_db()
        assert req.status == TransfusionRequest.Status.TRANSFUNDIDA

    def test_checar_endpoint_rights_failure_422(self):
        req, bag = self._liberada()
        resp = self._client(self.nurse).post(
            f"{BASE}/transfusion-requests/{req.pk}/checar/",
            {
                "bag": str(bag.pk),
                "patient_barcode": "WRONG",
                "bag_barcode": bag.identifier,
            },
            format="json",
        )
        assert resp.status_code == 422, resp.content
        assert "detail" in resp.data
        checagem = resp.data["checagem"]
        for key in (
            "paciente",
            "bolsa",
            "componente",
            "compatibilidade",
            "validade",
            "ok",
            "mismatches",
        ):
            assert key in checagem
        assert checagem["paciente"] is False
        assert checagem["ok"] is False

    def test_checar_endpoint_override_201(self):
        req, bag = self._liberada()
        resp = self._client(self.nurse).post(
            f"{BASE}/transfusion-requests/{req.pk}/checar/",
            {
                "bag": str(bag.pk),
                "patient_barcode": "WRONG",
                "bag_barcode": bag.identifier,
                "override_reason": "pulseira danificada",
            },
            format="json",
        )
        assert resp.status_code == 201, resp.content
        assert resp.data["checagem_verified"] is False

    def test_checar_non_liberada_409(self):
        req = self._request()
        bag = self._bag()
        resp = self._client(self.nurse).post(
            f"{BASE}/transfusion-requests/{req.pk}/checar/",
            {"bag": str(bag.pk), "patient_barcode": "WB-123", "bag_barcode": bag.identifier},
            format="json",
        )
        assert resp.status_code == 409, resp.content

    def test_checar_requires_transfuse_perm(self):
        req, bag = self._liberada()
        resp = self._client(self.reader).post(
            f"{BASE}/transfusion-requests/{req.pk}/checar/",
            {"bag": str(bag.pk), "patient_barcode": "WB-123", "bag_barcode": bag.identifier},
            format="json",
        )
        assert resp.status_code == 403, resp.content

    def test_reacao_endpoint(self):
        req, bag = self._liberada()
        adm = admin_service.checar_e_administrar(
            req, bag, patient_barcode="WB-123", bag_barcode=bag.identifier, actor=self.nurse
        )
        resp = self._client(self.nurse).post(
            f"{BASE}/transfusion-administrations/{adm.pk}/reacao/",
            {
                "tipo": TransfusionReaction.Tipo.ALERGICA,
                "gravidade": TransfusionReaction.Gravidade.MODERADA,
                "descricao": "Urticária generalizada.",
                "conduta": "Anti-histamínico.",
            },
            format="json",
        )
        assert resp.status_code == 201, resp.content
        assert TransfusionReaction.objects.filter(administration=adm).count() == 1

    def test_administrations_list_read_gated(self):
        req, bag = self._liberada()
        admin_service.checar_e_administrar(
            req, bag, patient_barcode="WB-123", bag_barcode=bag.identifier, actor=self.nurse
        )
        ok = self._client(self.reader).get(f"{BASE}/transfusion-administrations/?request={req.pk}")
        assert ok.status_code == 200, ok.content
        rows = ok.data["results"] if "results" in ok.data else ok.data
        assert len(rows) == 1
        assert (
            self._client(self.nobody).get(f"{BASE}/transfusion-administrations/").status_code == 403
        )

    def test_reactions_list_filter(self):
        req, bag = self._liberada()
        adm = admin_service.checar_e_administrar(
            req, bag, patient_barcode="WB-123", bag_barcode=bag.identifier, actor=self.nurse
        )
        admin_service.registrar_reacao(
            adm,
            tipo=TransfusionReaction.Tipo.OUTRA,
            gravidade=TransfusionReaction.Gravidade.LEVE,
            descricao="x",
            actor=self.nurse,
        )
        resp = self._client(self.reader).get(
            f"{BASE}/transfusion-reactions/?administration={adm.pk}"
        )
        assert resp.status_code == 200, resp.content
        rows = resp.data["results"] if "results" in resp.data else resp.data
        assert len(rows) == 1

    def test_administrations_append_only(self):
        req, bag = self._liberada()
        adm = admin_service.checar_e_administrar(
            req, bag, patient_barcode="WB-123", bag_barcode=bag.identifier, actor=self.nurse
        )
        c = self._client(self.nurse)
        assert (
            c.patch(
                f"{BASE}/transfusion-administrations/{adm.pk}/", {"volume_ml": 200}, format="json"
            ).status_code
            == 405
        )
        assert c.delete(f"{BASE}/transfusion-administrations/{adm.pk}/").status_code == 405

    def test_reactions_append_only(self):
        req, bag = self._liberada()
        adm = admin_service.checar_e_administrar(
            req, bag, patient_barcode="WB-123", bag_barcode=bag.identifier, actor=self.nurse
        )
        reac = admin_service.registrar_reacao(
            adm,
            tipo=TransfusionReaction.Tipo.OUTRA,
            gravidade=TransfusionReaction.Gravidade.LEVE,
            descricao="x",
            actor=self.nurse,
        )
        c = self._client(self.nurse)
        assert (
            c.patch(
                f"{BASE}/transfusion-reactions/{reac.pk}/",
                {"notificado_hemovigilancia": True},
                format="json",
            ).status_code
            == 405
        )
        assert c.delete(f"{BASE}/transfusion-reactions/{reac.pk}/").status_code == 405
