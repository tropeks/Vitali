"""
Dose-safety wedge PR A — EMR schema tests.

PURE SCHEMA. No dose engine, no enforcement, no clinical numbers.

Covered:
  - PrescriptionItem new structured dose fields are all nullable/blank:
    an existing-style item with NO dose fields still saves (no regression),
    and the new fields can be populated.
  - AISafetyAlert source idempotency fix: an "llm" dose alert and an "engine"
    dose alert for the SAME prescription_item coexist (unique_together now
    includes source); re-saving the engine row does NOT touch the llm row's
    override/acknowledgement.
  - Migration round-trip (apply + reverse) for the AISafetyAlert source change.
"""

from decimal import Decimal

from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor

from apps.core.permissions import DEFAULT_ROLES
from apps.emr.models import (
    AISafetyAlert,
    Encounter,
    Patient,
    Prescription,
    PrescriptionItem,
    Professional,
)
from apps.pharmacy.models import Drug
from apps.test_utils import TenantTestCase


def _make_prescription():
    from apps.core.models import Role, User

    role_md = Role.objects.create(name="medico_dose", permissions=DEFAULT_ROLES["medico"])
    user = User.objects.create_user(email="md_dose@t.com", password="pw", role=role_md)
    patient = Patient.objects.create(
        full_name="Dose Patient", birth_date="1985-06-15", gender="F", cpf="33333333333"
    )
    prescriber = Professional.objects.create(
        user=user, council_type="CRM", council_number="77", council_state="SP"
    )
    encounter = Encounter.objects.create(patient=patient, professional=prescriber)
    rx = Prescription.objects.create(encounter=encounter, patient=patient, prescriber=prescriber)
    return rx


class TestPrescriptionItemDoseFields(TenantTestCase):
    def setUp(self):
        self.rx = _make_prescription()
        self.drug = Drug.objects.create(name="Dose Drug 10mg", generic_name="dosedrug")

    def test_item_without_dose_fields_still_saves(self):
        """Regression: existing-style item with no structured dose fields persists."""
        item = PrescriptionItem.objects.create(
            prescription=self.rx,
            drug=self.drug,
            quantity=Decimal("21"),
            unit_of_measure="cx",
            dosage_instructions="1 comp 8/8h",
        )
        item.refresh_from_db()
        self.assertIsNone(item.dose_amount)
        self.assertEqual(item.dose_unit, "")
        self.assertEqual(item.route, "")
        self.assertIsNone(item.frequency_per_day)

    def test_item_with_dose_fields_persists_decimal(self):
        item = PrescriptionItem.objects.create(
            prescription=self.rx,
            drug=self.drug,
            quantity=Decimal("1"),
            dose_amount=Decimal("10.500"),
            dose_unit="mg",
            route="IV",
            frequency_per_day=3,
        )
        item.refresh_from_db()
        self.assertEqual(item.dose_amount, Decimal("10.500"))
        self.assertIsInstance(item.dose_amount, Decimal)
        self.assertEqual(item.dose_unit, "mg")
        self.assertEqual(item.route, "IV")
        self.assertEqual(item.frequency_per_day, 3)


