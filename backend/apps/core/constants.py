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
    }
)
