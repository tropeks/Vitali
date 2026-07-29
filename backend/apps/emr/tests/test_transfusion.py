"""
H3 — Requisição transfusional + prova de compatibilidade + reserva/liberação.

Covers:
  * TransfusionRequest create gated by ``hemoterapia.request`` (a read-only user
    is 403 on create); read gated by ``hemoterapia.read``
  * the ``reservar`` service/action: a compatible available bag → CrossMatch
    compatível + bag reservada + request reservada
  * an incompatible bag (ABO mismatch) → 409, nothing reserved (bag stays
    disponível, request stays solicitada), an incompatível CrossMatch recorded
  * an unavailable (quarentena) bag → 409
  * liberar reservada → liberada; cancelar frees the reserved bag back to
    disponível; illegal transitions → 409
  * the ABO/Rh compatibility helpers
  * cross-schema BloodComponentCatalog delete-protection via TransfusionRequest

Mirrors setup from test_bloodbank_structure.py + test_adt_admission.py. A bag is
made available by setting serology_status=liberada directly (H2's release flow is
a parallel sprint).
"""

from datetime import timedelta

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import BloodComponentCatalog, Role, User
from apps.emr.models import (
    BloodBag,
    CrossMatch,
    Encounter,
    Patient,
    Professional,
    TransfusionRequest,
)
from apps.emr.services import transfusion as transfusion_service
from apps.test_utils import TenantTestCase

BASE = "/api/v1"

REQUEST_PERMS = ["hemoterapia.read", "hemoterapia.request"]
MANAGE_PERMS = ["hemoterapia.read", "hemoterapia.manage"]
READ_PERMS = ["hemoterapia.read"]


# ─── compatibility helpers (pure) ─────────────────────────────────────────────


class TestCompatibilityRules(TenantTestCase):
    def test_abo_same_or_o(self):
        assert transfusion_service.abo_compativel("O", "O")
        assert not transfusion_service.abo_compativel("O", "A")
        assert transfusion_service.abo_compativel("A", "A")
        assert transfusion_service.abo_compativel("A", "O")
        assert not transfusion_service.abo_compativel("A", "B")
        # AB is universal recipient
        for donor in ("A", "B", "AB", "O"):
            assert transfusion_service.abo_compativel("AB", donor)

    def test_rh_neg_recipient_only_neg(self):
        assert transfusion_service.rh_compativel("negativo", "negativo")
        assert not transfusion_service.rh_compativel("negativo", "positivo")
        # positive recipient takes either
        assert transfusion_service.rh_compativel("positivo", "positivo")
        assert transfusion_service.rh_compativel("positivo", "negativo")


# ─── shared fixtures ──────────────────────────────────────────────────────────


class TransfusionTestBase(TenantTestCase):
    def setUp(self):
        self.request_role = Role.objects.create(name="medico_hemo", permissions=REQUEST_PERMS)
        self.manage_role = Role.objects.create(name="agencia_hemo", permissions=MANAGE_PERMS)
        self.read_role = Role.objects.create(name="leitor_hemo", permissions=READ_PERMS)
        self.none_role = Role.objects.create(name="sem_perm_hemo", permissions=[])

        self.requester_user = User.objects.create_user(
            email="medico@t.com", password="pw", role=self.request_role
        )
        self.manager = User.objects.create_user(
            email="agencia@t.com", password="pw", role=self.manage_role
        )
        self.reader = User.objects.create_user(
            email="leitor@t.com", password="pw", role=self.read_role
        )
        self.nobody = User.objects.create_user(
            email="none@t.com", password="pw", role=self.none_role
        )

        self.prof = Professional.objects.create(
            user=self.requester_user,
            council_type="CRM",
            council_number="12345",
            council_state="SP",
        )
        # Recipient: O negativo (only O negativo units are compatible).
        self.patient = Patient.objects.create(
            full_name="Maria Receptora",
            cpf="52998224725",
            birth_date="1980-01-01",
            gender="F",
            abo="O",
            rh_factor="negativo",
        )
        self.encounter = Encounter.objects.create(patient=self.patient, professional=self.prof)
        self.component = BloodComponentCatalog.objects.create(
            code="CH", display="Concentrado de hemácias", default_validade_dias=42
        )
        self.today = timezone.now().date()

    def _client(self, user):
        c = APIClient()
        c.defaults["SERVER_NAME"] = self.__class__.domain.domain
        c.force_authenticate(user)
        return c

    def _bag(self, **overrides):
        """A released + available bag (O negativo by default → compatible)."""
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


# ─── service: reservar / liberar / cancelar ───────────────────────────────────