class TestAISafetyAlertSourceIdempotency(TenantTestCase):
    def setUp(self):
        from apps.core.models import Role, User

        self.rx = _make_prescription()
        self.drug = Drug.objects.create(name="Alert Drug 5mg", generic_name="alertdrug")
        self.item = PrescriptionItem.objects.create(
            prescription=self.rx, drug=self.drug, quantity=Decimal("1")
        )
        role = Role.objects.create(name="ack_role", permissions=DEFAULT_ROLES["medico"])
        self.user = User.objects.create_user(email="ack@t.com", password="pw", role=role)

    def test_llm_and_engine_dose_alerts_coexist(self):
        """The unique_together fix: same item + alert_type, different source = two rows."""
        llm = AISafetyAlert.objects.create(
            prescription_item=self.item,
            alert_type="dose",
            source=AISafetyAlert.Source.LLM,
            severity="caution",
            message="LLM explanation of dose concern.",
        )
        engine = AISafetyAlert.objects.create(
            prescription_item=self.item,
            alert_type="dose",
            source=AISafetyAlert.Source.ENGINE,
            severity="contraindication",
            message="Deterministic engine: OUT_OF_RANGE.",
        )
        self.assertNotEqual(llm.pk, engine.pk)
        self.assertEqual(
            AISafetyAlert.objects.filter(prescription_item=self.item, alert_type="dose").count(),
            2,
        )

    def test_duplicate_same_source_still_blocked(self):
        AISafetyAlert.objects.create(
            prescription_item=self.item,
            alert_type="dose",
            source=AISafetyAlert.Source.LLM,
            severity="caution",
            message="first",
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AISafetyAlert.objects.create(
                    prescription_item=self.item,
                    alert_type="dose",
                    source=AISafetyAlert.Source.LLM,
                    severity="caution",
                    message="dup",
                )

    def test_source_defaults_to_llm(self):
        alert = AISafetyAlert.objects.create(
            prescription_item=self.item,
            alert_type="allergy",
            severity="caution",
            message="no source given",
        )
        self.assertEqual(alert.source, "llm")

    def test_engine_recheck_does_not_clobber_acknowledged_llm_alert(self):
        """
        The landmine: a re-check on the engine row must NOT wipe the LLM row's
        override/acknowledgement. With source in the key, update_or_create on the
        engine row touches only the engine row.
        """
        llm = AISafetyAlert.objects.create(
            prescription_item=self.item,
            alert_type="dose",
            source=AISafetyAlert.Source.LLM,
            severity="contraindication",
            message="LLM dose concern.",
        )
        llm.acknowledge(self.user, reason="Reviewed; intentional high dose for this patient.")
        llm.refresh_from_db()
        self.assertEqual(llm.status, "acknowledged")
        self.assertTrue(llm.override_reason)
        ack_at = llm.acknowledged_at

        # PR B's engine writes/updates its OWN row keyed on source="engine".
        engine, created = AISafetyAlert.objects.update_or_create(
            prescription_item=self.item,
            alert_type="dose",
            source=AISafetyAlert.Source.ENGINE,
            defaults={"severity": "contraindication", "message": "Engine verdict v1"},
        )
        self.assertTrue(created)
        # Re-run the engine check (idempotent retry) — updates engine row only.
        engine2, created2 = AISafetyAlert.objects.update_or_create(
            prescription_item=self.item,
            alert_type="dose",
            source=AISafetyAlert.Source.ENGINE,
            defaults={"severity": "contraindication", "message": "Engine verdict v2"},
        )
        self.assertFalse(created2)
        self.assertEqual(engine.pk, engine2.pk)

        # The LLM acknowledgement survives untouched.
        llm.refresh_from_db()
        self.assertEqual(llm.status, "acknowledged")
        self.assertTrue(llm.override_reason)
        self.assertEqual(llm.acknowledged_at, ack_at)


class TestAISafetyAlertSourceMigrationRoundTrip(TenantTestCase):
    """
    Apply + reverse the AISafetyAlert source migration (emr 0018) to prove it is
    reversible. Runs in the test schema like the rest of the suite.
    """

    migrate_from = ("emr", "0017_encounterprocedure")
    migrate_to = ("emr", "0018_alter_aisafetyalert_unique_together_and_more")

    def test_migration_reverse_and_reapply(self):
        executor = MigrationExecutor(connection)
        # Reverse to before the source change.
        executor.migrate([self.migrate_from])
        executor.loader.build_graph()
        # Re-apply forward.
        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_to])
        executor.loader.build_graph()

        # Schema is back at HEAD: the source field + new unique_together exist.
        field = AISafetyAlert._meta.get_field("source")
        self.assertEqual(field.default, AISafetyAlert.Source.LLM)
        self.assertIn(
            ("prescription_item", "alert_type", "source"),
            AISafetyAlert._meta.unique_together,
        )
