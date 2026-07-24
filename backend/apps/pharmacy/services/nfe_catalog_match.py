"""
NF-e ↔ ANVISA catalog matching (E3-T2)
======================================
When an NF-e line carries an EAN/GTIN barcode (``cEAN``), we can auto-suggest the
SHARED-schema catalog product it refers to by matching that barcode against
``core.AnvisaProduct.ean``. This gives the human reviewer a governed catalog
anchor for the line before they confirm the internal ``Drug`` mapping.

Kept deliberately small and side-effect-free: it *suggests*, it does not persist
or mutate the ``NFeCatalogMapping`` — the human confirmation flow owns that.
"""

from __future__ import annotations

from apps.core.catalog_models import AnvisaProduct


def match_anvisa_product_by_ean(barcode: str | None) -> AnvisaProduct | None:
    """Return the active :class:`AnvisaProduct` whose EAN equals ``barcode``.

    ``None`` for a blank barcode or no match — never raises. Thin wrapper over
    :meth:`AnvisaProduct.by_ean` so callers can pass a raw barcode string.
    """
    return AnvisaProduct.by_ean(barcode)


def suggest_anvisa_product_for_item(item) -> AnvisaProduct | None:
    """Auto-suggest the catalog product for an ``NFeReceiptItem`` by its EAN.

    ``item.barcode`` is populated from the NF-e ``cEAN`` element at ingestion
    (see ``nfe_ingestion.ingest_xml``). Returns the matched catalog product, or
    ``None`` when the line has no barcode or no catalog product matches.
    """
    return AnvisaProduct.by_ean(getattr(item, "barcode", None))
