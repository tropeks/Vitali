"""
M2-S1-T3 — generic catalog-FK reconciliation helper.
=====================================================
A single pure function that maps a raw/legacy code string on a tenant model onto
a governed SHARED terminology catalog: matched → set the FK, clear the legacy
text; unmatched → keep the legacy text + raise the ``*_unmatched`` flag (NEVER
lose data). It takes the model classes as arguments so the SAME logic runs both
from a data migration (historical models via ``apps.get_model``) and from unit
tests (real models). Mirrors the CID reconcile pattern (``apps.emr.cid_backfill``)
but is field-name-parametrized so ``emr.Professional`` (cbo/cnes) and
``organization.Facility`` (cnes) all reuse it.
"""

from __future__ import annotations


def reconcile_catalog_fk(
    Model,
    CatalogModel,
    *,
    fk_field: str,
    legacy_field: str,
    unmatched_field: str,
    lookup_field: str = "code",
) -> tuple[int, int]:
    """Link rows whose ``legacy_field`` matches a governed catalog code.

    Matched → set ``<fk_field>_id``, clear ``legacy_field``, ``unmatched_field=False``.
    Unmatched → keep ``legacy_field``, set ``unmatched_field=True``.
    Only rows whose FK is still empty are considered. Returns ``(linked, unmatched)``.
    """
    linked = unmatched = 0
    for obj in Model.objects.filter(**{f"{fk_field}__isnull": True}).iterator():
        code = (getattr(obj, legacy_field) or "").strip()
        if not code:
            continue
        match = CatalogModel.objects.filter(**{lookup_field: code}).first()
        if match is not None:
            setattr(obj, f"{fk_field}_id", match.pk)
            setattr(obj, legacy_field, "")
            setattr(obj, unmatched_field, False)
            obj.save(update_fields=[fk_field, legacy_field, unmatched_field])
            linked += 1
        else:
            if not getattr(obj, unmatched_field):
                setattr(obj, unmatched_field, True)
                obj.save(update_fields=[unmatched_field])
            unmatched += 1
    return linked, unmatched