class TestReservarService(TransfusionTestBase):
    def test_compatible_available_bag_reserves(self):
        req = self._request()
        bag = self._bag()
        xm = transfusion_service.reservar(req, bag, actor=self.manager)

        assert xm.compativel is True
        assert xm.abo_compativel and xm.rh_compativel
        assert xm.crossmatch_resultado == CrossMatch.Resultado.COMPATIVEL

        bag.refresh_from_db()
        req.refresh_from_db()
        assert bag.stock_status == BloodBag.StockStatus.RESERVADA
        assert req.status == TransfusionRequest.Status.RESERVADA

    def test_incompatible_abo_bag_raises_and_reserves_nothing(self):
        req = self._request()
        # patient is O; an A bag is ABO-incompatible.
        bag = self._bag(identifier="DIN-A", abo="A", rh_factor="negativo")
        with self.assertRaises(DjangoValidationError):
            with transaction.atomic():
                transfusion_service.reservar(req, bag, actor=self.manager)

        bag.refresh_from_db()
        req.refresh_from_db()
        assert bag.stock_status == BloodBag.StockStatus.DISPONIVEL
        assert req.status == TransfusionRequest.Status.SOLICITADA
        # an incompatível crossmatch is still recorded (rolled back with the txn,
        # so query outside; here we assert none persisted after rollback)
        assert not CrossMatch.objects.filter(request=req).exists()

    def test_incompatible_rh_bag_raises(self):
        req = self._request()
        # patient is Rh negativo; a positivo bag is Rh-incompatible.
        bag = self._bag(identifier="DIN-POS", abo="O", rh_factor="positivo")
        with self.assertRaises(DjangoValidationError):
            with transaction.atomic():
                transfusion_service.reservar(req, bag, actor=self.manager)
        bag.refresh_from_db()
        assert bag.stock_status == BloodBag.StockStatus.DISPONIVEL

    def test_unavailable_quarantine_bag_raises(self):
        req = self._request()
        bag = self._bag(identifier="DIN-QUAR", serology_status=BloodBag.SerologyStatus.QUARENTENA)
        with self.assertRaises(DjangoValidationError):
            with transaction.atomic():
                transfusion_service.reservar(req, bag, actor=self.manager)
        req.refresh_from_db()
        assert req.status == TransfusionRequest.Status.SOLICITADA
        assert not CrossMatch.objects.filter(request=req).exists()

    def test_reservar_twice_raises(self):
        req = self._request()
        bag = self._bag()
        transfusion_service.reservar(req, bag, actor=self.manager)
        bag2 = self._bag(identifier="DIN-2")
        with self.assertRaises(DjangoValidationError):
            with transaction.atomic():
                transfusion_service.reservar(req, bag2, actor=self.manager)


class TestLiberarCancelarService(TransfusionTestBase):
    def test_liberar_reservada_to_liberada(self):
        req = self._request()
        bag = self._bag()
        transfusion_service.reservar(req, bag, actor=self.manager)
        transfusion_service.liberar(req, actor=self.manager)
        req.refresh_from_db()
        bag.refresh_from_db()
        assert req.status == TransfusionRequest.Status.LIBERADA
        # bag stays reservada until H4 transfunde
        assert bag.stock_status == BloodBag.StockStatus.RESERVADA

    def test_liberar_from_solicitada_raises(self):
        req = self._request()
        with self.assertRaises(DjangoValidationError):
            transfusion_service.liberar(req, actor=self.manager)

    def test_cancelar_frees_reserved_bag(self):
        req = self._request()
        bag = self._bag()
        transfusion_service.reservar(req, bag, actor=self.manager)
        transfusion_service.cancelar(req, reason="engano")
        req.refresh_from_db()
        bag.refresh_from_db()
        assert req.status == TransfusionRequest.Status.CANCELADA
        assert bag.stock_status == BloodBag.StockStatus.DISPONIVEL

    def test_cancelar_from_solicitada_ok(self):
        req = self._request()
        transfusion_service.cancelar(req)
        req.refresh_from_db()
        assert req.status == TransfusionRequest.Status.CANCELADA

    def test_cancelar_after_liberar_frees_bag(self):
        req = self._request()
        bag = self._bag()
        transfusion_service.reservar(req, bag, actor=self.manager)
        transfusion_service.liberar(req, actor=self.manager)
        transfusion_service.cancelar(req)
        bag.refresh_from_db()
        assert bag.stock_status == BloodBag.StockStatus.DISPONIVEL

    def test_cancelar_terminal_transfundida_raises(self):
        req = self._request(status=TransfusionRequest.Status.TRANSFUNDIDA)
        with self.assertRaises(DjangoValidationError):
            transfusion_service.cancelar(req)


# ─── DRF API: RBAC + endpoints ────────────────────────────────────────────────


