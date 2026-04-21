"""
S-065: Prescription PDF generator using WeasyPrint + Jinja2-style Django templates.

Key design decisions:
- Sign gate: raises ValueError if prescription is not signed.
- Cache: prescription_pdf:{id}:{signed_at.timestamp()} (invalidated if re-signed).
- Digital hash: sha256 of id + all item data + signed_at (anti-tampering).
- Controlled substances → different template with ANVISA blue border.
"""
import hashlib
import logging
from io import BytesIO

from django.conf import settings
from django.core.cache import cache
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)

PRESCRIPTION_PDF_CACHE_TTL = getattr(settings, "PRESCRIPTION_PDF_CACHE_TTL", 3600)

NORMAL_TEMPLATE = "pdf/prescription.html"
CONTROLLED_TEMPLATE = "pdf/prescription_controlled.html"


def _compute_digital_hash(prescription, items) -> str:
    """
    Compute a tamper-evident SHA-256 hash of the prescription data.
    Hash: sha256("{id}|{sorted_item_data}|{signed_at.isoformat()}")
    """
    item_data_parts = []
    for item in items:
        drug_name = item.generic_name or (item.drug.name if item.drug_id else "")
        part = f"{drug_name}:{item.quantity}:{item.unit_of_measure}:{item.dosage_instructions}"
        item_data_parts.append(part)

    item_data_sorted = "|".join(sorted(item_data_parts))
    raw = f"{prescription.id}|{item_data_sorted}|{prescription.signed_at.isoformat()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _has_controlled_substance(items) -> bool:
    """Return True if any item in the prescription is a controlled substance."""
    for item in items:
        try:
            if item.drug_id and item.drug.is_controlled:
                return True
        except Exception:
            pass
    return False


def _get_clinic_info(prescription) -> dict:
    """
    Extract clinic/tenant info for the PDF header.
    Falls back to safe defaults if tenant data is unavailable.
    """
    info = {
        "name": "Clínica",
        "address": "",
        "phone": "",
        "cnpj": "",
        "logo_url": "",
    }
    try:
        from django_tenants.utils import get_current_schema_name
        schema_name = get_current_schema_name()
        from apps.core.models import Tenant
        tenant = Tenant.objects.get(schema_name=schema_name)
        info["name"] = tenant.name or "Clínica"
        # Optional extra fields from tenant if they exist
        for field_name in ("address", "phone", "cnpj", "logo_url"):
            val = getattr(tenant, field_name, None)
            if val:
                info[field_name] = val
    except Exception:
        pass
    return info


class PrescriptionPDFGenerator:
    """
    Generates a PDF for a signed prescription using WeasyPrint.
    Chooses template based on whether any item is a controlled substance.
    """

    def generate(self, prescription) -> bytes:
        """
        Generate a PDF for the given prescription.

        Raises ValueError if prescription is not signed.
        Returns PDF bytes.
        """
        # 1. Sign gate
        if not prescription.is_signed:
            raise ValueError(
                "Receita não assinada. Assine a receita antes de gerar o PDF."
            )

        # 2. Cache key — signed_at.timestamp() changes if re-signed
        signed_ts = prescription.signed_at.timestamp()
        cache_key = f"prescription_pdf:{prescription.id}:{signed_ts}"

        # 3. Cache hit
        cached = cache.get(cache_key)
        if cached is not None:
            logger.debug("PDF cache hit for prescription %s", prescription.id)
            return cached

        # 4. Load items
        items = list(
            prescription.items.select_related("drug").all()
        )

        # 5. Compute digital hash
        digital_hash = _compute_digital_hash(prescription, items)

        # 6. Choose template
        is_controlled = _has_controlled_substance(items)
        template_name = CONTROLLED_TEMPLATE if is_controlled else NORMAL_TEMPLATE

        # 7. Build context
        clinic_info = _get_clinic_info(prescription)
        from datetime import timedelta
        validity_date = prescription.signed_at + timedelta(days=30)

        context = {
            "prescription": prescription,
            "items": items,
            "digital_hash": digital_hash,
            "digital_hash_short": digital_hash[:12],
            "clinic_info": clinic_info,
            "validity_date": validity_date,
            "is_controlled": is_controlled,
        }

        # 8. Render HTML
        try:
            html_content = render_to_string(template_name, context)
        except Exception as exc:
            logger.error("Failed to render prescription template: %s", exc, exc_info=True)
            raise

        # 9. WeasyPrint → PDF bytes
        try:
            from weasyprint import HTML
            pdf_bytes = HTML(string=html_content).write_pdf()
        except Exception as exc:
            logger.error("WeasyPrint failed for prescription %s: %s", prescription.id, exc, exc_info=True)
            raise

        # 10. Cache PDF bytes
        try:
            cache.set(cache_key, pdf_bytes, PRESCRIPTION_PDF_CACHE_TTL)
        except Exception:
            pass  # cache failure is non-fatal

        return pdf_bytes
