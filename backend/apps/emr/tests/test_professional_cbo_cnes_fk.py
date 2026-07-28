"""
M2-S1-T3 — emr.Professional ↔ core.CBOCode / core.CNESEstablishment FKs.

Covers: attaching a Professional to the governed CBO/CNES catalogs (FK set/read);
the backward-compatible ``cbo_code`` / ``cnes_code`` string accessors that
reconcile a raw code to the catalog (matched → FK, unmatched → legacy text +
flag); the cross-schema delete-protection signals (a referenced CBOCode /
CNESEstablishment cannot be hard-deleted); and the data-migration reconcile
helper preserving matched + unmatched rows.
"""

from django.db import transaction
from django.db.models.deletion import ProtectedError

from apps.core.catalog_backfill import reconcile_catalog_fk
from apps.core.models import CBOCode, CNESEstablishment, Role, User
from apps.emr.models import Professional
from apps.test_utils import TenantTestCase


def _user(email):
    role = Role.objects.create(name=f"role-{email}", permissions=[])
    return User.objects.create_user(email=email, password="pw", role=role)


def _professional(user, **kw):
    defaults = {"council_type": "CRM", "council_number": "1", "council_state": "SP"}
    defaults.update(kw)
    return Professional.objects.create(user=user, **defaults)


class TestProfessionalCatalogFK(TenantTestCase):
    def test_attach_cbo_and_cnes_via_fk(self):
        cbo = CBOCode.objects.create(code="225125", display="Médico clínico", family="2251")
        cnes = CNESEstablishment.objects.create(code="1000001", display="Hospital São João")
        prof = _professional(_user("a@x.com"), cbo=cbo, cnes=cnes)
        prof.refresh_from_db()
        self.assertEqual(prof.cbo_id, cbo.pk)
        self.assertEqual(prof.cnes_id, cnes.pk)
        self.assertEqual(prof.cbo.family, "2251")

    def test_fks_nullable_by_default(self):
        prof = _professional(_user("b@x.com"))
        self.assertIsNone(prof.cbo_id)
        self.assertIsNone(prof.cnes_id)
        self.assertEqual(prof.cbo_code, "")
        self.assertEqual(prof.cnes_code, "")

    def test_cbo_code_setter_matches_governed_code(self):
        CBOCode.objects.create(code="225125", display="Médico clínico")
        prof = _professional(_user("c@x.com"), cbo_code="225125")
        prof.refresh_from_db()
        self.assertEqual(prof.cbo_id, CBOCode.objects.get(code="225125").pk)
        self.assertEqual(prof.legacy_cbo_text, "")
        self.assertFalse(prof.cbo_unmatched)
        self.assertEqual(prof.cbo_code, "225125")

    def test_cbo_code_setter_preserves_unmatched(self):
        prof = _professional(_user("d@x.com"), cbo_code="999999")
        prof.refresh_from_db()
        self.assertIsNone(prof.cbo_id)
        self.assertEqual(prof.legacy_cbo_text, "999999")
        self.assertTrue(prof.cbo_unmatched)
        self.assertEqual(prof.cbo_code, "999999")  # accessor still returns raw

    def test_cnes_code_setter_matches_governed_code(self):
        CNESEstablishment.objects.create(code="1000001", display="Hospital São João")
        prof = _professional(_user("e@x.com"), cnes_code="1000001")
        prof.refresh_from_db()
        self.assertEqual(prof.cnes_id, CNESEstablishment.objects.get(code="1000001").pk)
        self.assertEqual(prof.legacy_cnes_text, "")
        self.assertFalse(prof.cnes_unmatched)


class TestCatalogDeleteProtection(TenantTestCase):
    def test_cbo_delete_blocked_when_referenced(self):
        cbo = CBOCode.objects.create(code="225125", display="Médico clínico")
        _professional(_user("f@x.com"), cbo=cbo)
        with self.assertRaises(ProtectedError) as ctx, transaction.atomic():
            cbo.delete()
        self.assertIn("CBOCode", str(ctx.exception))
        self.assertIn("Professional", str(ctx.exception))
        self.assertTrue(CBOCode.objects.filter(pk=cbo.pk).exists())

    def test_cbo_delete_allowed_when_unreferenced(self):
        cbo = CBOCode.objects.create(code="333333", display="Sem uso")
        cbo.delete()
        self.assertFalse(CBOCode.objects.filter(pk=cbo.pk).exists())

    def test_cnes_delete_blocked_when_referenced_by_professional(self):
        cnes = CNESEstablishment.objects.create(code="1000001", display="Hospital São João")
        _professional(_user("g@x.com"), cnes=cnes)
        with self.assertRaises(ProtectedError) as ctx, transaction.atomic():
            cnes.delete()
        self.assertIn("CNESEstablishment", str(ctx.exception))
        self.assertIn("Professional", str(ctx.exception))
        self.assertTrue(CNESEstablishment.objects.filter(pk=cnes.pk).exists())


class TestProfessionalBackfill(TenantTestCase):
    """Exercise the data-migration reconcile logic on real models."""

    def test_reconcile_matches_and_preserves_unmatched(self):
        CBOCode.objects.create(code="225125", display="Médico clínico")
        # Two professionals carrying only legacy text (as after the CharField rename).
        matched = _professional(_user("h@x.com"), council_number="1")
        Professional.objects.filter(pk=matched.pk).update(legacy_cbo_text="225125")
        unmatched = _professional(_user("i@x.com"), council_number="2")
        Professional.objects.filter(pk=unmatched.pk).update(legacy_cbo_text="999999")

        linked, unlinked = reconcile_catalog_fk(
            Professional,
            CBOCode,
            fk_field="cbo",
            legacy_field="legacy_cbo_text",
            unmatched_field="cbo_unmatched",
        )
        self.assertEqual((linked, unlinked), (1, 1))

        matched.refresh_from_db()
        self.assertEqual(matched.cbo_id, CBOCode.objects.get(code="225125").pk)
        self.assertEqual(matched.legacy_cbo_text, "")
        self.assertFalse(matched.cbo_unmatched)

        unmatched.refresh_from_db()
        self.assertIsNone(unmatched.cbo_id)
        self.assertEqual(unmatched.legacy_cbo_text, "999999")
        self.assertTrue(unmatched.cbo_unmatched)
