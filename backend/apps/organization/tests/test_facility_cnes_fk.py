"""
M2-S1-T3 — organization.Facility ↔ core.CNESEstablishment FK.

Covers: attaching a Facility to the governed CNES catalog (FK set/read); the
``cnes_code`` accessor reconciling a raw code (matched → FK, unmatched → legacy
text + flag); the cross-schema delete-protection signal (a referenced
CNESEstablishment cannot be hard-deleted); and the data-migration reconcile
helper preserving matched + unmatched rows.
"""

from django.db import transaction
from django.db.models.deletion import ProtectedError

from apps.core.catalog_backfill import reconcile_catalog_fk
from apps.core.models import CNESEstablishment
from apps.organization.models import Facility, LegalEntity
from apps.test_utils import TenantTestCase


def _legal_entity(code="LE-1"):
    return LegalEntity.objects.create(code=code, name="Grupo Vitali")


def _facility(le, code="FAC-1", **kw):
    return Facility.objects.create(code=code, name="Unidade Central", legal_entity=le, **kw)


class TestFacilityCnesFK(TenantTestCase):
    def test_attach_cnes_via_fk(self):
        cnes = CNESEstablishment.objects.create(code="1000001", display="Hospital São João")
        fac = _facility(_legal_entity(), cnes=cnes)
        fac.refresh_from_db()
        self.assertEqual(fac.cnes_id, cnes.pk)
        self.assertEqual(fac.cnes.display, "Hospital São João")

    def test_cnes_nullable_by_default(self):
        fac = _facility(_legal_entity())
        self.assertIsNone(fac.cnes_id)
        self.assertEqual(fac.cnes_code, "")

    def test_cnes_code_setter_matches_governed_code(self):
        CNESEstablishment.objects.create(code="1000001", display="Hospital São João")
        fac = _facility(_legal_entity(), cnes_code="1000001")
        fac.refresh_from_db()
        self.assertEqual(fac.cnes_id, CNESEstablishment.objects.get(code="1000001").pk)
        self.assertEqual(fac.legacy_cnes_text, "")
        self.assertFalse(fac.cnes_unmatched)

    def test_cnes_code_setter_preserves_unmatched(self):
        fac = _facility(_legal_entity(), cnes_code="999999")
        fac.refresh_from_db()
        self.assertIsNone(fac.cnes_id)
        self.assertEqual(fac.legacy_cnes_text, "999999")
        self.assertTrue(fac.cnes_unmatched)


class TestFacilityCnesDeleteProtection(TenantTestCase):
    def test_cnes_delete_blocked_when_referenced_by_facility(self):
        cnes = CNESEstablishment.objects.create(code="1000001", display="Hospital São João")
        _facility(_legal_entity(), cnes=cnes)
        with self.assertRaises(ProtectedError) as ctx, transaction.atomic():
            cnes.delete()
        self.assertIn("CNESEstablishment", str(ctx.exception))
        self.assertIn("Facility", str(ctx.exception))
        self.assertTrue(CNESEstablishment.objects.filter(pk=cnes.pk).exists())


class TestFacilityBackfill(TenantTestCase):
    def test_reconcile_matches_and_preserves_unmatched(self):
        CNESEstablishment.objects.create(code="1000001", display="Hospital São João")
        le = _legal_entity()
        matched = _facility(le, code="FAC-M")
        Facility.objects.filter(pk=matched.pk).update(legacy_cnes_text="1000001")
        unmatched = _facility(le, code="FAC-U")
        Facility.objects.filter(pk=unmatched.pk).update(legacy_cnes_text="999999")

        linked, unlinked = reconcile_catalog_fk(
            Facility,
            CNESEstablishment,
            fk_field="cnes",
            legacy_field="legacy_cnes_text",
            unmatched_field="cnes_unmatched",
        )
        self.assertEqual((linked, unlinked), (1, 1))

        matched.refresh_from_db()
        self.assertEqual(matched.cnes_id, CNESEstablishment.objects.get(code="1000001").pk)
        self.assertEqual(matched.legacy_cnes_text, "")
        self.assertFalse(matched.cnes_unmatched)

        unmatched.refresh_from_db()
        self.assertIsNone(unmatched.cnes_id)
        self.assertEqual(unmatched.legacy_cnes_text, "999999")
        self.assertTrue(unmatched.cnes_unmatched)
