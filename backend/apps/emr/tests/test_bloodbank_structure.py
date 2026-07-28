"""
H1 — Banco de Sangue/Hemoterapia: estrutura (tipagem + hemocomponente + estoque).

Covers:
  * the governed BloodComponentCatalog searchable via the terminology registry
  * the import_blood_components importer creating components from the sample
  * BloodBag CRUD with the hemoterapia.read / hemoterapia.manage split (manager
    writes; reader lists but is 403 on write)
  * ``is_available()`` logic (quarantined / reserved / expired bag not available)
  * the ``?available=true`` + abo/rh/serology/stock filters
  * Patient ``abo`` / ``rh_factor`` round-trip
  * cross-schema BloodComponentCatalog delete-protection (ProtectedError)

Mirrors setup from test_adt_beds_api.py / test_adt_catalog.py.
"""

from datetime import timedelta
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.management.commands.import_blood_components import Command as ImportBloodComponents
from apps.core.models import BloodComponentCatalog, Role, User
from apps.core.terminology import UnknownTerminologySystem, search
from apps.core.terminology_base import TerminologyImportLog
from apps.emr.models import BloodBag, Patient
from apps.test_utils import TenantTestCase

BASE = "/api/v1"
CORE_FIXTURES = Path(__file__).resolve().parents[3] / "apps" / "core" / "tests" / "fixtures"

MANAGE_PERMS = ["hemoterapia.read", "hemoterapia.manage"]
READ_PERMS = ["hemoterapia.read"]


def _run(cmd, **options):
    out = StringIO()
    call_command(cmd, stdout=out, stderr=out, **options)
    return out.getvalue()


# ─── catalog: terminology registry ────────────────────────────────────────────


class TestBloodComponentCatalog(TenantTestCase):
    def setUp(self):
        BloodComponentCatalog.objects.create(
            code="CH",
            display="Concentrado de hemácias",
            default_validade_dias=42,
            context="Hemácias",
        )
        BloodComponentCatalog.objects.create(code="OLD", display="Inativo antigo", active=False)

    def test_system_default_and_normalized_display(self):
        c = BloodComponentCatalog.objects.get(code="CH")
        self.assertEqual(c.system, "blood_component")
        self.assertEqual(c.normalized_display, "concentrado de hemacias")

    def test_search_exact_code(self):
        results = search("blood_component", "CH")
        self.assertEqual(results[0]["code"], "CH")
        self.assertEqual(results[0]["system"], "blood_component")
        self.assertEqual(results[0]["display"], "Concentrado de hemácias")

    def test_search_context_fields(self):
        ctx = search("blood_component", "CH")[0]["context"]
        self.assertEqual(ctx["default_validade_dias"], 42)
        self.assertEqual(ctx["context"], "Hemácias")

    def test_search_active_only(self):
        codes = [r["code"] for r in search("blood_component", "OLD")]
        self.assertNotIn("OLD", codes)

    def test_unknown_system_raises(self):
        with self.assertRaises(UnknownTerminologySystem):
            search("bogus-blood", "x")


# ─── importer ─────────────────────────────────────────────────────────────────


class TestImportBloodComponents(TenantTestCase):
    SAMPLE = CORE_FIXTURES / "blood_components_sample.csv"
    MALFORMED = CORE_FIXTURES / "blood_components_malformed.csv"

    def test_creates_rows_with_all_fields(self):
        _run(ImportBloodComponents(), source=str(self.SAMPLE))
        self.assertEqual(BloodComponentCatalog.objects.count(), 4)
        c = BloodComponentCatalog.objects.get(code="CH")
        self.assertEqual(c.display, "FAKE-Concentrado de hemácias")
        self.assertEqual(c.default_validade_dias, 42)
        self.assertEqual(c.context, "FAKE-Hemácias")
        self.assertEqual(c.system, "blood_component")
        self.assertTrue(c.active)

    def test_idempotent_and_provenance(self):
        _run(ImportBloodComponents(), source=str(self.SAMPLE))
        _run(ImportBloodComponents(), source=str(self.SAMPLE))
        self.assertEqual(BloodComponentCatalog.objects.count(), 4)
        log = TerminologyImportLog.objects.filter(system="blood_component").latest("ran_at")
        self.assertEqual(log.provenance, "ISBT-128/HEMOBRAS")
        self.assertEqual(log.status, TerminologyImportLog.Status.SUCCESS)

    def test_dry_run_writes_nothing(self):
        _run(ImportBloodComponents(), source=str(self.SAMPLE), dry_run=True)
        self.assertEqual(BloodComponentCatalog.objects.count(), 0)

    def test_malformed_csv_aborts(self):
        with self.assertRaises(CommandError):
            _run(ImportBloodComponents(), source=str(self.MALFORMED))
        self.assertEqual(BloodComponentCatalog.objects.count(), 0)


# ─── model: is_available ──────────────────────────────────────────────────────