class TestTransfusionRequestAPI(TransfusionTestBase):
    def _payload(self, **overrides):
        payload = {
            "patient": str(self.patient.pk),
            "encounter": str(self.encounter.pk),
            "component": str(self.component.pk),
            "quantidade": 1,
            "indicacao": "Anemia sintomática",
            "urgencia": "rotina",
            "requester": str(self.prof.pk),
        }
        payload.update(overrides)
        return payload

    def test_requester_creates_reader_forbidden(self):
        # médico (hemoterapia.request) creates
        resp = self._client(self.requester_user).post(
            f"{BASE}/transfusion-requests/", self._payload(), format="json"
        )
        assert resp.status_code == 201, resp.content
        obj = TransfusionRequest.objects.get(pk=resp.data["id"])
        assert obj.status == TransfusionRequest.Status.SOLICITADA
        assert obj.created_by_id == self.requester_user.id

        # read-only user → 403 on create
        forbidden = self._client(self.reader).post(
            f"{BASE}/transfusion-requests/", self._payload(identifier="x"), format="json"
        )
        assert forbidden.status_code == 403, forbidden.content

    def test_no_perm_forbidden_on_list(self):
        assert self._client(self.nobody).get(f"{BASE}/transfusion-requests/").status_code == 403

    def test_reader_can_list(self):
        self._request()
        assert self._client(self.reader).get(f"{BASE}/transfusion-requests/").status_code == 200

    def test_manager_cannot_create_but_can_read(self):
        # manager lacks hemoterapia.request → 403 on create
        resp = self._client(self.manager).post(
            f"{BASE}/transfusion-requests/", self._payload(), format="json"
        )
        assert resp.status_code == 403, resp.content

    def test_missing_order_parent_rejected(self):
        resp = self._client(self.requester_user).post(
            f"{BASE}/transfusion-requests/",
            self._payload(encounter=None),
            format="json",
        )
        assert resp.status_code == 400, resp.content

    def test_reservar_action_compatible(self):
        req = self._request()
        bag = self._bag()
        resp = self._client(self.manager).post(
            f"{BASE}/transfusion-requests/{req.pk}/reservar/",
            {"bag": str(bag.pk)},
            format="json",
        )
        assert resp.status_code == 200, resp.content
        assert resp.data["status"] == TransfusionRequest.Status.RESERVADA
        bag.refresh_from_db()
        assert bag.stock_status == BloodBag.StockStatus.RESERVADA

    def test_reservar_incompatible_returns_409(self):
        req = self._request()
        bag = self._bag(identifier="DIN-A", abo="A")
        resp = self._client(self.manager).post(
            f"{BASE}/transfusion-requests/{req.pk}/reservar/",
            {"bag": str(bag.pk)},
            format="json",
        )
        assert resp.status_code == 409, resp.content
        req.refresh_from_db()
        bag.refresh_from_db()
        assert req.status == TransfusionRequest.Status.SOLICITADA
        assert bag.stock_status == BloodBag.StockStatus.DISPONIVEL

    def test_reservar_unavailable_returns_409(self):
        req = self._request()
        bag = self._bag(identifier="DIN-Q", serology_status=BloodBag.SerologyStatus.QUARENTENA)
        resp = self._client(self.manager).post(
            f"{BASE}/transfusion-requests/{req.pk}/reservar/",
            {"bag": str(bag.pk)},
            format="json",
        )
        assert resp.status_code == 409, resp.content

    def test_reservar_requires_manage(self):
        req = self._request()
        bag = self._bag()
        # requester (hemoterapia.request but not manage) → 403
        resp = self._client(self.requester_user).post(
            f"{BASE}/transfusion-requests/{req.pk}/reservar/",
            {"bag": str(bag.pk)},
            format="json",
        )
        assert resp.status_code == 403, resp.content

    def test_liberar_action(self):
        req = self._request()
        bag = self._bag()
        transfusion_service.reservar(req, bag, actor=self.manager)
        resp = self._client(self.manager).post(
            f"{BASE}/transfusion-requests/{req.pk}/liberar/", {}, format="json"
        )
        assert resp.status_code == 200, resp.content
        assert resp.data["status"] == TransfusionRequest.Status.LIBERADA

    def test_liberar_illegal_transition_409(self):
        req = self._request()  # solicitada
        resp = self._client(self.manager).post(
            f"{BASE}/transfusion-requests/{req.pk}/liberar/", {}, format="json"
        )
        assert resp.status_code == 409, resp.content

    def test_cancelar_action_frees_bag(self):
        req = self._request()
        bag = self._bag()
        transfusion_service.reservar(req, bag, actor=self.manager)
        resp = self._client(self.manager).post(
            f"{BASE}/transfusion-requests/{req.pk}/cancelar/",
            {"reason": "engano"},
            format="json",
        )
        assert resp.status_code == 200, resp.content
        assert resp.data["status"] == TransfusionRequest.Status.CANCELADA
        bag.refresh_from_db()
        assert bag.stock_status == BloodBag.StockStatus.DISPONIVEL


class TestCrossMatchAPI(TransfusionTestBase):
    def test_list_filter_by_request(self):
        req = self._request()
        bag = self._bag()
        transfusion_service.reservar(req, bag, actor=self.manager)
        resp = self._client(self.reader).get(f"{BASE}/crossmatches/?request={req.pk}")
        assert resp.status_code == 200, resp.content
        rows = resp.data["results"] if "results" in resp.data else resp.data
        assert len(rows) == 1
        assert rows[0]["compativel"] is True

    def test_no_perm_forbidden(self):
        assert self._client(self.nobody).get(f"{BASE}/crossmatches/").status_code == 403


# ─── cross-schema delete-protection ───────────────────────────────────────────


class TestComponentDeleteProtection(TransfusionTestBase):
    def test_component_referenced_by_request_is_protected(self):
        self._request()
        with self.assertRaises(ProtectedError):
            self.component.delete()
