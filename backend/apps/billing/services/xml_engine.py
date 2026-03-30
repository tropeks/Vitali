"""
TISS XML Engine
================
Generates and validates TISS 4.01.00 XML for guides and batches.

Design notes:
- Uses Jinja2 for templating (already installed with Django; no extra dep).
  Templates live in apps/billing/templates/tiss/*.xml.j2.
- Validates against the ANS XSD schema using lxml. The XSD file must be
  placed at apps/billing/schemas/tissV4_01_00.xsd.
  Download from: https://www.ans.gov.br/images/stories/Prestadores/padrao_tiss.zip
- Path is absolute (relative paths break when cwd != project root).
- If the XSD file is absent, validate_xml() returns a warning rather than
  crashing — useful in development before the schema file is added.
"""

import hashlib
import logging
from decimal import Decimal
from pathlib import Path

from django.utils import timezone
from jinja2 import Environment, FileSystemLoader, select_autoescape

logger = logging.getLogger(__name__)

# ─── Paths ────────────────────────────────────────────────────────────────────

_BILLING_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = _BILLING_DIR / "templates" / "tiss"
TISS_XSD_PATH = _BILLING_DIR / "schemas" / "tissV4_01_00.xsd"

# ─── Jinja2 environment ───────────────────────────────────────────────────────

def _make_jinja_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    # Custom filters
    env.filters["format_date"] = _format_date
    env.filters["format_time"] = _format_time
    env.filters["format_decimal"] = _format_decimal
    env.filters["format_currency"] = _format_currency
    return env


_jinja_env: Environment | None = None


def _env() -> Environment:
    global _jinja_env
    if _jinja_env is None:
        _jinja_env = _make_jinja_env()
    return _jinja_env


# ─── Jinja2 filters ───────────────────────────────────────────────────────────

def _format_date(value) -> str:
    """Convert date/datetime to TISS format YYYY-MM-DD."""
    if hasattr(value, "date"):
        value = value.date()
    return value.strftime("%Y-%m-%d") if value else ""


def _format_time(value) -> str:
    """Convert datetime to TISS format HH:MM:SS."""
    if hasattr(value, "strftime"):
        return value.strftime("%H:%M:%S")
    return "00:00:00"


def _format_decimal(value) -> str:
    """Format quantity with 2 decimal places."""
    return f"{Decimal(str(value)):.2f}"


def _format_currency(value) -> str:
    """Format monetary value with 2 decimal places."""
    return f"{Decimal(str(value)):.2f}"


# ─── Guide XML generation ─────────────────────────────────────────────────────

def generate_guide_xml(guide) -> str:
    """
    Generate the XML fragment for a single TISSGuide.
    Returns the rendered XML string (no envelope, no XSD declaration).
    """
    template_name = (
        "sadt_guide.xml.j2" if guide.guide_type == "sadt" else "consulta_guide.xml.j2"
    )
    template = _env().get_template(template_name)

    # Resolve professional from encounter
    professional = None
    try:
        professional = guide.encounter.professional
    except Exception:
        pass

    return template.render(guide=guide, professional=professional)


# ─── Batch XML generation ─────────────────────────────────────────────────────

def generate_batch_xml(batch) -> str:
    """
    Generate the full TISS batch XML envelope for a TISSBatch.
    Includes all guides in the batch. Returns the complete XML string.
    """
    template = _env().get_template("batch_envelope.xml.j2")

    guides = list(batch.guides.select_related("patient", "provider", "encounter").all())

    # Generate each guide's XML fragment
    guide_xml: dict[str, str] = {}
    for guide in guides:
        try:
            guide_xml[guide.guide_number] = generate_guide_xml(guide)
        except Exception as exc:
            logger.error("Failed to generate XML for guide %s: %s", guide.guide_number, exc)
            guide_xml[guide.guide_number] = f"<!-- ERROR guide {guide.guide_number}: {exc} -->"

    # Derive competency from the first guide (all should have the same)
    competency = guides[0].competency if guides else ""

    # Clinic CNES — derive from first guide's professional CNES if available
    clinic_cnes = ""
    if guides:
        try:
            clinic_cnes = guides[0].encounter.professional.cnes_code or ""
        except Exception:
            pass

    now = timezone.now()
    rendered = template.render(
        batch=batch,
        guides=guides,
        guide_xml=guide_xml,
        competency=competency,
        clinic_cnes=clinic_cnes,
        now=now,
        xml_hash="",  # placeholder — hash computed below
    )

    # Compute MD5 hash of the content body for epilogo (TISS spec)
    content_hash = hashlib.md5(rendered.encode()).hexdigest()
    rendered = rendered.replace("<ans:hash></ans:hash>", f"<ans:hash>{content_hash}</ans:hash>")

    return rendered


# ─── XSD Validation ───────────────────────────────────────────────────────────

def validate_xml(xml_string: str) -> list[str]:
    """
    Validate an XML string against the TISS 4.01.00 XSD.
    Returns a list of validation error strings (empty = valid).

    If the XSD file is not found, returns a single warning message instead
    of crashing — allows development without the ANS schema file.
    """
    if not TISS_XSD_PATH.exists():
        logger.warning(
            "TISS XSD not found at %s — skipping validation. "
            "Download from ANS and place at that path.",
            TISS_XSD_PATH,
        )
        return [
            f"[WARNING] XSD schema file not found at {TISS_XSD_PATH}. "
            "Validation skipped. Download from ANS padrao.tiss.ans.gov.br."
        ]

    from lxml import etree  # lazy import — lxml may be absent in test envs

    schema = etree.XMLSchema(file=str(TISS_XSD_PATH))
    try:
        _parser = etree.XMLParser(resolve_entities=False, no_network=True)
        doc = etree.fromstring(xml_string.encode(), parser=_parser)
    except etree.XMLSyntaxError as exc:
        return [f"XML parse error: {exc}"]

    schema.validate(doc)
    return [str(e) for e in schema.error_log]
