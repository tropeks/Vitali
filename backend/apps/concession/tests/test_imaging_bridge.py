"""C5-P2 — Imaging→consumption auto-wire.

``resolve_concession_exam(study)`` maps a DICOM study to ``(ConcessionService,
unit)`` or ``None``. A ``post_save`` receiver on ``imaging.DicomStudy`` (hooked
concession-side) records an idempotent ``ExamConsumption`` ONLY when the tenant
has the ``diagnostic_concession`` module active AND the study resolves — and it
NEVER raises into the study save (insufficient stock must not block the exam).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from apps.concession.imaging_bridge import resolve_concession_exam
from apps.concession.models import (
    ConcessionService,
    ExamConsumption,
    MaterialUnitCost,
    ServiceRecipe,
)
from apps.concession.permissions import CONCESSION_MODULE_KEY
from apps.core.models import FeatureFlag
from apps.emr.models import Patient
from apps.imaging.models import DicomStudy
from apps.test_utils import TenantTestCase

from .factories import make_facility, make_material, make_user, make_warehouse, stock_item_with_qty


class _Fixtures(TenantTestCase):
    def setUp(self):
        self.user = make_user()
        self.unit = make_facility()
        self.wh = make_warehouse()
        self.gel = make_material("Gel condutor")
        MaterialUnitCost.objects.create(material=self.gel, unit_cost=Decimal("1.50"))
        self.stock = stock_item_with_qty(self.gel, self.wh, 100, self.user, lot="G-1")
        # Service mapped to the DICOM modality code "US".
        self.svc = ConcessionService.objects.create(code="US", name="Ultrassom", modality="US")
        ServiceRecipe.objects.create(service=self.svc, material=self.gel, quantity=Decimal("2"))
        self.patient = Patient.objects.create(
            full_name="Paciente A", cpf="12345678909", birth_date=date(1990, 1, 1), gender="F"
        )

    def _enable_module(self):
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key=CONCESSION_MODULE_KEY,
            defaults={"is_enabled": True},
        )

    def _make_study(self, uid="1.2.3", modality="US", with_unit=True):
        return DicomStudy.objects.create(
            patient=self.patient,
            study_instance_uid=uid,
            modality=modality,
            unit=self.unit if with_unit else None,
            study_date=datetime(2026, 7, 21, tzinfo=UTC),
        )


class ResolverTests(_Fixtures):
    def test_resolves_service_and_unit_by_modality(self):
        resolved = resolve_concession_exam(self._make_study())
        self.assertIsNotNone(resolved)
        service, unit = resolved
        self.assertEqual(service, self.svc)
        self.assertEqual(unit, self.unit)

    def test_no_unit_returns_none(self):
        self.assertIsNone(resolve_concession_exam(self._make_study(with_unit=False)))

    def test_unmapped_modality_returns_none(self):
        self.assertIsNone(resolve_concession_exam(self._make_study(modality="CT")))


class SignalTests(_Fixtures):
    def test_active_module_records_consumption(self):
        self._enable_module()
        study = self._make_study(uid="UID-1")
        rows = ExamConsumption.objects.filter(dicom_study=study)
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.first().cost_snapshot, Decimal("3.00"))  # 2 × 1.50
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, Decimal("98.000"))  # 100 − 2

    def test_idempotent_on_resave(self):
        self._enable_module()
        study = self._make_study(uid="UID-2")
        study.description = "updated"
        study.save()
        self.assertEqual(ExamConsumption.objects.filter(dicom_study=study).count(), 1)
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, Decimal("98.000"))  # deducted once only

    def test_module_off_records_nothing(self):
        study = self._make_study(uid="UID-3")  # no FeatureFlag enabled
        self.assertEqual(ExamConsumption.objects.filter(dicom_study=study).count(), 0)

    def test_no_unit_records_nothing(self):
        self._enable_module()
        study = self._make_study(uid="UID-4", with_unit=False)
        self.assertEqual(ExamConsumption.objects.filter(dicom_study=study).count(), 0)

    def test_unmapped_modality_records_nothing(self):
        self._enable_module()
        study = self._make_study(uid="UID-5", modality="MR")
        self.assertEqual(ExamConsumption.objects.filter(dicom_study=study).count(), 0)

    def test_insufficient_stock_does_not_block_study_save(self):
        self._enable_module()
        scarce = make_material("Contraste raro")
        MaterialUnitCost.objects.create(material=scarce, unit_cost=Decimal("5.00"))
        svc2 = ConcessionService.objects.create(code="CT", name="Tomografia", modality="CT")
        ServiceRecipe.objects.create(service=svc2, material=scarce, quantity=Decimal("5"))
        stock_item_with_qty(scarce, self.wh, 1, self.user, lot="C-1")  # only 1 in stock
        study = self._make_study(uid="UID-6", modality="CT")
        # The study saved fine despite the consumption failure, and nothing recorded.
        self.assertTrue(DicomStudy.objects.filter(pk=study.pk).exists())
        self.assertEqual(ExamConsumption.objects.filter(dicom_study=study).count(), 0)
