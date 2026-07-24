"""
E1-T5 — CID reconciliation helpers.

Pure functions that map raw/legacy CID-10 strings onto the governed
``core.CID10Code`` catalog: matched → FK/M2M, unmatched → preserved in the
legacy field + flag (NEVER lose data). They take the model classes as arguments
so the SAME logic runs both from the data migration (historical models via
``apps.get_model``) and from unit tests (real models).
"""

from __future__ import annotations


def reconcile_medical_history(MedicalHistoryModel, CID10Model) -> tuple[int, int]:
    """Link MedicalHistory rows whose legacy_cid_text matches a governed code.

    Matched → set ``cid10`` FK, clear ``legacy_cid_text``, ``cid_unmatched=False``.
    Unmatched → keep ``legacy_cid_text``, set ``cid_unmatched=True``.
    Returns ``(linked, unmatched)``.
    """
    linked = unmatched = 0
    qs = MedicalHistoryModel.objects.filter(cid10__isnull=True)
    for mh in qs.iterator():
        code = (mh.legacy_cid_text or "").strip()
        if not code:
            continue
        cid = CID10Model.objects.filter(code=code).first()
        if cid is not None:
            mh.cid10_id = cid.pk
            mh.legacy_cid_text = ""
            mh.cid_unmatched = False
            mh.save(update_fields=["cid10", "legacy_cid_text", "cid_unmatched"])
            linked += 1
        else:
            if not mh.cid_unmatched:
                mh.cid_unmatched = True
                mh.save(update_fields=["cid_unmatched"])
            unmatched += 1
    return linked, unmatched


def reconcile_soap_note(SOAPNoteModel, CID10Model, ThroughModel) -> tuple[int, int]:
    """Move SOAPNote legacy_cid_codes onto the governed M2M.

    Matched codes → a through row (SOAPNoteCID10). Unmatched codes stay in
    ``legacy_cid_codes`` and set ``cid_unmatched=True``. Returns ``(linked,
    unmatched)`` counted across all notes.
    """
    linked = unmatched = 0
    for soap in SOAPNoteModel.objects.iterator():
        raw = list(soap.legacy_cid_codes or [])
        if not raw:
            continue
        remaining: list[str] = []
        for value in raw:
            code = str(value or "").strip()
            if not code:
                continue
            cid = CID10Model.objects.filter(code=code).first()
            if cid is not None:
                ThroughModel.objects.get_or_create(soap_note=soap, cid10_id=cid.pk)
                linked += 1
            elif code not in remaining:
                remaining.append(code)
                unmatched += 1
        soap.legacy_cid_codes = remaining
        soap.cid_unmatched = bool(remaining)
        soap.save(update_fields=["legacy_cid_codes", "cid_unmatched"])
    return linked, unmatched
