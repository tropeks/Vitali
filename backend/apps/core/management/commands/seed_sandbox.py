"""Sandbox seed for wedge telemetry dogfooding (S31-05).

Creates a "sandbox" tenant from scratch, seeds mock data for all 7 wedges,
enables every FeatureFlag, and calls WedgeTelemetryView internally so the
output is printed without needing a running server.

Usage:
    python manage.py seed_sandbox            # create + seed (idempotent)
    python manage.py seed_sandbox --reset    # drop & re-seed from zero
    python manage.py seed_sandbox --test-only  # skip seed, just call endpoint
"""

import json
import random
from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone
from django_tenants.utils import schema_context

SCHEMA = "sandbox"
DOMAIN = "sandbox.localhost"
USER_EMAIL = "sandbox@vitali.dev"
USER_PASS = "SandboxPass123!"

WAVE_1_FLAGS = ["no_show_prediction", "stockout_safety", "deterioration_safety"]
WAVE_2_FLAGS = ["dose_safety", "allergy_safety", "glosa_safety", "controlled_safety"]
ALL_FLAGS = WAVE_1_FLAGS + WAVE_2_FLAGS


class Command(BaseCommand):
    help = "Seed sandbox tenant with mock data for all 7 wedges and call telemetry endpoint."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Drop existing sandbox schema and re-create from zero.",
        )
        parser.add_argument(
            "--test-only",
            action="store_true",
            help="Skip seeding; only call the telemetry endpoint.",
        )

    def handle(self, *args, **options):
        reset = options["reset"]
        test_only = options["test_only"]

        tenant = self._ensure_tenant(reset=reset)

        if not test_only:
            with schema_context(SCHEMA):
                user = self._ensure_user()
                self._enable_flags(tenant)
                self._seed_wave1(user)
                self._seed_wave2(user)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("═" * 60))
        self.stdout.write(self.style.SUCCESS("  GET /api/v1/wedge-telemetry/?days=30"))
        self.stdout.write(self.style.SUCCESS("═" * 60))

        with schema_context(SCHEMA):
            self._call_endpoint()

    # ── tenant bootstrap ──────────────────────────────────────────────────────

    def _ensure_tenant(self, *, reset):
        from apps.core.models import Domain, Tenant

        existing = Tenant.objects.filter(schema_name=SCHEMA).first()
        if existing and reset:
            self.stdout.write(f"--reset: dropping existing schema '{SCHEMA}'...")
            existing.delete()
            existing = None

        if not existing:
            self.stdout.write(f"Creating tenant '{SCHEMA}'...")
            tenant = Tenant.objects.create(
                name="Sandbox Demo",
                slug=SCHEMA,
                schema_name=SCHEMA,
            )
            Domain.objects.create(tenant=tenant, domain=DOMAIN, is_primary=True)
            self.stdout.write(self.style.SUCCESS(f"  Tenant created: {SCHEMA} / {DOMAIN}"))
        else:
            tenant = existing
            self.stdout.write(f"Tenant '{SCHEMA}' already exists — skipping create.")

        return tenant

    # ── user + roles ──────────────────────────────────────────────────────────

    def _ensure_user(self):
        from apps.core.models import Role, User
        from apps.core.permissions import DEFAULT_ROLES
        from apps.emr.models import Professional

        role, _ = Role.objects.get_or_create(
            name="medico_sandbox",
            defaults={"permissions": DEFAULT_ROLES.get("medico", {})},
        )
        user, created = User.objects.get_or_create(
            email=USER_EMAIL,
            defaults={"role": role, "is_active": True},
        )
        if created:
            user.set_password(USER_PASS)
            user.save()
            self.stdout.write(f"  User created: {USER_EMAIL} / {USER_PASS}")

        Professional.objects.get_or_create(
            user=user,
            defaults={
                "council_type": "CRM",
                "council_number": "12345",
                "council_state": "SP",
            },
        )
        return user

    # ── feature flags ─────────────────────────────────────────────────────────

    def _enable_flags(self, tenant):
        from apps.core.models import FeatureFlag

        for key in ALL_FLAGS:
            FeatureFlag.objects.update_or_create(
                tenant=tenant, module_key=key, defaults={"is_enabled": True}
            )
        self.stdout.write(f"  Feature flags enabled: {', '.join(ALL_FLAGS)}")

    # ── shared fixture helpers ────────────────────────────────────────────────

    def _get_prof(self, user):
        from apps.emr.models import Professional

        return Professional.objects.get(user=user)

    def _make_patient(self, i):
        from apps.emr.models import Patient

        return Patient.objects.create(
            full_name=f"[SANDBOX] Paciente {i}",
            birth_date=date(1970 + i, 1, 1),
            gender="M" if i % 2 == 0 else "F",
            cpf=f"111{i:08d}",
        )

    def _make_drug(self, name, *, lead_time_days=None):
        from apps.pharmacy.models import Drug

        drug, _ = Drug.objects.get_or_create(
            name=f"[SANDBOX] {name}",
            defaults={"lead_time_days": lead_time_days, "unit_of_measure": "un"},
        )
        return drug

    def _make_encounter(self, patient, prof):
        from apps.emr.models import Encounter

        return Encounter.objects.create(patient=patient, professional=prof)

    def _make_prescription(self, patient, prof):
        from apps.emr.models import Prescription

        enc = self._make_encounter(patient, prof)
        return Prescription.objects.create(encounter=enc, patient=patient, prescriber=prof)

    def _make_prescription_item(self, rx, drug):
        from apps.emr.models import PrescriptionItem

        return PrescriptionItem.objects.create(
            prescription=rx, drug=drug, quantity=Decimal("1"), unit_of_measure="un"
        )

    def _make_dispensation(self, rx, item, patient, user):
        from apps.pharmacy.models import Dispensation

        return Dispensation.objects.create(
            prescription=rx, prescription_item=item, patient=patient, dispensed_by=user
        )

    # ── Wave 1 seed ───────────────────────────────────────────────────────────

    def _seed_wave1(self, user):
        self.stdout.write("\nSeeding Wave 1 wedges...")
        self._seed_no_show(user)
        self._seed_stockout()
        self._seed_deterioration(user)

    def _seed_no_show(self, user):
        from apps.emr.models import Appointment, NoShowRisk

        prof = self._get_prof(user)
        # Fixed anchor so re-runs don't generate overlapping slots on the same professional.
        # Slots are 1 h apart (appointment duration 30 min) → no overlaps ever.
        import datetime as _dt

        anchor = _dt.datetime(2027, 1, 10, 8, 0, 0, tzinfo=_dt.UTC)
        specs = [
            ("0.80", "high", "open", "pending"),
            ("0.75", "high", "acknowledged", "intercepted"),
            ("0.62", "high", "open", "pending"),
            ("0.45", "medium", "open", "pending"),
            ("0.30", "low", "acknowledged", "false_positive"),
        ]
        for i, (score, band, status, outcome) in enumerate(specs):
            patient = self._make_patient(10 + i)
            start = anchor + timedelta(hours=i)
            appt, _ = Appointment.objects.get_or_create(
                professional=prof,
                start_time=start,
                defaults={
                    "patient": patient,
                    "end_time": start + timedelta(minutes=30),
                    "status": "scheduled",
                },
            )
            NoShowRisk.objects.get_or_create(
                appointment=appt,
                defaults={
                    "score": score,
                    "band": band,
                    "status": status,
                    "outcome": outcome,
                    "suggested_action": "confirm_active",
                    "engine_version": "noshow-n1",
                },
            )
        self.stdout.write(f"  no_show_prediction: {len(specs)} alerts")

    def _seed_stockout(self):
        from apps.pharmacy.models import StockAlert

        now = timezone.now()
        specs = [
            ("Dipirona 500mg", 7, "open", "pending"),
            ("Amoxicilina 500mg", 14, "acknowledged", "intercepted"),
            ("Ibuprofeno 600mg", 10, "open", "pending"),
        ]
        for name, days, status, outcome in specs:
            drug = self._make_drug(name, lead_time_days=days)
            alert, _ = StockAlert.objects.get_or_create(
                drug=drug,
                kind="stockout_risk",
                defaults={
                    "severity": "advise",
                    "status": status,
                    "predicted_date": now.date() + timedelta(days=random.randint(3, 12)),
                    "message": f"Ruptura prevista em {days} dias.",
                    "outcome": outcome,
                },
            )
        self.stdout.write(f"  stockout_safety: {len(specs)} alerts")

    def _seed_deterioration(self, user):
        from apps.emr.models import DeteriorationAlert, VitalSigns

        prof = self._get_prof(user)
        specs = [
            # (rr, spo2, sbp, hr, temp, score, band, severity, status)
            (28, 90, 95, 118, Decimal("39.1"), 8, "high", "escalation", "open"),
            (22, 94, 100, 105, Decimal("38.5"), 6, "medium", "advise", "acknowledged"),
        ]
        for i, (rr, spo2, sbp, hr, temp, score, band, sev, status) in enumerate(specs):
            patient = self._make_patient(20 + i)
            enc = self._make_encounter(patient, prof)
            vs = VitalSigns.objects.create(
                encounter=enc,
                respiratory_rate=rr,
                oxygen_saturation=spo2,
                on_supplemental_oxygen=True,
                blood_pressure_systolic=sbp,
                heart_rate=hr,
                temperature_celsius=temp,
                consciousness="A",
            )
            DeteriorationAlert.objects.get_or_create(
                encounter=enc,
                defaults={
                    "vital_signs": vs,
                    "score": score,
                    "band": band,
                    "breakdown": {"respiratory_rate": 3},
                    "any_param_three": True,
                    "spo2_scale": 1,
                    "severity": sev,
                    "status": status,
                    "engine_version": "news2-rcp-2017-v1",
                    "message": f"NEWS2 {score}",
                },
            )
        self.stdout.write(f"  deterioration_safety: {len(specs)} alerts")

    # ── Wave 2 seed ───────────────────────────────────────────────────────────

    def _seed_wave2(self, user):
        self.stdout.write("\nSeeding Wave 2 wedges...")
        self._seed_dose_safety(user)
        self._seed_allergy_safety(user)
        self._seed_glosa_safety(user)
        self._seed_controlled_safety(user)

    def _seed_dose_safety(self, user):
        from apps.emr.models import AISafetyAlert

        prof = self._get_prof(user)
        specs = [
            ("flagged", "Dose acima do intervalo terapêutico."),
            ("flagged", "Dose pediátrica incompatível com peso estimado."),
            ("acknowledged", "Dose alta: prescritor confirmou intencional."),
        ]
        for i, (status, msg) in enumerate(specs):
            patient = self._make_patient(30 + i)
            drug = self._make_drug(f"Drug Dose {i + 1}")
            rx = self._make_prescription(patient, prof)
            item = self._make_prescription_item(rx, drug)
            AISafetyAlert.objects.get_or_create(
                prescription_item=item,
                alert_type="dose",
                source="engine",
                defaults={
                    "severity": "caution",
                    "message": msg,
                    "status": status,
                },
            )
        self.stdout.write(f"  dose_safety: {len(specs)} alerts")

    def _seed_allergy_safety(self, user):
        from apps.emr.models import AISafetyAlert, Allergy

        prof = self._get_prof(user)
        specs = [
            ("flagged", "caution", "Alergia cruzada: penicilina / amoxicilina."),
            (
                "flagged",
                "contraindication",
                "NSAID contraindicado: alergia grave a AAS registrada.",
            ),
        ]
        for i, (status, severity, msg) in enumerate(specs):
            patient = self._make_patient(40 + i)
            Allergy.objects.get_or_create(
                patient=patient,
                substance="Penicilina",
                defaults={"severity": "severe", "reaction": "Anafilaxia"},
            )
            drug = self._make_drug(f"Drug Allergy {i + 1}")
            rx = self._make_prescription(patient, prof)
            item = self._make_prescription_item(rx, drug)
            AISafetyAlert.objects.get_or_create(
                prescription_item=item,
                alert_type="allergy",
                source="engine",
                defaults={
                    "severity": severity,
                    "message": msg,
                    "status": status,
                },
            )
        self.stdout.write(f"  allergy_safety: {len(specs)} alerts")

    def _seed_glosa_safety(self, user):
        from apps.billing.models import GlosaSafetyAlert, InsuranceProvider, TISSGuide

        prof = self._get_prof(user)
        provider, _ = InsuranceProvider.objects.get_or_create(
            ans_code="999001",
            defaults={"name": "[SANDBOX] Plano Demo"},
        )
        specs = [
            ("incomplete", "advise", "flagged", "Dados incompletos: CID-10 ausente."),
            ("stale_price", "block", "flagged", "Valor diverge da tabela vigente."),
            ("duplicate", "block", "acknowledged", "Procedimento duplicado na guia."),
        ]
        for i, (code, severity, status, msg) in enumerate(specs):
            patient = self._make_patient(50 + i)
            enc = self._make_encounter(patient, prof)
            guide, _ = TISSGuide.objects.get_or_create(
                encounter=enc,
                defaults={
                    "guide_type": "sadt",
                    "patient": patient,
                    "provider": provider,
                    "insured_card_number": f"999{i:017d}",
                    "competency": "2026-06",
                    "status": "pending",
                },
            )
            GlosaSafetyAlert.objects.get_or_create(
                guide=guide,
                check_code=code,
                source="engine",
                guide_item=None,
                defaults={
                    "severity": severity,
                    "message": msg,
                    "status": status,
                },
            )
        self.stdout.write(f"  glosa_safety: {len(specs)} alerts")

    def _seed_controlled_safety(self, user):
        from apps.pharmacy.models import ControlledAlert

        prof = self._get_prof(user)
        specs = [
            ("refill_too_soon", "open", "pending", "Refill 8 dias antes do intervalo mínimo."),
            ("multiple_prescribers", "open", "pending", "3 prescritores distintos em 30 dias."),
            (
                "quantity_escalation",
                "acknowledged",
                "true_positive",
                "Escalada 40%: diversion confirmada.",
            ),
        ]
        for i, (signal, status, outcome, msg) in enumerate(specs):
            patient = self._make_patient(60 + i)
            drug = self._make_drug(f"Controlado {i + 1}")
            rx = self._make_prescription(patient, prof)
            item = self._make_prescription_item(rx, drug)
            disp = self._make_dispensation(rx, item, patient, user)
            ControlledAlert.objects.get_or_create(
                dispensation=disp,
                signal_kind=signal,
                defaults={
                    "patient": patient,
                    "drug": drug,
                    "detail": {"msg": msg},
                    "status": status,
                    "outcome": outcome,
                    "engine_version": "controlled-c1",
                },
            )
        self.stdout.write(f"  controlled_safety: {len(specs)} alerts")

    # ── telemetry endpoint call ───────────────────────────────────────────────

    def _call_endpoint(self):
        from rest_framework.test import APIRequestFactory, force_authenticate

        from apps.core.models import User
        from apps.core.views_telemetry import WedgeTelemetryView

        user = User.objects.filter(email=USER_EMAIL).first()
        if not user:
            self.stdout.write(
                self.style.ERROR("Sandbox user not found — run without --test-only first.")
            )
            return

        factory = APIRequestFactory()
        request = factory.get("/api/v1/wedge-telemetry/", {"days": "30"})
        force_authenticate(request, user=user)

        view = WedgeTelemetryView.as_view()
        response = view(request)
        response.accepted_renderer = None  # bypass renderer

        data = response.data
        self._print_telemetry(data)

    def _print_telemetry(self, data):
        days = data.get("days", "?")
        wedges = data.get("wedges", [])

        self.stdout.write(f"\n  Janela: {days} dias | {len(wedges)} wedges\n")
        for w in wedges:
            enabled = "✓ ATIVO" if w["enabled"] else "○ inativo"
            rate = w["override_rate"]
            rate_str = f"{rate * 100:.0f}%" if rate is not None else "—"
            oc = w["flywheel"].get("outcome_counts")
            oc_str = json.dumps(oc, ensure_ascii=False) if oc else "null"
            graded = w["flywheel"].get("graded_count", 0)
            self.stdout.write(
                f"  {w['key']:<25} {enabled:<12} "
                f"alertas={w['alert_count']} ack={w['acknowledged_count']} "
                f"override={rate_str}  outcomes={oc_str}  graded={graded}"
            )

        self.stdout.write("")
        self.stdout.write("  JSON completo:")
        self.stdout.write(json.dumps(dict(data), indent=4, ensure_ascii=False, default=str))