class TestBloodBagIsAvailable(TenantTestCase):
    def setUp(self):
        self.component = BloodComponentCatalog.objects.create(
            code="CH", display="Concentrado de hemácias", default_validade_dias=42
        )
        self.today = timezone.now().date()

    def _bag(self, **overrides):
        defaults = {
            "identifier": overrides.pop("identifier", "DIN-001"),
            "component": self.component,
            "abo": BloodBag.ABO.O,
            "rh_factor": BloodBag.RhFactor.NEGATIVO,
            "volume_ml": 450,
            "collection_date": self.today - timedelta(days=1),
            "expiry_date": self.today + timedelta(days=30),
            "serology_status": BloodBag.SerologyStatus.LIBERADA,
            "stock_status": BloodBag.StockStatus.DISPONIVEL,
        }
        defaults.update(overrides)
        return BloodBag.objects.create(**defaults)

    def test_released_available_not_expired_is_available(self):
        self.assertTrue(self._bag().is_available())

    def test_quarantined_default_not_available(self):
        bag = self._bag(identifier="DIN-Q", serology_status=BloodBag.SerologyStatus.QUARENTENA)
        self.assertFalse(bag.is_available())

    def test_reserved_not_available(self):
        bag = self._bag(identifier="DIN-R", stock_status=BloodBag.StockStatus.RESERVADA)
        self.assertFalse(bag.is_available())

    def test_expired_not_available(self):
        bag = self._bag(identifier="DIN-E", expiry_date=self.today - timedelta(days=1))
        self.assertFalse(bag.is_available())

    def test_default_serology_status_quarentena(self):
        bag = BloodBag.objects.create(
            identifier="DIN-DEF",
            component=self.component,
            abo=BloodBag.ABO.A,
            rh_factor=BloodBag.RhFactor.POSITIVO,
            volume_ml=300,
            collection_date=self.today,
            expiry_date=self.today + timedelta(days=5),
        )
        self.assertEqual(bag.serology_status, BloodBag.SerologyStatus.QUARENTENA)
        self.assertEqual(bag.stock_status, BloodBag.StockStatus.DISPONIVEL)


# ─── Patient imunohematologia round-trip ──────────────────────────────────────


class TestPatientImunohematologia(TenantTestCase):
    def test_abo_rh_round_trip(self):
        p = Patient.objects.create(
            full_name="Fulano",
            cpf="12345678900",
            birth_date="1990-01-01",
            gender="M",
            abo="O",
            rh_factor="negativo",
            antibody_screen="negativo",
        )
        p.refresh_from_db()
        self.assertEqual(p.abo, "O")
        self.assertEqual(p.rh_factor, "negativo")
        self.assertEqual(p.antibody_screen, "negativo")
        # legacy free-text blood_type is untouched and independent
        self.assertEqual(p.blood_type, "")

    def test_abo_rh_blank_by_default(self):
        p = Patient.objects.create(
            full_name="Sicrano", cpf="98765432100", birth_date="1985-05-05", gender="F"
        )
        self.assertEqual(p.abo, "")
        self.assertEqual(p.rh_factor, "")


# ─── DRF API: RBAC + filters ──────────────────────────────────────────────────


