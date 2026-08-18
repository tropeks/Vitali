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


class TISSXMLGenerationError(Exception):
    """Raised when a guide/batch cannot be rendered into schema-valid TISS XML.

    Fail loud instead of silently emitting XML for the wrong guide type (or XML
    that structurally cannot satisfy the ANS XSD) — see the "honorários guide
    falls through to the consulta template" gap fixed by this exception.
    """


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
    env.filters["conselho_ans_code"] = _conselho_ans_code
    env.filters["uf_ibge_code"] = _uf_ibge_code
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


# dm_conselhoProfissional (tissSimpleTypesV4_01_00.xsd) — closed 2-digit ANS
# enumeration for professional councils. apps.emr.Professional.council_type
# stores the council acronym (CRM, COREN, ...); this maps it to the code the
# XSD actually requires. Keys are the exact values in
# apps.emr.models.Professional.COUNCIL_CHOICES.
_CONSELHO_ANS_CODE = {
    "CRESS": "01",
    "COREN": "02",
    "CRF": "03",
    "CRFA": "04",
    "CREFITO": "05",
    "CRM": "06",
    "CRN": "07",
    "CRO": "08",
    "CRP": "09",
}

# dm_UF (tissSimpleTypesV4_01_00.xsd) — closed 2-digit IBGE state code
# enumeration. Professional.council_state stores the 2-letter UF (SP, RJ...);
# this maps it to the IBGE numeric code the XSD requires.
_UF_IBGE_CODE = {
    "RO": "11",
    "AC": "12",
    "AM": "13",
    "RR": "14",
    "PA": "15",
    "AP": "16",
    "TO": "17",
    "MA": "21",
    "PI": "22",
    "CE": "23",
    "RN": "24",
    "PB": "25",
    "PE": "26",
    "AL": "27",
    "SE": "28",
    "BA": "29",
    "MG": "31",
    "ES": "32",
    "RJ": "33",
    "SP": "35",
    "PR": "41",
    "SC": "42",
    "RS": "43",
    "MS": "50",
    "MT": "51",
    "GO": "52",
    "DF": "53",
}


def _conselho_ans_code(council_type: str) -> str:
    """Map Professional.council_type (CRM, COREN, ...) to dm_conselhoProfissional."""
    return _CONSELHO_ANS_CODE.get(council_type, "")


def _uf_ibge_code(uf: str) -> str:
    """Map a 2-letter UF (SP, RJ, ...) to the dm_UF IBGE numeric code."""
    return _UF_IBGE_CODE.get((uf or "").upper(), "")


# ─── Guide XML generation ─────────────────────────────────────────────────────


_TEMPLATE_BY_GUIDE_TYPE = {
    "consulta": "consulta_guide.xml.j2",
    "sadt": "sadt_guide.xml.j2",
    "internacao": "internacao_guide.xml.j2",
    # "honorarios" is intentionally ABSENT: no ctm_honorarioIndividualGuia
    # template exists yet (see TISSXMLGenerationError below). It used to fall
    # through to consulta_guide.xml.j2 via a dict .get() default, silently
    # emitting a wrong guide type — 2.8 closes that hole.
}


def generate_guide_xml(guide) -> str:
    """
    Generate the XML fragment for a single TISSGuide.
    Returns the rendered XML string (no envelope, no XSD declaration).

    Raises TISSXMLGenerationError for guide types with no schema-conformant
    template (currently "honorarios") or with data the ANS XSD requires but
    the guide does not have (e.g. more than one procedure on a guia de
    consulta, which the XSD models as exactly one <procedimento>).
    """
    template_name = _TEMPLATE_BY_GUIDE_TYPE.get(guide.guide_type)
    if template_name is None:
        raise TISSXMLGenerationError(
            f"guide_type={guide.guide_type!r} has no TISS XML template. "
            "Rendering it as another guide type would silently produce the "
            "wrong ANS guide — see billing/models.py TISSGuide.guide_type "
            "choices and apps/billing/templates/tiss/."
        )
    template = _env().get_template(template_name)

    # Resolve professional from encounter
    professional = None
    try:
        professional = guide.encounter.professional
    except Exception:
        pass

    context: dict = {"guide": guide, "professional": professional}

    if guide.guide_type == "consulta":
        # ctm_consultaGuia (tissGuiasV4_01_00.xsd) models exactly ONE
        # <procedimento> per guia de consulta — not a repeatable list. Fail
        # loud rather than silently dropping items or emitting an invalid
        # repeated element.
        items = list(guide.items.all())
        if len(items) != 1:
            raise TISSXMLGenerationError(
                f"Guia de consulta {guide.guide_number} tem {len(items)} item(ns); "
                "o XSD TISS 4.01.00 (ctm_consultaGuia) permite exatamente um "
                "<procedimento> por guia de consulta."
            )
        context["item"] = items[0]

    return template.render(**context)


# ─── Batch XML generation ─────────────────────────────────────────────────────


def generate_batch_xml(batch) -> str:
    """
    Generate the full TISS batch XML envelope for a TISSBatch.
    Includes all guides in the batch. Returns the complete XML string.
    """
    template = _env().get_template("batch_envelope.xml.j2")

    guides = list(batch.guides.select_related("patient", "provider", "encounter").all())

    # ctm_guiaLote (tissGuiasV4_01_00.xsd) wraps <guiasTISS> in a <choice>: a
    # single lote may contain guides of exactly ONE ANS guide type (repeated),
    # not a mix. A mixed-type batch cannot be expressed as one schema-valid
    # <guiasTISS> element — fail loud instead of emitting an invalid document.
    guide_types = {guide.guide_type for guide in guides}
    if len(guide_types) > 1:
        raise TISSXMLGenerationError(
            f"Lote {batch.batch_number} mistura tipos de guia {sorted(guide_types)}; "
            "o XSD TISS 4.01.00 (ctm_guiaLote/guiasTISS) exige um único tipo de "
            "guia por lote. Separe em lotes homogêneos antes de gerar o XML."
        )

    # Generate each guide's XML fragment
    guide_xml: dict[str, str] = {}
    for guide in guides:
        try:
            guide_xml[guide.guide_number] = generate_guide_xml(guide)
        except Exception as exc:
            logger.error("Failed to generate XML for guide %s: %s", guide.guide_number, exc)
            guide_xml[guide.guide_number] = f"<!-- ERROR guide {guide.guide_number}: {exc} -->"

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
