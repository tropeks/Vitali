"""
H2 — Banco de Sangue: doador + entrada de bolsa + sorologia (triagem RDC 34).

Covers:
  * BloodDonor CRUD with the hemoterapia.read / hemoterapia.manage split
  * BloodBagSerology.all_non_reactive property
  * registrar_sorologia service — the release rule:
      - todos marcadores nao_reagente → bag.serology_status=liberada,
        is_available() flips true (if not expired)
      - qualquer marcador reagente/indeterminado → serology_status=descartada
        + stock_status=descartada + not available
      - só sai de quarentena: re-testar bolsa liberada/descartada → ValidationError (409)
  * serology API: create routes through the service, ?bag= read filter, RBAC.

Mirrors setup from test_bloodbank_structure.py (BloodComponentCatalog + BloodBag).
"""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import BloodComponentCatalog, Role, User
from apps.emr.models import BloodBag, BloodBagSerology, BloodDonor
from apps.emr.services.blood_serology import registrar_sorologia
from apps.test_utils import TenantTestCase

BASE = "/api/v1"

MANAGE_PERMS = ["hemoterapia.read", "hemoterapia.manage"]
READ_PERMS = ["hemoterapia.read"]

PANEL = ["hiv", "hbsag", "anti_hbc", "anti_hcv", "sifilis", "chagas", "htlv"]


def _all_non_reactive():
    return {m: BloodBagSerology.Result.NAO_REAGENTE for m in PANEL}


# ─── model: BloodDonor + BloodBagSerology.all_non_reactive ─────────────────────


class TestBloodDonorModel(TenantTestCase):
    def test_donor_defaults(self):
        d = BloodDonor.objects.create(full_name="Doador Um", abo="O", rh_factor="negativo")
        self.assertTrue(d.apto)
        self.assertEqual(d.cpf, "")
        self.assertIsNone(d.birth_date)
        self.assertIsNone(d.last_donation)


class TestSerologyModel(TenantTestCase):
    def setUp(self):
        self.component = BloodComponentCatalog.objects.create(
            code="CH", display="Concentrado de hemácias", default_validade_dias=42
        )
        self.today = timezone.now().date()

    def _bag(self, **overrides):
        defaults = {
            "identifier": overrides.pop("identifier", "DIN-S1"),
            "component": self.component,
            "abo": "O",
            "rh_factor": "negativo",
            "volume_ml": 450,
            "collection_date": self.today,
            "expiry_date": self.today + timedelta(days=30),
        }
        defaults.update(overrides)
        return BloodBag.objects.create(**defaults)

    def test_all_non_reactive_true(self):
        s = BloodBagSerology.objects.create(bag=self._bag(), **_all_non_reactive())
        self.assertTrue(s.all_non_reactive)

    def test_all_non_reactive_false_when_reactive(self):
        markers = _all_non_reactive()
        markers["hiv"] = BloodBagSerology.Result.REAGENTE
        s = BloodBagSerology.objects.create(bag=self._bag(), **markers)
        self.assertFalse(s.all_non_reactive)

    def test_all_non_reactive_false_when_indeterminado(self):
        markers = _all_non_reactive()
        markers["chagas"] = BloodBagSerology.Result.INDETERMINADO
        s = BloodBagSerology.objects.create(bag=self._bag(), **markers)
        self.assertFalse(s.all_non_reactive)


# ─── service: registrar_sorologia (release rule) ──────────────────────────────


