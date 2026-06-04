"""
Shared constants for the core app.
Import from here — don't redefine inline in views, serializers, or elsewhere.
"""

# ─── Dose-safety: canonical units ─────────────────────────────────────────────
# ONE source of truth for absolute MASS dose units, shared by both apps.emr and
# apps.pharmacy (both already import from core, and core is public/shared-schema
# so this creates no bad cross-app dependency). Using a single choices set gives
# DB-level coherence: "milligrams" vs "mg" can no longer silently diverge across
# PrescriptionItem.dose_unit, MedicationFormulary.strength_unit, and
# DoseRule.dose_unit.
#
# MASS UNITS ONLY — NEVER "mg/kg". A per-kg dose is expressed by DoseRule.basis +
# the per-kg fields; the unit of a per-kg field is implicitly `dose_unit` per kg.
DOSE_UNIT_CHOICES: list[tuple[str, str]] = [
    ("mg", "mg"),
    ("mcg", "mcg"),
    ("mEq", "mEq"),
    ("unit", "unit"),
    ("g", "g"),
]

# Volume units (mL only for now) for injectables expressed per-volume.
VOLUME_UNIT_CHOICES: list[tuple[str, str]] = [
    ("mL", "mL"),
]

ALLOWED_MODULE_KEYS: frozenset = frozenset(
    {
        "emr",
        "billing",
        "pharmacy",
        "ai_tuss",
        "whatsapp",
        "analytics",
        "rh",
        "signatures",
        "fhir",
        "imaging",
        "telemedicine",
        "patient_portal",
        "pharmacy_ai",
        "smart_scheduling",
        "triage",
        "mobile",
        # Dose-safety wedge (PR B): per-tenant toggle for the deterministic
        # dose-check engine + soft-stop enforcement. Default OFF — a tenant must
        # explicitly enable it (and have a pharmacist-supplied formulary) before
        # the prescription/pharmacy gates start blocking on dose verdicts.
        "dose_safety",
        # Glosa-safety wedge (PR G1): per-tenant toggle for the deterministic
        # glosa (insurance-denial) interceptor + per-guia soft-stop on batch
        # close. Default OFF — a tenant must explicitly enable it before the
        # batch-close gate starts blocking on duplicate/not-tabled findings.
        "glosa_safety",
        # Stockout-prediction wedge (PR S2): per-tenant toggle for the
        # deterministic stockout/expiry interceptor (advise-only). Default OFF —
        # a tenant must explicitly enable it before the engine evaluates products
        # and persists StockAlert rows. Proactive only (no DispenseView gate).
        "stockout_safety",
        # Clinical-deterioration wedge (PR D2): per-tenant toggle for the NEWS2
        # early-warning interceptor (advise/escalation-only — NEVER blocks vitals
        # recording). Default OFF — a tenant must explicitly enable it (clinical
        # governance + escalation protocol) before VitalSigns saves raise a
        # DeteriorationAlert. NEWS2 itself is a public RCP standard, not invented.
        "deterioration_safety",
        # Allergy & drug-interaction wedge (PR A1): per-tenant toggle for the
        # deterministic allergy-conflict interceptor (soft-stop at prescription
        # sign / dispense). Default OFF — a tenant must explicitly enable it before
        # the engine writes engine-sourced allergy alerts and the gate blocks on
        # them. Direct allergy match runs on existing data; cross-reactivity /
        # interaction tables (A2/A3) are human-curated, inert until populated.
        "allergy_safety",
        # No-show prediction wedge (PR N1): per-tenant toggle for the deterministic
        # no-show risk scorer (advise/operational — NEVER blocks booking or
        # check-in). Default OFF. The risk is DERIVED from each patient's own
        # appointment history (no curated data); a patient with < 5 terminal
        # appointments stays inert. v1 only surfaces a suggested action.
        "no_show_prediction",
    }
)
