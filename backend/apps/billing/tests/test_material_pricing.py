"""
B4a — Material/OPME price source (Simpro) tests.
================================================
Cobre a fonte de preço de material/OPME modelada no B4a:

  * ``core.SimproMaterial`` — catálogo governado SHARED (subclasse de
    ``TerminologyCatalog``): persiste, ``normalized_display`` populado, default
    ``system=="simpro"``.
  * ``billing.MaterialPriceItem`` — valor negociado por (``PriceTable``, item
    Simpro); ``unique_together`` barra duplicata.
  * ``material_unit_value(price_table, simpro)`` — devolve o negociado quando
    existe, ``Decimal("0")`` quando não há preço (nem tabela).
  * cross-schema PROTECT: deletar um ``SimproMaterial`` referenciado por um
    ``MaterialPriceItem`` levanta ``ProtectedError``.

Espelha ``apps.billing.tests.test_inpatient_billing`` (usa ``TenantTestCase``).
"""

import datetime
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError

from apps.billing.material_models import MaterialPriceItem
from apps.billing.models import InsuranceProvider, PriceTable
from apps.billing.services.material_billing import material_unit_value
from apps.core.models import SimproMaterial, TUSSCode
from apps.test_utils import TenantTestCase


class MaterialPricingTestCase(TenantTestCase):
    def setUp(self):
        self.provider = InsuranceProvider.objects.create(name="Convênio X", ans_code="900001")
        self.table = PriceTable.objects.create(
            provider=self.provider,
            name="Tabela 2026",
            valid_from=datetime.date(2026, 1, 1),
        )
        self.tuss = TUSSCode.objects.create(
            code="90000010", description="Parafuso pedicular", group="material", version="2026-01"
        )
        self.simpro = SimproMaterial.objects.create(
            code="SP-001",
            display="Parafuso de titânio 4.5mm",
            kind=SimproMaterial.Kind.OPME,
            tuss_code=self.tuss,
            reference_price=Decimal("1250.5000"),
            edition="2026-07",
        )

    # ── SimproMaterial catálogo ──────────────────────────────────────────────
    def test_simpro_material_persists_and_normalizes(self):
        obj = SimproMaterial.objects.get(code="SP-001")
        self.assertEqual(obj.system, "simpro")  # default redeclarado
        self.assertEqual(obj.kind, "opme")
        self.assertEqual(obj.tuss_code_id, self.tuss.id)
        self.assertEqual(obj.reference_price, Decimal("1250.5000"))
        self.assertEqual(obj.edition, "2026-07")
        # normalized_display: sem acentos, minúsculas, sincronizado no save().
        self.assertEqual(obj.normalized_display, "parafuso de titanio 4.5mm")

    def test_simpro_material_default_kind_is_material(self):
        obj = SimproMaterial.objects.create(code="SP-999", display="Compressa")
        self.assertEqual(obj.kind, "material")
        self.assertEqual(obj.system, "simpro")

    # ── MaterialPriceItem ────────────────────────────────────────────────────
    def test_material_price_item_persists(self):
        item = MaterialPriceItem.objects.create(
            table=self.table, simpro=self.simpro, negotiated_value=Decimal("980.0000")
        )
        self.assertEqual(item.table_id, self.table.id)
        self.assertEqual(item.simpro_id, self.simpro.id)
        self.assertEqual(item.negotiated_value, Decimal("980.0000"))

    def test_material_price_item_unique_together_blocks_duplicate(self):
        MaterialPriceItem.objects.create(
            table=self.table, simpro=self.simpro, negotiated_value=Decimal("980.0000")
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            MaterialPriceItem.objects.create(
                table=self.table, simpro=self.simpro, negotiated_value=Decimal("1000.0000")
            )

    # ── helper de precificação ───────────────────────────────────────────────
    def test_material_unit_value_returns_negotiated_when_present(self):
        MaterialPriceItem.objects.create(
            table=self.table, simpro=self.simpro, negotiated_value=Decimal("980.0000")
        )
        self.assertEqual(material_unit_value(self.table, self.simpro), Decimal("980.0000"))

    def test_material_unit_value_zero_when_no_price(self):
        self.assertEqual(material_unit_value(self.table, self.simpro), Decimal("0"))

    def test_material_unit_value_zero_when_no_table(self):
        self.assertEqual(material_unit_value(None, self.simpro), Decimal("0"))

    # ── cross-schema PROTECT ─────────────────────────────────────────────────
    def test_delete_blocked_when_referenced_by_material_price_item(self):
        MaterialPriceItem.objects.create(
            table=self.table, simpro=self.simpro, negotiated_value=Decimal("980.0000")
        )
        with self.assertRaises(ProtectedError) as ctx, transaction.atomic():
            self.simpro.delete()
        self.assertIn("SimproMaterial", str(ctx.exception))
        self.assertIn("MaterialPriceItem", str(ctx.exception))
        self.assertTrue(SimproMaterial.objects.filter(pk=self.simpro.pk).exists())

    def test_delete_allowed_when_unreferenced(self):
        orphan = SimproMaterial.objects.create(code="SP-ORP", display="Sem uso")
        orphan.delete()
        self.assertFalse(SimproMaterial.objects.filter(pk=orphan.pk).exists())