class TestRegistrarSorologia(TenantTestCase):
    def setUp(self):
        self.component = BloodComponentCatalog.objects.create(
            code="CH", display="Concentrado de hemácias", default_validade_dias=42
        )
        self.today = timezone.now().date()
        self.user = User.objects.create_user(
            email="tester@t.com",
            password="pw",
            role=Role.objects.create(name="hemo", permissions=MANAGE_PERMS),
        )

    def _bag(self, **overrides):
        defaults = {
            "identifier": overrides.pop("identifier", "DIN-R1"),
            "component": self.component,
            "abo": "O",
            "rh_factor": "negativo",
            "volume_ml": 450,
            "collection_date": self.today,
            "expiry_date": self.today + timedelta(days=30),
        }
        defaults.update(overrides)
        return BloodBag.objects.create(**defaults)

    def test_all_non_reactive_releases_and_available(self):
        bag = self._bag()
        self.assertFalse(bag.is_available())  # quarentena
        s = registrar_sorologia(bag, _all_non_reactive(), by=self.user)
        bag.refresh_from_db()
        self.assertEqual(bag.serology_status, BloodBag.SerologyStatus.LIBERADA)
        self.assertEqual(bag.stock_status, BloodBag.StockStatus.DISPONIVEL)
        self.assertTrue(bag.is_available())
        self.assertEqual(s.tested_by_id, self.user.id)
        self.assertIn(s, bag.serologies.all())

    def test_reactive_marker_discards_and_not_available(self):
        bag = self._bag(identifier="DIN-R2")
        markers = _all_non_reactive()
        markers["hbsag"] = BloodBagSerology.Result.REAGENTE
        registrar_sorologia(bag, markers, by=self.user)
        bag.refresh_from_db()
        self.assertEqual(bag.serology_status, BloodBag.SerologyStatus.DESCARTADA)
        self.assertEqual(bag.stock_status, BloodBag.StockStatus.DESCARTADA)
        self.assertFalse(bag.is_available())

    def test_indeterminado_discards(self):
        bag = self._bag(identifier="DIN-R3")
        markers = _all_non_reactive()
        markers["htlv"] = BloodBagSerology.Result.INDETERMINADO
        registrar_sorologia(bag, markers, by=self.user)
        bag.refresh_from_db()
        self.assertEqual(bag.serology_status, BloodBag.SerologyStatus.DESCARTADA)
        self.assertEqual(bag.stock_status, BloodBag.StockStatus.DESCARTADA)

    def test_retest_non_quarentena_rejected(self):
        bag = self._bag(identifier="DIN-R4")
        registrar_sorologia(bag, _all_non_reactive(), by=self.user)  # → liberada
        with self.assertRaises(ValidationError):
            registrar_sorologia(bag, _all_non_reactive(), by=self.user)

    def test_retest_discarded_rejected(self):
        bag = self._bag(identifier="DIN-R5")
        markers = _all_non_reactive()
        markers["sifilis"] = BloodBagSerology.Result.REAGENTE
        registrar_sorologia(bag, markers, by=self.user)  # → descartada
        with self.assertRaises(ValidationError):
            registrar_sorologia(bag, _all_non_reactive(), by=self.user)


# ─── DRF API: RBAC + serology endpoint + ?bag= filter ─────────────────────────


class BloodDonorAPITestBase(TenantTestCase):
    def setUp(self):
        self.manager = User.objects.create_user(
            email="mgr@t.com",
            password="pw",
            role=Role.objects.create(name="banco", permissions=MANAGE_PERMS),
        )
        self.reader = User.objects.create_user(
            email="rdr@t.com",
            password="pw",
            role=Role.objects.create(name="leitor", permissions=READ_PERMS),
        )
        self.nobody = User.objects.create_user(
            email="none@t.com",
            password="pw",
            role=Role.objects.create(name="sem", permissions=[]),
        )
        self.component = BloodComponentCatalog.objects.create(
            code="CH", display="Concentrado de hemácias", default_validade_dias=42
        )
        self.today = timezone.now().date()

    def _client(self, user):
        c = APIClient()
        c.defaults["SERVER_NAME"] = self.__class__.domain.domain
        c.force_authenticate(user)
        return c

    @staticmethod
    def _rows(resp):
        return resp.data["results"] if "results" in resp.data else resp.data

    def _bag(self, **overrides):
        defaults = {
            "identifier": overrides.pop("identifier", "DIN-API"),
            "component": self.component,
            "abo": "O",
            "rh_factor": "negativo",
            "volume_ml": 450,
            "collection_date": self.today,
            "expiry_date": self.today + timedelta(days=30),
        }
        defaults.update(overrides)
        return BloodBag.objects.create(**defaults)