class BloodBankAPITestBase(TenantTestCase):
    def setUp(self):
        self.manage_role = Role.objects.create(name="banco_sangue", permissions=MANAGE_PERMS)
        self.read_role = Role.objects.create(name="leitor_hemo", permissions=READ_PERMS)
        self.none_role = Role.objects.create(name="sem_perm_hemo", permissions=[])
        self.manager = User.objects.create_user(
            email="agencia@t.com", password="pw", role=self.manage_role
        )
        self.reader = User.objects.create_user(
            email="med@t.com", password="pw", role=self.read_role
        )
        self.nobody = User.objects.create_user(
            email="none-hemo@t.com", password="pw", role=self.none_role
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

    def _bag_payload(self, **overrides):
        payload = {
            "identifier": "DIN-100",
            "component": str(self.component.pk),
            "abo": "O",
            "rh_factor": "negativo",
            "volume_ml": 450,
            "collection_date": str(self.today - timedelta(days=1)),
            "expiry_date": str(self.today + timedelta(days=30)),
        }
        payload.update(overrides)
        return payload


class TestBloodComponentAPI(BloodBankAPITestBase):
    def test_reader_lists_manager_creates(self):
        reader = self._client(self.reader)
        assert reader.get(f"{BASE}/blood-components/").status_code == 200
        write = reader.post(
            f"{BASE}/blood-components/",
            {"code": "PFC", "display": "Plasma fresco congelado"},
            format="json",
        )
        assert write.status_code == 403, write.content
        mgr = self._client(self.manager).post(
            f"{BASE}/blood-components/",
            {"code": "PFC", "display": "Plasma fresco congelado"},
            format="json",
        )
        assert mgr.status_code == 201, mgr.content

    def test_no_perm_forbidden(self):
        assert self._client(self.nobody).get(f"{BASE}/blood-components/").status_code == 403


class TestBloodBagAPI(BloodBankAPITestBase):
    def test_manager_creates_bag_defaults_quarentena(self):
        resp = self._client(self.manager).post(
            f"{BASE}/blood-bags/", self._bag_payload(), format="json"
        )
        assert resp.status_code == 201, resp.content
        bag = BloodBag.objects.get(pk=resp.data["id"])
        assert bag.serology_status == BloodBag.SerologyStatus.QUARENTENA
        assert bag.stock_status == BloodBag.StockStatus.DISPONIVEL
        assert bag.created_by_id == self.manager.id
        assert resp.data["available"] is False  # quarantined
        assert resp.data["component_code"] == "CH"

    def test_reader_can_list_not_write(self):
        BloodBag.objects.create(
            identifier="DIN-L",
            component=self.component,
            abo="A",
            rh_factor="positivo",
            volume_ml=300,
            collection_date=self.today,
            expiry_date=self.today + timedelta(days=5),
        )
        reader = self._client(self.reader)
        assert reader.get(f"{BASE}/blood-bags/").status_code == 200
        write = reader.post(
            f"{BASE}/blood-bags/", self._bag_payload(identifier="DIN-X"), format="json"
        )
        assert write.status_code == 403, write.content

    def test_no_perm_forbidden(self):
        assert self._client(self.nobody).get(f"{BASE}/blood-bags/").status_code == 403

    def test_available_filter(self):
        # available bag
        BloodBag.objects.create(
            identifier="DIN-AV",
            component=self.component,
            abo="O",
            rh_factor="negativo",
            volume_ml=450,
            collection_date=self.today,
            expiry_date=self.today + timedelta(days=30),
            serology_status=BloodBag.SerologyStatus.LIBERADA,
            stock_status=BloodBag.StockStatus.DISPONIVEL,
        )
        # quarantined bag (not available)
        BloodBag.objects.create(
            identifier="DIN-QU",
            component=self.component,
            abo="O",
            rh_factor="negativo",
            volume_ml=450,
            collection_date=self.today,
            expiry_date=self.today + timedelta(days=30),
        )
        c = self._client(self.reader)
        all_rows = self._rows(c.get(f"{BASE}/blood-bags/"))
        assert len(all_rows) == 2
        avail = self._rows(c.get(f"{BASE}/blood-bags/?available=true"))
        assert len(avail) == 1
        assert avail[0]["identifier"] == "DIN-AV"

    def test_abo_rh_and_status_filters(self):
        BloodBag.objects.create(
            identifier="DIN-A1",
            component=self.component,
            abo="A",
            rh_factor="positivo",
            volume_ml=450,
            collection_date=self.today,
            expiry_date=self.today + timedelta(days=30),
            serology_status=BloodBag.SerologyStatus.LIBERADA,
        )
        BloodBag.objects.create(
            identifier="DIN-O1",
            component=self.component,
            abo="O",
            rh_factor="negativo",
            volume_ml=450,
            collection_date=self.today,
            expiry_date=self.today + timedelta(days=30),
            stock_status=BloodBag.StockStatus.RESERVADA,
        )
        c = self._client(self.reader)
        assert len(self._rows(c.get(f"{BASE}/blood-bags/?abo=A"))) == 1
        assert len(self._rows(c.get(f"{BASE}/blood-bags/?rh_factor=negativo"))) == 1
        assert len(self._rows(c.get(f"{BASE}/blood-bags/?serology_status=liberada"))) == 1
        assert len(self._rows(c.get(f"{BASE}/blood-bags/?stock_status=reservada"))) == 1
        assert len(self._rows(c.get(f"{BASE}/blood-bags/?component={self.component.pk}"))) == 2


# ─── cross-schema delete protection ───────────────────────────────────────────


class TestBloodComponentDeleteProtection(TenantTestCase):
    def test_delete_blocked_when_referenced_by_bag(self):
        today = timezone.now().date()
        component = BloodComponentCatalog.objects.create(
            code="CH", display="Concentrado de hemácias"
        )
        BloodBag.objects.create(
            identifier="DIN-P",
            component=component,
            abo="O",
            rh_factor="negativo",
            volume_ml=450,
            collection_date=today,
            expiry_date=today + timedelta(days=30),
        )
        with self.assertRaises(ProtectedError) as ctx, transaction.atomic():
            component.delete()
        self.assertIn("BloodComponentCatalog", str(ctx.exception))
        self.assertIn("BloodBag", str(ctx.exception))
        self.assertTrue(BloodComponentCatalog.objects.filter(pk=component.pk).exists())

    def test_delete_allowed_when_unreferenced(self):
        component = BloodComponentCatalog.objects.create(code="ZZ", display="Sem uso")
        component.delete()
        self.assertFalse(BloodComponentCatalog.objects.filter(pk=component.pk).exists())
