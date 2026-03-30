"""
TISS Retorno XML Parser (S-023b)
==================================
Parses the ANS-standard "retorno de lote" XML that convênios return after
processing a submitted batch. Updates TISSGuide statuses and creates Glosa
records for denied items.

TISS 4.01.00 retorno envelope structure (simplified):
  <mensagemTISS>
    <operadoraParaPrestador>
      <retornoLote>
        <numeroLote>202603001</numeroLote>
        <protocoloLote>
          <numeroProtocolo>…</numeroProtocolo>
          <dataProtocolo>…</dataProtocolo>
        </protocoloLote>
        <retornoGuias>
          <guiaSP_SADT>
            <numeroGuiaPrestador>202603000001</numeroGuiaPrestador>
            <situacaoGuia>...</situacaoGuia>  <!-- 1=pago, 2=glosado, 3=parcialmente pago -->
            <glosas>
              <glosa>
                <codigoGlosa>01</codigoGlosa>
                <descricaoGlosa>Procedimento não coberto</descricaoGlosa>
                <valorGlosa>150.00</valorGlosa>
              </glosa>
            </glosas>
          </guiaSP_SADT>
          …
        </retornoGuias>
      </retornoLote>
    </operadoraParaPrestador>
  </mensagemTISS>
"""

import logging
from decimal import Decimal, InvalidOperation

from django.db import transaction
from lxml import etree

from apps.billing.models import GLOSA_REASON_CODES, Glosa, TISSBatch, TISSGuide

_VALID_REASON_CODES = {code for code, _ in GLOSA_REASON_CODES}

logger = logging.getLogger(__name__)

TISS_NS = "http://www.ans.gov.br/padroes/tiss/schemas"
NS = {"ans": TISS_NS}

# Map TISS situacaoGuia codes to our guide status choices
SITUACAO_TO_STATUS = {
    "1": "paid",
    "2": "denied",
    "3": "paid",   # partially paid — treated as paid, glosas will record the deductions
    "4": "denied",
    "5": "denied",  # devolvida (guide returned/voided by insurer) — not paid
}


def parse_retorno(xml_bytes: bytes) -> dict:
    """
    Parse a TISS retorno XML and apply changes to the database.

    Returns a summary dict:
      {
        "batch_number": str,
        "guides_updated": int,
        "glosas_created": int,
        "errors": [str],
      }
    """
    errors: list[str] = []
    guides_updated = 0
    glosas_created = 0
    batch_number = ""

    try:
        # Disable XXE: prevent external entity resolution and network access from uploaded XML
        _parser = etree.XMLParser(resolve_entities=False, no_network=True)
        root = etree.fromstring(xml_bytes, parser=_parser)
    except etree.XMLSyntaxError as exc:
        return {"batch_number": "", "guides_updated": 0, "glosas_created": 0, "errors": [str(exc)]}

    # Locate retornoLote
    retorno_lote = root.find(".//ans:retornoLote", NS)
    if retorno_lote is None:
        return {
            "batch_number": "",
            "guides_updated": 0,
            "glosas_created": 0,
            "errors": ["<retornoLote> element not found in XML"],
        }

    numero_lote_el = retorno_lote.find("ans:numeroLote", NS)
    if numero_lote_el is not None:
        batch_number = (numero_lote_el.text or "").strip()

    # Resolve the batch
    batch: TISSBatch | None = None
    if batch_number:
        try:
            batch = TISSBatch.objects.get(batch_number=batch_number)
        except TISSBatch.DoesNotExist:
            errors.append(f"Batch '{batch_number}' not found in database.")

    # Process each guide result inside a single atomic block so partial failures
    # don't leave the batch in an inconsistent state.
    retorno_guias = retorno_lote.find("ans:retornoGuias", NS)
    if retorno_guias is None:
        return {
            "batch_number": batch_number,
            "guides_updated": guides_updated,
            "glosas_created": glosas_created,
            "errors": errors,
        }

    with transaction.atomic():
        for guide_el in retorno_guias:
            guide_number_el = guide_el.find("ans:numeroGuiaPrestador", NS)
            if guide_number_el is None:
                errors.append(f"Guide element <{guide_el.tag}> missing numeroGuiaPrestador")
                continue

            guide_number = (guide_number_el.text or "").strip()
            try:
                guide = TISSGuide.objects.get(guide_number=guide_number)
            except TISSGuide.DoesNotExist:
                errors.append(f"Guide '{guide_number}' not found in database.")
                continue

            situacao_el = guide_el.find("ans:situacaoGuia", NS)
            situacao = (situacao_el.text or "").strip() if situacao_el is not None else ""
            if situacao not in SITUACAO_TO_STATUS:
                errors.append(
                    f"Guide '{guide_number}': unknown situacaoGuia code '{situacao}' — guide status unchanged."
                )
                continue
            new_status = SITUACAO_TO_STATUS[situacao]

            guide.status = new_status
            guide.save(update_fields=["status", "updated_at"])
            guides_updated += 1

            # Create Glosa records for denied items
            glosas_el = guide_el.find("ans:glosas", NS)
            if glosas_el is not None:
                for glosa_el in glosas_el.findall("ans:glosa", NS):
                    codigo_el = glosa_el.find("ans:codigoGlosa", NS)
                    descricao_el = glosa_el.find("ans:descricaoGlosa", NS)
                    valor_el = glosa_el.find("ans:valorGlosa", NS)

                    raw_code = (codigo_el.text or "").strip() if codigo_el is not None else ""
                    # Validate reason code against known TISS codes; default to "99" (Outro)
                    reason_code = raw_code[:5] if raw_code[:5] in _VALID_REASON_CODES else "99"
                    reason_desc = (descricao_el.text or "").strip() if descricao_el is not None else ""
                    try:
                        value_denied = Decimal((valor_el.text or "0").strip())
                    except InvalidOperation:
                        value_denied = Decimal("0")

                    Glosa.objects.create(
                        guide=guide,
                        reason_code=reason_code,
                        reason_description=reason_desc,
                        value_denied=value_denied,
                    )
                    glosas_created += 1

                    # Update guide status to denied if any glosa with value exists
                    if guide.status == "paid" and value_denied > 0:
                        guide.status = "denied"
                        guide.save(update_fields=["status", "updated_at"])

        # Update batch status to processed
        if batch:
            batch.status = "processed"
            batch.save(update_fields=["status"])

    return {
        "batch_number": batch_number,
        "guides_updated": guides_updated,
        "glosas_created": glosas_created,
        "errors": errors,
    }
