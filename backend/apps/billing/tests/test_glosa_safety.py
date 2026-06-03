"""Service + gate + ack tests for the glosa-safety wedge (PR G1).

Mirrors apps.emr.tests.test_dose_safety_enforcement: flag-OFF regression guard,
flag-ON blocking, per-guia 409 naming only the offending guide, acknowledge →
re-close, advise-only checks do NOT 409, cross-guide duplicate detection.

Run: python manage.py test apps.billing.tests.test_glosa_safety
"""

import datetime
from decimal import Decimal

from django.core.cache import cache
from rest_framework.test import APIClient

from apps.billing.models import (
    GlosaSafetyAlert,
    InsuranceProvider,
    PriceTable,
    PriceTableItem,
    TISSBatch,
    TISSGuide,
    TISSGuideItem,
)
from apps.billing.services.glosa_safety import GlosaSafetyService
from apps.core.models import FeatureFlag, Role, TUSSCode, User
from apps.emr.models import Encounter, Patient, Professional
from apps.test_utils import TenantTestCase


class GlosaSafetyTestCase(TenantTestCase):
    """Glosa-safety service + batch-close gate tests."""

    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain

        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant, module_key="billing", defaults={"is_enabled": True}
        )

        self.faturista_role = Role.objects.create(
            name="faturista",
            permissions=["billing.read", "billing.write"],
            is_system=True,
        )
        self.faturista = User.objects.create_user(
            email="faturista@test.com",
            full_name="Faturista Test",
            password="Str0ng!Pass#2024",
            role=self.faturista_role,
        )
        prof_user = User.objects.create_user(
            email="medico@test.com",
            full_name="Dr. Test",
            password="Str0ng!Pass#2024",
            role=self.faturista_role,
        )

        self.patient = Patient.objects.create(
            full_name="Maria Test",
            cpf="000.000.000-00",
            birth_date=datetime.date(1985, 1, 1),
            gender="F",
        )
        self.professional = Professional.objects.create(
            user=prof_user,
            council_type="CRM",
            council_number="99999",
            council_state="SP",
        )
        self.encounter = Encounter.objects.create(
            patient=self.patient,
            professional=self.professional,
        )
        self.provider = InsuranceProvider.objects.create(name="Unimed Test", ans_code="999999")

        # TUSS codes (public schema) + active price table covering 2026-03.
        self.tuss_a = TUSSCode.objects.create(
            code="10101012", description="Consulta", group="procedimento", version="2024-01"
        )
        self.tuss_b = TUSSCode.objects.create(
            code="40304361", description="Hemograma", group="procedimento", version="2024-01"
        )
        self.table = PriceTable.objects.create(
            provider=self.provider,
            name="Tabela 2026",
            valid_from=datetime.date(2026, 1, 1),
            is_active=True,
        )
        PriceTableItem.objects.create(
            table=self.table, tuss_code=self.tuss_a, negotiated_value=Decimal("100.00")
        )
        PriceTableItem.objects.create(
            table=self.table, tuss_code=self.tuss_b, negotiated_value=Decimal("50.00")
        )

        self.fat_token = self._get_token("faturista@test.com")

    # ── helpers ───────────────────────────────────────────────────────────────

    def _get_token(self, email):
        resp = self.client.post(
            "/api/v1/auth/login",
            {"email": email, "password": "Str0ng!Pass#2024"},
            format="json",
        )
        return resp.json().get("access")

    def _auth(self):
        c = APIClient()
        c.defaults["SERVER_NAME"] = self.__class__.domain.domain
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {self.fat_token}")
        return c

    def _enable_glosa(self):
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key="glosa_safety",
            defaults={"is_enabled": True},
        )

    def _make_guide(self, *, encounter=None, tuss=None, unit_value=Decimal("100.00"), **kw):
        defaults = {
            "guide_type": "sadt",
            "encounter": encounter or self.encounter,
            "patient": self.patient,
            "provider": self.provider,
            "insured_card_number": "0001234567890001",
            "competency": "2026-03",
            "cid10_codes": [{"code": "J00"}],
            "status": "pending",
        }
        defaults.update(kw)
        guide = TISSGuide.objects.create(**defaults)
        TISSGuideItem.objects.create(
            guide=guide,
            tuss_code=tuss or self.tuss_a,
            description="x",
            quantity=Decimal("1"),
            unit_value=unit_value,
        )
        return guide

    def _make_batch(self, *guides):
        batch = TISSBatch.objects.create(provider=self.provider, status="open")
        for g in guides:
            batch.guides.add(g)
        return batch

    # ── flag OFF regression guards ───────────────────────────────────────────

    def test_flag_off_evaluate_guide_is_noop(self):
        guide = self._make_guide(tuss=self.tuss_b, unit_value=Decimal("999.00"))
        svc = GlosaSafetyService(requesting_user=self.faturista)
        svc.evaluate_guide(guide, gate="batch_close")
        self.assertFalse(GlosaSafetyAlert.objects.filter(guide=guide).exists())
        self.assertFalse(GlosaSafetyService.has_blocking_glosa_alert(guide))

    def test_flag_off_close_does_not_409_even_with_stale_block_alert(self):
        # A stale flagged BLOCK alert from a previously-ON period must NOT lock
        # the gate once the flag is OFF (mirrors the dose flag-off fix).
        guide = self._make_guide()
        GlosaSafetyAlert.objects.create(
            guide=guide,
            check_code="duplicate",
            severity="block",
            source="engine",
            status="flagged",
            message="stale",
        )
        batch = self._make_batch(guide)
        resp = self._auth().post(f"/api/v1/billing/batches/{batch.id}/close/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "closed")

    # ── flag ON gate behavior ──────────────────────────────────────────────────

    def test_duplicate_line_blocks_close_with_409(self):
        self._enable_glosa()
        # Two guides, same encounter + same TUSS → both lines duplicate.
        g1 = self._make_guide()
        g2 = self._make_guide()  # same encounter + tuss_a
        batch = self._make_batch(g1, g2)

        resp = self._auth().post(f"/api/v1/billing/batches/{batch.id}/close/")
        self.assertEqual(resp.status_code, 409)
        body = resp.json()
        self.assertEqual(body["code"], "glosa_safety_block")
        self.assertTrue(len(body["guides"]) >= 1)
        # Batch must NOT be closed.
        batch.refresh_from_db()
        self.assertEqual(batch.status, "open")

    def test_409_names_only_the_bad_guide(self):
        self._enable_glosa()
        # Bad guide: a TUSS not in the active table (block). Clean guide: tabulated.
        other_encounter = Encounter.objects.create(
            patient=self.patient, professional=self.professional
        )
        tuss_untabled = TUSSCode.objects.create(
            code="99999999", description="X", group="procedimento", version="2024-01"
        )
        bad = self._make_guide(encounter=other_encounter, tuss=tuss_untabled)
        clean_encounter = Encounter.objects.create(
            patient=self.patient, professional=self.professional
        )
        clean = self._make_guide(
            encounter=clean_encounter, tuss=self.tuss_b, unit_value=Decimal("50.00")
        )
        batch = self._make_batch(bad, clean)

        resp = self._auth().post(f"/api/v1/billing/batches/{batch.id}/close/")
        self.assertEqual(resp.status_code, 409)
        guide_ids = {g["guide_id"] for g in resp.json()["guides"]}
        self.assertIn(str(bad.id), guide_ids)
        self.assertNotIn(str(clean.id), guide_ids)

    def test_acknowledge_block_then_reclose_succeeds(self):
        self._enable_glosa()
        other_encounter = Encounter.objects.create(
            patient=self.patient, professional=self.professional
        )
        tuss_untabled = TUSSCode.objects.create(
            code="99999999", description="X", group="procedimento", version="2024-01"
        )
        bad = self._make_guide(encounter=other_encounter, tuss=tuss_untabled)
        batch = self._make_batch(bad)
        client = self._auth()

        resp = client.post(f"/api/v1/billing/batches/{batch.id}/close/")
        self.assertEqual(resp.status_code, 409)
        alert_id = resp.json()["guides"][0]["alerts"][0]["id"]

        ack = client.post(
            f"/api/v1/billing/glosa-safety-alerts/{alert_id}/acknowledge/",
            {"reason": "Procedimento aprovado manualmente pelo convênio."},
            format="json",
        )
        self.assertEqual(ack.status_code, 200)

        reclose = client.post(f"/api/v1/billing/batches/{batch.id}/close/")
        self.assertEqual(reclose.status_code, 200)
        self.assertEqual(reclose.json()["status"], "closed")

    def test_advise_checks_do_not_409(self):
        self._enable_glosa()
        # stale_price (snapshot diverges from active table) + incomplete (no CID)
        # are advise — recorded but must NOT block the close.
        guide = self._make_guide(tuss=self.tuss_b, unit_value=Decimal("75.00"), cid10_codes=[])
        batch = self._make_batch(guide)
        resp = self._auth().post(f"/api/v1/billing/batches/{batch.id}/close/")
        self.assertEqual(resp.status_code, 200)
        # Advisory alerts were recorded.
        codes = set(
            GlosaSafetyAlert.objects.filter(guide=guide).values_list("check_code", flat=True)
        )
        self.assertIn("stale_price", codes)
        self.assertIn("incomplete", codes)
        for a in GlosaSafetyAlert.objects.filter(guide=guide):
            self.assertEqual(a.severity, "advise")

    def test_duplicate_detected_across_two_guides_same_encounter_tuss(self):
        self._enable_glosa()
        g1 = self._make_guide()
        g2 = self._make_guide()  # same encounter + tuss_a
        svc = GlosaSafetyService(requesting_user=self.faturista)
        svc.evaluate_guide(g1, gate="batch_close")
        svc.evaluate_guide(g2, gate="batch_close")
        self.assertTrue(
            GlosaSafetyAlert.objects.filter(
                guide=g1, check_code="duplicate", severity="block", status="flagged"
            ).exists()
        )
        self.assertTrue(GlosaSafetyService.has_blocking_glosa_alert(g2))

    # ── FIX 1: NULL-guide_item uniqueness (no MultipleObjectsReturned brick) ──

    def test_repeated_guide_level_alert_yields_single_row(self):
        self._enable_glosa()
        # A guide missing CID-10 → a guide-level (guide_item NULL) incomplete
        # advise. Two consecutive evaluations must NOT accumulate duplicate rows.
        other = Encounter.objects.create(patient=self.patient, professional=self.professional)
        guide = self._make_guide(encounter=other, tuss=self.tuss_b, cid10_codes=[])
        svc = GlosaSafetyService(requesting_user=self.faturista)
        svc.evaluate_guide(guide, gate="batch_close")
        svc.evaluate_guide(guide, gate="batch_close")
        self.assertEqual(
            GlosaSafetyAlert.objects.filter(
                guide=guide, check_code="incomplete", guide_item__isnull=True
            ).count(),
            1,
        )

    def test_constraint_blocks_duplicate_guide_level_row(self):
        self._enable_glosa()
        other = Encounter.objects.create(patient=self.patient, professional=self.professional)
        guide = self._make_guide(encounter=other, tuss=self.tuss_b, cid10_codes=[])
        GlosaSafetyAlert.objects.create(
            guide=guide,
            guide_item=None,
            check_code="incomplete",
            source="engine",
            severity="advise",
            status="flagged",
            message="m1",
        )
        # nulls_distinct=False → inserting a second NULL-guide_item row on the
        # same key must violate the unique constraint.
        from django.db import IntegrityError, transaction

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                GlosaSafetyAlert.objects.create(
                    guide=guide,
                    guide_item=None,
                    check_code="incomplete",
                    source="engine",
                    severity="advise",
                    status="flagged",
                    message="m2",
                )

    def test_engine_error_advisory_uses_distinct_check_code(self):
        self._enable_glosa()
        other = Encounter.objects.create(patient=self.patient, professional=self.professional)
        guide = self._make_guide(encounter=other, tuss=self.tuss_b)
        svc = GlosaSafetyService(requesting_user=self.faturista)
        # Force the engine to raise so fail-open fires.
        from unittest import mock

        with mock.patch.object(
            GlosaSafetyService, "_build_context", side_effect=RuntimeError("boom")
        ):
            svc.evaluate_guide(guide, gate="batch_close")
        alerts = GlosaSafetyAlert.objects.filter(guide=guide)
        codes = set(alerts.values_list("check_code", flat=True))
        self.assertIn("engine_error", codes)
        self.assertNotIn("incomplete", codes)
        # Advisory, never blocking.
        err = alerts.get(check_code="engine_error")
        self.assertEqual(err.severity, "advise")

    # ── FIX 2: mid-month table resolves; no resolvable table fails to advise ──

    def test_midmonth_table_resolves_no_false_not_in_table(self):
        self._enable_glosa()
        today = datetime.date.today()
        # Provider whose ONLY active table was negotiated mid-period: valid_from
        # on the 15th of this month (after the 1st). The old 1st-of-month floor
        # would exclude it → false not_in_table for every line. With the fix the
        # guide's effective date (created today) is covered.
        prov = InsuranceProvider.objects.create(name="MidMonth", ans_code="777777")
        midmonth = today.replace(day=15) if today.day >= 15 else today
        table = PriceTable.objects.create(
            provider=prov, name="Mid", valid_from=midmonth, is_active=True
        )
        PriceTableItem.objects.create(
            table=table, tuss_code=self.tuss_a, negotiated_value=Decimal("100.00")
        )
        enc = Encounter.objects.create(patient=self.patient, professional=self.professional)
        guide = self._make_guide(
            encounter=enc, provider=prov, tuss=self.tuss_a, unit_value=Decimal("100.00")
        )
        svc = GlosaSafetyService(requesting_user=self.faturista)
        svc.evaluate_guide(guide, gate="batch_close")
        self.assertFalse(
            GlosaSafetyAlert.objects.filter(guide=guide, check_code="not_in_table").exists()
        )

    def test_no_resolvable_table_advises_not_blocks(self):
        self._enable_glosa()
        # Provider with NO active table at all → must NOT block every line;
        # exactly one table_unresolved advise; close() must NOT 409.
        prov = InsuranceProvider.objects.create(name="NoTable", ans_code="666666")
        enc = Encounter.objects.create(patient=self.patient, professional=self.professional)
        guide = self._make_guide(encounter=enc, provider=prov, tuss=self.tuss_a)
        svc = GlosaSafetyService(requesting_user=self.faturista)
        svc.evaluate_guide(guide, gate="batch_close")
        self.assertFalse(
            GlosaSafetyAlert.objects.filter(guide=guide, check_code="not_in_table").exists()
        )
        advise = GlosaSafetyAlert.objects.filter(guide=guide, check_code="table_unresolved")
        self.assertEqual(advise.count(), 1)
        self.assertEqual(advise.first().severity, "advise")
        self.assertFalse(GlosaSafetyService.has_blocking_glosa_alert(guide))

        batch = TISSBatch.objects.create(provider=prov, status="open")
        batch.guides.add(guide)
        resp = self._auth().post(f"/api/v1/billing/batches/{batch.id}/close/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "closed")

    # ── FIX 3: draft excluded from "already presented" duplicate set ──────────

    def test_abandoned_draft_does_not_flag_duplicate(self):
        self._enable_glosa()
        # An abandoned DRAFT guide with same encounter+TUSS must NOT cause a
        # duplicate block on a real (pending) guide — a draft was never presented.
        self._make_guide(status="draft")  # abandoned draft, same encounter+tuss
        real = self._make_guide(status="pending")
        svc = GlosaSafetyService(requesting_user=self.faturista)
        svc.evaluate_guide(real, gate="batch_close")
        self.assertFalse(
            GlosaSafetyAlert.objects.filter(
                guide=real, check_code="duplicate", severity="block"
            ).exists()
        )

    def test_pending_sibling_does_flag_duplicate(self):
        self._enable_glosa()
        # A PENDING (presented/queued) sibling DOES flag the duplicate.
        self._make_guide(status="pending")  # presented sibling, same encounter+tuss
        real = self._make_guide(status="pending")
        svc = GlosaSafetyService(requesting_user=self.faturista)
        svc.evaluate_guide(real, gate="batch_close")
        self.assertTrue(
            GlosaSafetyAlert.objects.filter(
                guide=real, check_code="duplicate", severity="block"
            ).exists()
        )

    # ── FIX A: paid sibling flags (paid-then-rebilled double-bill); denied/appeal
    #          siblings do NOT (legitimate recurso/correction) ─────────────────

    def test_paid_sibling_does_flag_duplicate(self):
        self._enable_glosa()
        # A PAID procedure (encounter+TUSS X) re-billed on a NEW pending guide is
        # the classic paid-then-rebilled double-bill — the duplicate MUST fire.
        self._make_guide(status="paid")  # already presented + settled, same enc+tuss
        real = self._make_guide(status="pending")
        svc = GlosaSafetyService(requesting_user=self.faturista)
        svc.evaluate_guide(real, gate="batch_close")
        self.assertTrue(
            GlosaSafetyAlert.objects.filter(
                guide=real, check_code="duplicate", severity="block"
            ).exists()
        )

    def test_denied_sibling_does_not_flag_duplicate(self):
        self._enable_glosa()
        # A DENIED (glosado) prior guide for the same encounter+TUSS must NOT
        # flag — a re-presentation is a legitimate recurso/correction; flagging
        # would false-BLOCK the recovery flow.
        self._make_guide(status="denied")  # glosado sibling, same enc+tuss
        real = self._make_guide(status="pending")
        svc = GlosaSafetyService(requesting_user=self.faturista)
        svc.evaluate_guide(real, gate="batch_close")
        self.assertFalse(
            GlosaSafetyAlert.objects.filter(
                guide=real, check_code="duplicate", severity="block"
            ).exists()
        )

    def test_appeal_sibling_does_not_flag_duplicate(self):
        self._enable_glosa()
        # A sibling in active recurso (appeal) must NOT flag — same rationale as
        # denied: a correction/re-presentation during the appeal is legitimate.
        self._make_guide(status="appeal")  # in recurso, same enc+tuss
        real = self._make_guide(status="pending")
        svc = GlosaSafetyService(requesting_user=self.faturista)
        svc.evaluate_guide(real, gate="batch_close")
        self.assertFalse(
            GlosaSafetyAlert.objects.filter(
                guide=real, check_code="duplicate", severity="block"
            ).exists()
        )

    # ── FIX 4: close() locks the batch row + evaluates exactly its guides ─────

    def test_close_locks_batch_and_evaluates_its_guides(self):
        self._enable_glosa()
        from unittest import mock

        from apps.billing import views as billing_views

        enc = Encounter.objects.create(patient=self.patient, professional=self.professional)
        guide = self._make_guide(encounter=enc, tuss=self.tuss_a, unit_value=Decimal("100.00"))
        batch = self._make_batch(guide)

        evaluated: list = []
        orig_eval = GlosaSafetyService.evaluate_guide

        def _spy(self, g, *, gate):
            evaluated.append(g.id)
            return orig_eval(self, g, gate=gate)

        select_for_update_seen = {"called": False}
        orig_sfu = billing_views.TISSBatch.objects.select_for_update

        def _sfu_spy(*a, **kw):
            select_for_update_seen["called"] = True
            return orig_sfu(*a, **kw)

        with mock.patch.object(GlosaSafetyService, "evaluate_guide", _spy):
            with mock.patch.object(billing_views.TISSBatch.objects, "select_for_update", _sfu_spy):
                resp = self._auth().post(f"/api/v1/billing/batches/{batch.id}/close/")
        self.assertEqual(resp.status_code, 200)
        # Batch row lock path was taken and exactly the batch's guides evaluated.
        self.assertTrue(select_for_update_seen["called"])
        self.assertEqual(evaluated, [guide.id])

    # ── FIX B: TOCTOU — blocking-check operates on the EVALUATED id set, and a
    #          membership change between capture and finalize is rejected ──────

    def test_close_blocking_check_uses_evaluated_id_set(self):
        # The blocking decision must be computed via
        # blocking_glosa_alerts_for_guides over the SAME ids that were evaluated
        # — NOT a fresh batch.guides.all() re-query. Assert the method is called
        # and that the id set it receives equals the evaluated id set.
        self._enable_glosa()
        from unittest import mock

        enc = Encounter.objects.create(patient=self.patient, professional=self.professional)
        guide = self._make_guide(encounter=enc, tuss=self.tuss_a, unit_value=Decimal("100.00"))
        batch = self._make_batch(guide)

        evaluated: list = []
        orig_eval = GlosaSafetyService.evaluate_guide

        def _eval_spy(self, g, *, gate):
            evaluated.append(g.id)
            return orig_eval(self, g, gate=gate)

        checked_ids = {}
        orig_block = GlosaSafetyService.blocking_glosa_alerts_for_guides

        def _block_spy(guide_ids):
            checked_ids["ids"] = list(guide_ids)
            return orig_block(guide_ids)

        with mock.patch.object(GlosaSafetyService, "evaluate_guide", _eval_spy):
            with mock.patch.object(
                GlosaSafetyService,
                "blocking_glosa_alerts_for_guides",
                staticmethod(_block_spy),
            ):
                resp = self._auth().post(f"/api/v1/billing/batches/{batch.id}/close/")
        self.assertEqual(resp.status_code, 200)
        # The blocking check ran over exactly the evaluated id set.
        self.assertIn("ids", checked_ids)
        self.assertEqual(set(checked_ids["ids"]), set(evaluated))
        self.assertEqual(set(evaluated), {guide.id})

    def test_close_rejects_membership_change_during_close(self):
        # Simulate a concurrent guides.add() landing AFTER the evaluated set was
        # captured but BEFORE finalize: the membership re-assertion must fire,
        # returning 409 batch_modified_during_close and NOT closing the batch.
        self._enable_glosa()
        from unittest import mock

        enc = Encounter.objects.create(patient=self.patient, professional=self.professional)
        guide = self._make_guide(encounter=enc, tuss=self.tuss_a, unit_value=Decimal("100.00"))
        batch = self._make_batch(guide)

        # A second, never-evaluated guide that a "concurrent" actor adds mid-flow.
        enc2 = Encounter.objects.create(patient=self.patient, professional=self.professional)
        sneaked = self._make_guide(encounter=enc2, tuss=self.tuss_b, unit_value=Decimal("50.00"))

        orig_block = GlosaSafetyService.blocking_glosa_alerts_for_guides

        def _block_then_add(guide_ids):
            # Runs between evaluated-set capture and the membership re-assertion.
            result = orig_block(guide_ids)
            batch.guides.add(sneaked)  # add-after-capture window
            return result

        with mock.patch.object(
            GlosaSafetyService,
            "blocking_glosa_alerts_for_guides",
            staticmethod(_block_then_add),
        ):
            resp = self._auth().post(f"/api/v1/billing/batches/{batch.id}/close/")
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()["code"], "batch_modified_during_close")
        # Batch must NOT be closed.
        batch.refresh_from_db()
        self.assertEqual(batch.status, "open")


class AcknowledgeGlosaAlertTests(TenantTestCase):
    """Ack endpoint: block needs >=10-char reason; advise acks without one."""

    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant, module_key="billing", defaults={"is_enabled": True}
        )
        self.role = Role.objects.create(
            name="faturista", permissions=["billing.read", "billing.write"], is_system=True
        )
        self.faturista = User.objects.create_user(
            email="faturista@test.com",
            full_name="Faturista",
            password="Str0ng!Pass#2024",
            role=self.role,
        )
        prof_user = User.objects.create_user(
            email="medico@test.com",
            full_name="Dr",
            password="Str0ng!Pass#2024",
            role=self.role,
        )
        self.patient = Patient.objects.create(
            full_name="P", cpf="000.000.000-00", birth_date=datetime.date(1985, 1, 1), gender="F"
        )
        self.professional = Professional.objects.create(
            user=prof_user, council_type="CRM", council_number="1", council_state="SP"
        )
        self.encounter = Encounter.objects.create(
            patient=self.patient, professional=self.professional
        )
        self.provider = InsuranceProvider.objects.create(name="Op", ans_code="888888")
        self.guide = TISSGuide.objects.create(
            guide_type="sadt",
            encounter=self.encounter,
            patient=self.patient,
            provider=self.provider,
            insured_card_number="0001",
            competency="2026-03",
            cid10_codes=[{"code": "J00"}],
        )
        resp = self.client.post(
            "/api/v1/auth/login",
            {"email": "faturista@test.com", "password": "Str0ng!Pass#2024"},
            format="json",
        )
        self.token = resp.json().get("access")

    def _auth(self):
        c = APIClient()
        c.defaults["SERVER_NAME"] = self.__class__.domain.domain
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token}")
        return c

    def _alert(self, severity):
        return GlosaSafetyAlert.objects.create(
            guide=self.guide,
            check_code="duplicate" if severity == "block" else "incomplete",
            severity=severity,
            source="engine",
            status="flagged",
            message="m",
        )

    def test_block_alert_requires_reason(self):
        alert = self._alert("block")
        resp = self._auth().post(
            f"/api/v1/billing/glosa-safety-alerts/{alert.id}/acknowledge/",
            {"reason": "curto"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        alert.refresh_from_db()
        self.assertEqual(alert.status, "flagged")

    def test_block_alert_acks_with_long_reason(self):
        alert = self._alert("block")
        resp = self._auth().post(
            f"/api/v1/billing/glosa-safety-alerts/{alert.id}/acknowledge/",
            {"reason": "Justificativa suficientemente longa."},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        alert.refresh_from_db()
        self.assertEqual(alert.status, "acknowledged")
        self.assertEqual(alert.acknowledged_by, self.faturista)

    def test_advise_alert_acks_without_reason(self):
        alert = self._alert("advise")
        resp = self._auth().post(
            f"/api/v1/billing/glosa-safety-alerts/{alert.id}/acknowledge/",
            {},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        alert.refresh_from_db()
        self.assertEqual(alert.status, "acknowledged")


class GlosaClinicalCompatServiceTests(GlosaSafetyTestCase):
    """Orchestrator-level G3b: the service resolves patient age/sex (from the
    guide's Patient) + the guide's CID-10 codes + the TUSS ANS metadata, and the
    engine emits advise-only clinical_incompat. INERT without ANS metadata; never
    blocks the close()."""

    def _populate_tuss(self, tuss, **meta):
        """Stamp ANS clinical-compat metadata onto a public TUSSCode row (this is
        what import_tuss would do from the ANS source — here done directly)."""
        for field_name, value in meta.items():
            setattr(tuss, field_name, value)
        tuss.save(update_fields=list(meta.keys()))

    def test_age_mismatch_advises_in_window_silent(self):
        self._enable_glosa()
        # Patient born 1985 → ~40y ≈ 15000 days. Restrict tuss_a to infants only.
        self._populate_tuss(self.tuss_a, age_min_days=0, age_max_days=365)
        enc = Encounter.objects.create(patient=self.patient, professional=self.professional)
        guide = self._make_guide(encounter=enc, tuss=self.tuss_a, unit_value=Decimal("100.00"))
        svc = GlosaSafetyService(requesting_user=self.faturista)
        svc.evaluate_guide(guide, gate="batch_close")
        alert = GlosaSafetyAlert.objects.filter(guide=guide, check_code="clinical_incompat").first()
        self.assertIsNotNone(alert)
        self.assertEqual(alert.severity, "advise")

        # In-window: widen the window to cover the adult patient → no finding.
        enc2 = Encounter.objects.create(patient=self.patient, professional=self.professional)
        guide2 = self._make_guide(encounter=enc2, tuss=self.tuss_b, unit_value=Decimal("50.00"))
        self._populate_tuss(self.tuss_b, age_min_days=0, age_max_days=40000)
        svc.evaluate_guide(guide2, gate="batch_close")
        self.assertFalse(
            GlosaSafetyAlert.objects.filter(guide=guide2, check_code="clinical_incompat").exists()
        )

    def test_sex_mismatch_advises_both_silent(self):
        self._enable_glosa()
        # Patient is F (setUp). Restrict tuss_a to M → advise.
        self._populate_tuss(self.tuss_a, sex_allowed="M")
        enc = Encounter.objects.create(patient=self.patient, professional=self.professional)
        guide = self._make_guide(encounter=enc, tuss=self.tuss_a, unit_value=Decimal("100.00"))
        svc = GlosaSafetyService(requesting_user=self.faturista)
        svc.evaluate_guide(guide, gate="batch_close")
        self.assertTrue(
            GlosaSafetyAlert.objects.filter(
                guide=guide, check_code="clinical_incompat", severity="advise"
            ).exists()
        )

        # sex_allowed="B" (default for tuss_b) → no finding.
        enc2 = Encounter.objects.create(patient=self.patient, professional=self.professional)
        guide2 = self._make_guide(encounter=enc2, tuss=self.tuss_b, unit_value=Decimal("50.00"))
        svc.evaluate_guide(guide2, gate="batch_close")
        self.assertFalse(
            GlosaSafetyAlert.objects.filter(guide=guide2, check_code="clinical_incompat").exists()
        )

    def test_cid_whitelist_advises_when_guide_cid_not_in_it(self):
        self._enable_glosa()
        # Guide CID is J00 (setUp default). Restrict tuss_a to C50 → advise.
        self._populate_tuss(self.tuss_a, cid10_whitelist=["C50", "C51"])
        enc = Encounter.objects.create(patient=self.patient, professional=self.professional)
        guide = self._make_guide(encounter=enc, tuss=self.tuss_a, unit_value=Decimal("100.00"))
        svc = GlosaSafetyService(requesting_user=self.faturista)
        svc.evaluate_guide(guide, gate="batch_close")
        self.assertTrue(
            GlosaSafetyAlert.objects.filter(
                guide=guide, check_code="clinical_incompat", severity="advise"
            ).exists()
        )

    def test_cid_in_whitelist_silent(self):
        self._enable_glosa()
        # Whitelist includes the guide's CID J00 → no finding.
        self._populate_tuss(self.tuss_a, cid10_whitelist=["J00", "J01"])
        enc = Encounter.objects.create(patient=self.patient, professional=self.professional)
        guide = self._make_guide(
            encounter=enc,
            tuss=self.tuss_a,
            unit_value=Decimal("100.00"),
            cid10_codes=[{"code": "J00"}],
        )
        svc = GlosaSafetyService(requesting_user=self.faturista)
        svc.evaluate_guide(guide, gate="batch_close")
        self.assertFalse(
            GlosaSafetyAlert.objects.filter(guide=guide, check_code="clinical_incompat").exists()
        )

    def test_inert_when_tuss_has_no_ans_metadata(self):
        self._enable_glosa()
        # tuss_a left at defaults (no ANS metadata) → NO clinical_incompat,
        # regardless of the patient's age/sex/CID.
        enc = Encounter.objects.create(patient=self.patient, professional=self.professional)
        guide = self._make_guide(encounter=enc, tuss=self.tuss_a, unit_value=Decimal("100.00"))
        svc = GlosaSafetyService(requesting_user=self.faturista)
        svc.evaluate_guide(guide, gate="batch_close")
        self.assertFalse(
            GlosaSafetyAlert.objects.filter(guide=guide, check_code="clinical_incompat").exists()
        )

    def test_clinical_incompat_alone_does_not_409(self):
        # Regression guard: a guide whose ONLY issue is clinical_incompat (advise)
        # must NOT block the close() — advise never enters the blocking set.
        self._enable_glosa()
        self._populate_tuss(self.tuss_b, sex_allowed="M")  # patient is F
        enc = Encounter.objects.create(patient=self.patient, professional=self.professional)
        guide = self._make_guide(encounter=enc, tuss=self.tuss_b, unit_value=Decimal("50.00"))
        batch = self._make_batch(guide)
        resp = self._auth().post(f"/api/v1/billing/batches/{batch.id}/close/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "closed")
        # The advise alert WAS recorded.
        alert = GlosaSafetyAlert.objects.filter(guide=guide, check_code="clinical_incompat").first()
        self.assertIsNotNone(alert)
        self.assertEqual(alert.severity, "advise")
        self.assertFalse(GlosaSafetyService.has_blocking_glosa_alert(guide))