class TestBloodDonorAPI(BloodDonorAPITestBase):
    def test_manager_creates_reader_lists(self):
        create = self._client(self.manager).post(
            f"{BASE}/blood-donors/",
            {"full_name": "Doador Api", "abo": "A", "rh_factor": "positivo"},
            format="json",
        )
        assert create.status_code == 201, create.content
        assert BloodDonor.objects.filter(full_name="Doador Api").exists()
        reader = self._client(self.reader)
        assert reader.get(f"{BASE}/blood-donors/").status_code == 200

    def test_reader_cannot_write(self):
        write = self._client(self.reader).post(
            f"{BASE}/blood-donors/",
            {"full_name": "X", "abo": "O", "rh_factor": "negativo"},
            format="json",
        )
        assert write.status_code == 403, write.content

    def test_no_perm_forbidden(self):
        assert self._client(self.nobody).get(f"{BASE}/blood-donors/").status_code == 403


class TestSerologyAPI(BloodDonorAPITestBase):
    def _payload(self, bag, **overrides):
        payload = {"bag": str(bag.pk), **_all_non_reactive()}
        payload.update(overrides)
        return payload

    def test_manager_registers_releases_bag(self):
        bag = self._bag(identifier="DIN-API1")
        resp = self._client(self.manager).post(
            f"{BASE}/blood-bag-serologies/", self._payload(bag), format="json"
        )
        assert resp.status_code == 201, resp.content
        bag.refresh_from_db()
        assert bag.serology_status == BloodBag.SerologyStatus.LIBERADA
        assert bag.is_available() is True

    def test_reactive_discards_via_api(self):
        bag = self._bag(identifier="DIN-API2")
        resp = self._client(self.manager).post(
            f"{BASE}/blood-bag-serologies/",
            self._payload(bag, hiv=BloodBagSerology.Result.REAGENTE),
            format="json",
        )
        assert resp.status_code == 201, resp.content
        bag.refresh_from_db()
        assert bag.serology_status == BloodBag.SerologyStatus.DESCARTADA
        assert bag.stock_status == BloodBag.StockStatus.DESCARTADA

    def test_retest_returns_409(self):
        bag = self._bag(identifier="DIN-API3")
        client = self._client(self.manager)
        first = client.post(f"{BASE}/blood-bag-serologies/", self._payload(bag), format="json")
        assert first.status_code == 201, first.content
        second = client.post(f"{BASE}/blood-bag-serologies/", self._payload(bag), format="json")
        assert second.status_code == 409, second.content

    def test_reader_cannot_register(self):
        bag = self._bag(identifier="DIN-API4")
        resp = self._client(self.reader).post(
            f"{BASE}/blood-bag-serologies/", self._payload(bag), format="json"
        )
        assert resp.status_code == 403, resp.content

    def test_bag_filter_and_read(self):
        bag1 = self._bag(identifier="DIN-API5")
        bag2 = self._bag(identifier="DIN-API6")
        client = self._client(self.manager)
        client.post(f"{BASE}/blood-bag-serologies/", self._payload(bag1), format="json")
        client.post(
            f"{BASE}/blood-bag-serologies/",
            self._payload(bag2, chagas=BloodBagSerology.Result.REAGENTE),
            format="json",
        )
        reader = self._client(self.reader)
        all_rows = self._rows(reader.get(f"{BASE}/blood-bag-serologies/"))
        assert len(all_rows) == 2
        filtered = self._rows(reader.get(f"{BASE}/blood-bag-serologies/?bag={bag1.pk}"))
        assert len(filtered) == 1
        assert str(filtered[0]["bag"]) == str(bag1.pk)
        assert filtered[0]["all_non_reactive"] is True
