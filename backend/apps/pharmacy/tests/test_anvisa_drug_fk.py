"""
E3-T2 — pharmacy.Drug ↔ core.AnvisaProduct cross-schema FK + NF-e EAN match.

Covers: attaching a Drug to a governed catalog product (FK set/read); the legacy
``anvisa_code`` surviving the transition; the cross-schema delete-protection
signal (a referenced AnvisaProduct cannot be hard-deleted); and the NF-e line →
catalog auto-suggest by EAN barcode.
"""

from django.db import transaction
from django.db.models.deletion import ProtectedError

from apps.core.catalog_models import AnvisaProduct
from apps.pharmacy.models import Drug, NFeReceiptItem
from apps.pharmacy.services.nfe_catalog_match import (
    match_anvisa_product_by_ean,
    suggest_anvisa_product_for_item,
)
from apps.test_utils import TenantTestCase


def _product(**kw):
    defaults = {"code": "1000000000001", "display": "FAKE-Amoxicilina", "dcb": "Amoxicilina"}
    defaults.update(kw)
    return AnvisaProduct.objects.create(**defaults)


class TestDrugAnvisaProductFK(TenantTestCase):
    def test_attach_catalog_product_via_fk(self):
        prod = _product(ean="7891111111111")
        drug = Drug.objects.create(name="Amoxil 500mg", anvisa_product=prod)
        drug.refresh_from_db()
        self.assertEqual(drug.anvisa_product_id, prod.id)
        self.assertEqual(drug.anvisa_product.dcb, "Amoxicilina")

    def test_legacy_anvisa_code_preserved_alongside_fk(self):
        prod = _product()
        drug = Drug.objects.create(
            name="Amoxil 500mg", anvisa_code="9999999999999", anvisa_product=prod
        )
        drug.refresh_from_db()
        # Legacy free-text code kept during transition; FK is the governed anchor.
        self.assertEqual(drug.anvisa_code, "9999999999999")
        self.assertEqual(drug.anvisa_product_id, prod.id)

    def test_fk_nullable_by_default(self):
        drug = Drug.objects.create(name="Uncatalogued drug")
        self.assertIsNone(drug.anvisa_product_id)


class TestAnvisaProductDeleteProtection(TenantTestCase):
    def test_delete_blocked_when_referenced_by_drug(self):
        prod = _product()
        Drug.objects.create(name="Referencing drug", anvisa_product=prod)
        with self.assertRaises(ProtectedError) as ctx, transaction.atomic():
            prod.delete()
        self.assertIn("AnvisaProduct", str(ctx.exception))
        self.assertIn("Drug", str(ctx.exception))
        self.assertTrue(AnvisaProduct.objects.filter(pk=prod.pk).exists())

    def test_delete_allowed_when_unreferenced(self):
        prod = _product(code="2000000000002")
        prod.delete()
        self.assertFalse(AnvisaProduct.objects.filter(pk=prod.pk).exists())


class TestNFeEanMatch(TenantTestCase):
    def test_match_by_ean_returns_right_product(self):
        _product(code="A", display="Other", ean="7890000000000")
        target = _product(code="B", display="Target", ean="7891111111111")
        self.assertEqual(match_anvisa_product_by_ean("7891111111111"), target)

    def test_no_match_returns_none(self):
        _product(ean="7891111111111")
        self.assertIsNone(match_anvisa_product_by_ean("0000000000000"))
        self.assertIsNone(match_anvisa_product_by_ean(""))

    def test_suggest_for_nfe_item_by_barcode(self):
        target = _product(ean="7893333333333")
        # Build a lightweight NFeReceiptItem-like stub carrying just the barcode.
        item = NFeReceiptItem(barcode="7893333333333")
        self.assertEqual(suggest_anvisa_product_for_item(item), target)

    def test_suggest_for_item_without_barcode(self):
        _product(ean="7893333333333")
        item = NFeReceiptItem(barcode="")
        self.assertIsNone(suggest_anvisa_product_for_item(item))
