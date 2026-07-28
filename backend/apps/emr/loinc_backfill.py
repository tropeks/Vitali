"""
M2-S3-T2 — LOINC reconciliation helper.

Pure function that maps a LabTest's legacy free-text ``loinc_code`` onto the
governed ``core.LoincCode`` catalog: matched → set the ``loinc`` FK (the legacy
CharField is PRESERVED for audit, never cleared). It takes the model classes as
arguments so the SAME logic runs both from the data migration (historical models
via ``apps.get_model``) and from unit tests (real models). Best-effort: a
LabTest whose ``loinc_code`` matches no governed code is simply left unlinked —
nothing is ever lost.
"""

from __future__ import annotations


def reconcile_lab_test_loinc(LabTestModel, LoincCodeModel) -> tuple[int, int]:
    """Link LabTest rows whose legacy ``loinc_code`` matches a governed code.

    Matched → set ``loinc`` FK (legacy ``loinc_code`` kept as-is). Unmatched →
    left untouched. Returns ``(linked, unmatched)``.
    """
    linked = unmatched = 0
    qs = LabTestModel.objects.filter(loinc__isnull=True).exclude(loinc_code="")
    for test in qs.iterator():
        code = (test.loinc_code or "").strip()
        if not code:
            continue
        match = LoincCodeModel.objects.filter(code=code).first()
        if match is not None:
            test.loinc_id = match.pk
            test.save(update_fields=["loinc"])
            linked += 1
        else:
            unmatched += 1
    return linked, unmatched
