"""
S-043: seed_demo_data management command.

Populates a tenant schema with realistic Brazilian healthcare demo data.
Idempotent: checks for [DEMO] sentinel prefix — safe to run on real tenants.

Usage:
    python manage.py seed_demo_data --tenant=<schema_name>
    python manage.py seed_demo_data --tenant=demo --force   # re-seeds even if present
"""

import random
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django_tenants.utils import schema_context


class Command(BaseCommand):
    help = "Seed a tenant schema with realistic demo data for investor demos and onboarding."

    def add_arguments(self, parser):
        parser.add_argument(
            "--tenant",
            required=True,
            help="Schema name of the tenant to seed (e.g. demo, clinica-aurora)",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-seed even if demo data already present (replaces existing [DEMO] records)",
        )

    def handle(self, *args, **options):
        schema = options["tenant"]
        force = options["force"]

        from apps.core.models import Tenant

        try:
            tenant = Tenant.objects.get(schema_name=schema)
        except Tenant.DoesNotExist as exc:
            raise CommandError(f"Tenant with schema_name='{schema}' not found.") from exc

        with schema_context(schema):
            self._seed(tenant, schema, force)

    def _seed(self, tenant, schema, force):
        from apps.emr.models import Patient

        # Idempotency sentinel — never corrupt real data
        if Patient.objects.filter(full_name__startswith="[DEMO]").exists():
            if not force:
                self.stdout.write(
                    self.style.WARNING(
                        f"Demo data already present in '{schema}'. Use --force to re-seed."
                    )
                )
                return
            self.stdout.write("--force specified: removing existing [DEMO] records...")
            Patient.objects.filter(full_name__startswith="[DEMO]").delete()

        self.stdout.write(f"Seeding demo data into tenant '{schema}'...")

        try:
            from faker import Faker

            fake = Faker("pt_BR")
        except ImportError as exc:
            raise CommandError(
                "Faker is required for seed_demo_data. Install it: pip install faker"
            ) from exc

        patients = self._create_patients(fake, 10)
        professionals = self._get_or_create_professional()
        appointments = self._create_appointments(fake, patients, professionals, 20)
        encounters = self._create_encounters(fake, patients, professionals, appointments[:8])
        self._create_guides(fake, encounters[:5], patients)
        pix_charges = self._create_pix_charges(appointments[:6])
        self._create_stock(fake, 50)
        self._create_purchase_orders(fake, 3)

        self.stdout.write(
            self.style.SUCCESS(
                f"Demo data seeded: {len(patients)} patients, {len(appointments)} appointments, "
                f"{len(encounters)} encounters, {len(pix_charges)} PIX charges."
            )
        )

    def _create_patients(self, fake, count):
        from apps.emr.models import Allergy, Patient

        patients = []
        for _i in range(count):
            p = Patient.objects.create(
                full_name=f"[DEMO] {fake.name()}",
                date_of_birth=fake.date_of_birth(minimum_age=18, maximum_age=80),
                sex=random.choice(["M", "F"]),
                phone=fake.phone_number()[:20],
                email=fake.email(),
            )
            patients.append(p)

        # DX-02: Seed one patient with a known Penicillin allergy so S-063 allergy
        # cross-check tests are non-vacuous (allergy table is empty without this).
        if patients:
            try:
                Allergy.objects.get_or_create(
                    patient=patients[0],
                    substance="Penicilina",
                    defaults={
                        "reaction": "Rash cutâneo e anafilaxia",
                        "severity": "severe",
                    },
                )
            except Exception:
                pass  # Allergy model may not exist in older migrations

        return patients

    def _get_or_create_professional(self):
        from apps.emr.models import Professional

        try:
            return list(Professional.objects.select_related("user").all()[:3])
        except Exception:
            return []

    def _create_appointments(self, fake, patients, professionals, count):
        from apps.emr.models import Appointment

        appointments = []
        if not professionals:
            return appointments
        now = timezone.now()
        for _i in range(count):
            start = now + timedelta(days=random.randint(-30, 30), hours=random.randint(8, 16))
            try:
                appt = Appointment.objects.create(
                    patient=random.choice(patients),
                    professional=random.choice(professionals),
                    start_time=start,
                    end_time=start + timedelta(minutes=30),
                    appointment_type=random.choice(["first_visit", "return"]),
                    status="scheduled",
                    source="web",
                )
                appointments.append(appt)
            except Exception:
                pass
        return appointments

    def _create_encounters(self, fake, patients, professionals, appointments):
        from apps.emr.models import ClinicalNote, Encounter

        encounters = []
        if not professionals:
            return encounters
        for _i, appt in enumerate(appointments[:8]):
            try:
                enc = Encounter.objects.create(
                    patient=appt.patient,
                    professional=appt.professional,
                    appointment=appt,
                    encounter_type="outpatient",
                    chief_complaint=f"[DEMO] {fake.sentence(nb_words=6)}",
                    status="completed",
                )
                ClinicalNote.objects.create(
                    encounter=enc,
                    note_type="evolution",
                    content={
                        "subjective": f"[DEMO] {fake.paragraph(nb_sentences=3)}",
                        "objective": f"[DEMO] PA: {random.randint(110, 140)}/{random.randint(70, 90)} mmHg. FC: {random.randint(60, 100)} bpm.",
                        "assessment": f"[DEMO] {fake.sentence(nb_words=8)}",
                        "plan": f"[DEMO] {fake.sentence(nb_words=10)}",
                    },
                    created_by=appt.professional.user,
                )
                encounters.append(enc)
            except Exception:
                pass
        return encounters

    def _create_guides(self, fake, encounters, patients):
        from apps.billing.models import InsuranceProvider, TISSGuide, TISSGuideItem
        from apps.core.models import TUSSCode

        try:
            provider = InsuranceProvider.objects.first()
            tuss_codes = list(TUSSCode.objects.filter(active=True)[:10])
            if not provider or not tuss_codes or not encounters:
                return
            for i, enc in enumerate(encounters):
                guide = TISSGuide.objects.create(
                    patient=enc.patient,
                    professional=enc.professional,
                    encounter=enc,
                    insurance_provider=provider,
                    guide_type="consultation",
                    status="paid" if i < 3 else "denied",
                    competency=timezone.now().date().replace(day=1).strftime("%Y-%m"),
                )
                tuss = random.choice(tuss_codes)
                TISSGuideItem.objects.create(
                    guide=guide,
                    tuss_code=tuss,
                    description=tuss.description[:200],
                    quantity=1,
                    unit_value=Decimal("150.00"),
                    total_value=Decimal("150.00"),
                )
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"Skipped guide creation: {e}"))

    def _create_pix_charges(self, appointments):
        """Seed PIXCharge records: 2 paid, 2 pending, 1 expired, 1 cancelled."""
        from apps.billing.models import PIXCharge

        now = timezone.now()
        charges = []
        statuses = [
            PIXCharge.Status.PAID,
            PIXCharge.Status.PAID,
            PIXCharge.Status.PENDING,
            PIXCharge.Status.PENDING,
            PIXCharge.Status.EXPIRED,
            PIXCharge.Status.CANCELLED,
        ]
        for i, appt in enumerate(appointments):
            if i >= len(statuses):
                break
            status = statuses[i]
            try:
                charge, created = PIXCharge.objects.get_or_create(
                    appointment=appt,
                    defaults={
                        "asaas_charge_id": f"pay_demo_{i:04d}",
                        "asaas_customer_id": f"cus_demo_{i:04d}",
                        "amount": Decimal("150.00"),
                        "status": status,
                        "pix_copy_paste": f"00020126580014br.gov.bcb.pix0136DEMO{i:04d}5204000053039865802BR5913DEMO VITALI6009SAO PAULO62070503***6304DEMO",
                        "pix_qr_code_base64": "",
                        "expires_at": now + timedelta(minutes=30)
                        if status == PIXCharge.Status.PENDING
                        else now - timedelta(hours=1),
                        "paid_at": now - timedelta(hours=random.randint(1, 48))
                        if status == PIXCharge.Status.PAID
                        else None,
                    },
                )
                if created:
                    charges.append(charge)
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"Skipped PIXCharge: {e}"))
        return charges

    def _create_stock(self, fake, count):
        from apps.pharmacy.models import Drug, StockItem

        drugs = list(Drug.objects.filter(is_active=True)[:count])
        for drug in drugs:
            lot = f"[DEMO]-{fake.bothify('??###')}"
            StockItem.objects.get_or_create(
                drug=drug,
                lot_number=lot,
                expiry_date=fake.future_date(end_date="+2y"),
                defaults={"quantity": Decimal(str(random.randint(10, 200)))},
            )

    def _create_purchase_orders(self, fake, count):
        from apps.pharmacy.models import Drug, PurchaseOrder, PurchaseOrderItem, Supplier

        drugs = list(Drug.objects.filter(is_active=True)[:5])
        if not drugs:
            return
        for _ in range(count):
            try:
                supplier, _ = Supplier.objects.get_or_create(
                    name=f"[DEMO] Distribuidora {fake.company()}",
                    defaults={"cnpj": fake.cnpj(), "is_active": True},
                )
                po = PurchaseOrder.objects.create(
                    supplier=supplier,
                    status=PurchaseOrder.Status.RECEIVED,
                    expected_date=fake.past_date(start_date="-30d"),
                    notes="[DEMO] Pedido de reposição de estoque.",
                )
                for drug in random.sample(drugs, min(3, len(drugs))):
                    PurchaseOrderItem.objects.create(
                        po=po,
                        drug=drug,
                        quantity_ordered=Decimal(str(random.randint(20, 100))),
                        quantity_received=Decimal(str(random.randint(20, 100))),
                        unit_price=Decimal(str(round(random.uniform(5.0, 80.0), 2))),
                    )
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"Skipped PO creation: {e}"))
