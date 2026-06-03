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

            <!-- ITEM-LEVEL glosas: one block per executed procedure -->
            <procedimentosExecutados>
              <procedimentoExecutado>
                <sequencialItem>1</sequencialItem>
                <procedimento>
                  <codigoTabela>22</codigoTabela>
                  <codigoProcedimento>40304361</codigoProcedimento>  <!-- TUSS -->
                </procedimento>
                <glosasProcedimento>
                  <glosa>
                    <codigoGlosa>01</codigoGlosa>
                    <descricaoGlosa>Procedimento não coberto</descricaoGlosa>
                    <valorGlosa>150.00</valorGlosa>
                  </glosa>
                </glosasProcedimento>
              </procedimentoExecutado>
            </procedimentosExecutados>

            <!-- GUIDE-LEVEL glosas: no procedure context (e.g. missing
                 signature, beneficiary-data problems). NEVER smeared onto
                 individual items. -->
            <glosasGuia>
              <glosa>
                <codigoGlosa>17</codigoGlosa>
                <descricaoGlosa>Falta assinatura do beneficiário</descricaoGlosa>
                <valorGlosa>0.00</valorGlosa>
              </glosa>
            </glosasGuia>

            <!-- Legacy / non-conforming senders sometimes emit a flat
                 <glosas> block with no procedure nesting. We treat that as
                 guide-level (cannot be unambiguously attributed to an item). -->
            <glosas>
              <glosa>...</glosa>
            </glosas>
          </guiaSP_SADT>
          …
        </retornoGuias>
      </retornoLote>
    </operadoraParaPrestador>
  </mensagemTISS>

Decision A-5 (flywheel precision)
---------------------------------
A glosa is mapped to its ``TISSGuideItem`` whenever the payer nests it under a
``<procedimentoExecutado>`` (procedure context). The match is:

  1. By ``codigoProcedimento`` (TUSS) against ``guide.items`` resolved by
     ``tuss_code.code``.
  2. If multiple guide items share the same TUSS code (duplicate lines), the
     ``<sequencialItem>`` disambiguates by 1-based position within the guide's
     item ordering (pk order). When ``sequencialItem`` is absent and the TUSS
     code is ambiguous, we DO NOT guess-attach — we fall back to a guide-level
     Glosa (``guide_item=None``) and log a warning.

``was_denied`` backfill is then strictly scoped:
  * An item-level Glosa marks ``was_denied=True`` ONLY on flywheel rows for
    THAT item — ``GlosaSafetyAlert`` rows with that ``guide_item``, and the
    matching ``GlosaPrediction`` row(s) keyed by ``(guide, tuss_code)``.
  * A guide-level Glosa NEVER touches item-scoped ``was_denied``. It is a
    genuine guide-level denial (e.g. missing signature) and is recorded as such
    without poisoning per-item ground-truth.

Idempotency
-----------
Re-parsing the same retorno must not double-create Glosa rows or flip labels.
Each (guide, guide_item, reason_code, value_denied) Glosa is created with
``get_or_create`` so a re-run is a no-op. ``was_denied`` backfill is itself
idempotent (it only ever sets True on the matching scope).
"""

import logging
from decimal import Decimal, InvalidOperation

from django.db import transaction
from lxml import etree

from apps.billing.models import (
    GLOSA_REASON_CODES,
    Glosa,
    GlosaSafetyAlert,
    TISSBatch,
    TISSGuide,
    TISSGuideItem,
)

_VALID_REASON_CODES = {code for code, _ in GLOSA_REASON_CODES}

logger = logging.getLogger(__name__)

TISS_NS = "http://www.ans.gov.br/padroes/tiss/schemas"
NS = {"ans": TISS_NS}

# Map TISS situacaoGuia codes to our guide status choices
SITUACAO_TO_STATUS = {
    "1": "paid",
    "2": "denied",
    "3": "paid",  # partially paid — treated as paid, glosas will record the deductions
    "4": "denied",
    "5": "denied",  # devolvida (guide returned/voided by insurer) — not paid
}


def _find_ns(el, tag: str):
    """Find a child trying namespaced first, then the bare tag (non-conforming senders)."""
    return el.find(f"ans:{tag}", NS) if el.find(f"ans:{tag}", NS) is not None else el.find(tag)


def _findall_ns(el, tag: str):
    """Find children trying namespaced first, then the bare tag."""
    found = el.findall(f"ans:{tag}", NS)
    return found if found else el.findall(tag)


def _text(el) -> str:
    return (el.text or "").strip() if el is not None else ""


def _parse_glosa_fields(glosa_el) -> tuple[str, str, Decimal]:
    """Extract (reason_code, reason_description, value_denied) from a <glosa> element."""
    raw_code = _text(_find_ns(glosa_el, "codigoGlosa"))
    # Validate reason code against known TISS codes; default to "99" (Outro)
    reason_code = raw_code[:5] if raw_code[:5] in _VALID_REASON_CODES else "99"
    reason_desc = _text(_find_ns(glosa_el, "descricaoGlosa"))
    try:
        value_denied = Decimal(_text(_find_ns(glosa_el, "valorGlosa")) or "0")
    except InvalidOperation:
        value_denied = Decimal("0")
    return reason_code, reason_desc, value_denied


def _resolve_guide_item(
    guide: TISSGuide,
    tuss_code: str,
    sequencial: str,
    guide_number: str,
    errors: list[str],
) -> TISSGuideItem | None:
    """Match a procedure-level glosa to a TISSGuideItem.

    Strategy (decision A-5):
      1. Filter the guide's items by TUSS code.
      2. Single match → use it.
      3. Multiple matches (duplicate TUSS lines) → disambiguate by
         ``sequencialItem`` (1-based index into the guide's item ordering).
      4. Cannot unambiguously match → return None (fall back to guide-level)
         and log a warning. NEVER guess-attach to the wrong item.
    """
    if not tuss_code:
        return None

    # Items in a stable, deterministic order (pk) so sequencialItem maps reliably.
    items = list(guide.items.select_related("tuss_code").order_by("pk"))

    # 4a. If a sequencialItem is provided, it is the authoritative pointer into
    # the guide's executed-procedure list. Verify the TUSS code agrees.
    if sequencial:
        try:
            seq_idx = int(sequencial)
        except (TypeError, ValueError):
            seq_idx = 0
        if 1 <= seq_idx <= len(items):
            candidate = items[seq_idx - 1]
            if candidate.tuss_code.code == tuss_code:
                return candidate
            # Sequence points at a line whose TUSS disagrees — ambiguous, do not guess.
            msg = (
                f"Guide '{guide_number}': glosa sequencialItem={seq_idx} points at TUSS "
                f"'{candidate.tuss_code.code}' but glosa TUSS is '{tuss_code}'. "
                "Falling back to guide-level (guide_item=None)."
            )
            logger.warning(msg)
            errors.append(msg)
            return None

    # 4b. No usable sequence — match purely by TUSS code.
    matches = [it for it in items if it.tuss_code.code == tuss_code]
    if len(matches) == 1:
        return matches[0]
    if len(matches) == 0:
        msg = (
            f"Guide '{guide_number}': procedure-level glosa TUSS '{tuss_code}' "
            "matches no guide item. Falling back to guide-level (guide_item=None)."
        )
        logger.warning(msg)
        errors.append(msg)
        return None
    # Ambiguous: duplicate TUSS lines and no sequencialItem to disambiguate.
    msg = (
        f"Guide '{guide_number}': procedure-level glosa TUSS '{tuss_code}' is ambiguous "
        f"({len(matches)} guide items share it) and no sequencialItem was provided. "
        "Falling back to guide-level (guide_item=None) — never guess-attaching."
    )
    logger.warning(msg)
    errors.append(msg)
    return None


def _create_glosa(
    guide: TISSGuide,
    guide_item: TISSGuideItem | None,
    reason_code: str,
    reason_desc: str,
    value_denied: Decimal,
) -> bool:
    """Idempotently create a Glosa. Returns True if a new row was created."""
    _obj, created = Glosa.objects.get_or_create(
        guide=guide,
        guide_item=guide_item,
        reason_code=reason_code,
        value_denied=value_denied,
        defaults={"reason_description": reason_desc},
    )
    return created


def _backfill_item_level(guide: TISSGuide, guide_item: TISSGuideItem) -> None:
    """Mark was_denied=True ONLY on flywheel rows for this specific item.

    - GlosaSafetyAlert rows carrying this guide_item (item-scoped engine verdicts).
    - GlosaPrediction rows keyed by (guide, tuss_code): GlosaPrediction has no
      guide_item FK today (it is created on guide edit, pre-line-persistence), but
      it DOES carry the TUSS code, so we can key item-level denials by TUSS within
      the guide — strictly narrower than the old guide-wide smear. (Limitation: if
      two predictions on the same guide share a TUSS code, both are marked; that is
      conservative and correct for that TUSS, never cross-contaminating other lines.)
    """
    GlosaSafetyAlert.objects.filter(guide=guide, guide_item=guide_item).update(was_denied=True)
    try:
        from apps.ai.models import GlosaPrediction

        GlosaPrediction.objects.filter(guide=guide, tuss_code=guide_item.tuss_code.code).update(
            was_denied=True
        )
    except Exception:
        # Fail-silently: retorno processing must not break if the ai app is unavailable.
        pass


def _process_guide_glosas(
    guide: TISSGuide,
    guide_el,
    guide_number: str,
    errors: list[str],
) -> int:
    """Extract and persist all glosas for one guide. Returns count of NEW Glosa rows.

    Item-level glosas (nested under procedimentoExecutado) are mapped to the
    matching TISSGuideItem and backfill was_denied for that item only. Genuinely
    guide-level glosas (glasasGuia / flat glosas) stay guide_item=None and never
    touch item-scoped labels.
    """
    glosas_created = 0
    any_value_denied = False

    # ── 1. Item-level glosas under <procedimentosExecutados>/<procedimentoExecutado> ──
    proc_container = _find_ns(guide_el, "procedimentosExecutados")
    if proc_container is not None:
        for proc_el in _findall_ns(proc_container, "procedimentoExecutado"):
            sequencial = _text(_find_ns(proc_el, "sequencialItem"))
            proc_inner = _find_ns(proc_el, "procedimento")
            tuss_code = (
                _text(_find_ns(proc_inner, "codigoProcedimento")) if proc_inner is not None else ""
            )

            # Glosas for this procedure may be under <glosasProcedimento> or a
            # nested <glosas>; accept either. (lxml elements are falsy when
            # childless, so compare with `is not None`, never truthiness.)
            glosas_block = _find_ns(proc_el, "glosasProcedimento")
            if glosas_block is None:
                glosas_block = _find_ns(proc_el, "glosas")
            if glosas_block is None:
                continue

            for glosa_el in _findall_ns(glosas_block, "glosa"):
                reason_code, reason_desc, value_denied = _parse_glosa_fields(glosa_el)
                guide_item = _resolve_guide_item(guide, tuss_code, sequencial, guide_number, errors)
                if _create_glosa(guide, guide_item, reason_code, reason_desc, value_denied):
                    glosas_created += 1
                if value_denied > 0:
                    any_value_denied = True
                if guide_item is not None:
                    _backfill_item_level(guide, guide_item)

    # ── 2. Guide-level glosas under <glosasGuia> (true guide-level denials) ──
    guide_glosas = _find_ns(guide_el, "glosasGuia")
    if guide_glosas is not None:
        for glosa_el in _findall_ns(guide_glosas, "glosa"):
            reason_code, reason_desc, value_denied = _parse_glosa_fields(glosa_el)
            # guide_item stays None — NEVER smeared onto items (decision A-5).
            if value_denied > 0:
                any_value_denied = True
            if _create_glosa(guide, None, reason_code, reason_desc, value_denied):
                glosas_created += 1

    # ── 3. Legacy/flat <glosas> block (no procedure nesting) → guide-level ──
    # Only consult this if it is a DIRECT child of the guide (not the per-procedure
    # ones we already consumed above). Cannot be unambiguously attributed to an item.
    flat_glosas = _find_ns(guide_el, "glosas")
    if flat_glosas is not None:
        for glosa_el in _findall_ns(flat_glosas, "glosa"):
            reason_code, reason_desc, value_denied = _parse_glosa_fields(glosa_el)
            if value_denied > 0:
                any_value_denied = True
            if _create_glosa(guide, None, reason_code, reason_desc, value_denied):
                glosas_created += 1

    # Status escalation (guide-scoped): a paid guide with any denied value
    # becomes denied. NOTE this is the GUIDE status only — item-level was_denied
    # labels are set strictly per-item above (_backfill_item_level), never smeared.
    if guide.status == "paid" and any_value_denied:
        guide.status = "denied"
        guide.save(update_fields=["status", "updated_at"])

    return glosas_created


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

    # Locate retornoLote — try namespaced first, fall back for non-conforming senders.
    # (lxml elements are falsy when childless, so compare with `is not None`.)
    retorno_lote = root.find(".//ans:retornoLote", NS)
    if retorno_lote is None:
        retorno_lote = root.find(".//retornoLote")
    if retorno_lote is None:
        return {
            "batch_number": "",
            "guides_updated": 0,
            "glosas_created": 0,
            "errors": ["<retornoLote> element not found in XML"],
        }

    numero_lote_el = _find_ns(retorno_lote, "numeroLote")
    if numero_lote_el is not None:
        batch_number = _text(numero_lote_el)

    # Resolve the batch
    batch: TISSBatch | None = None
    if batch_number:
        try:
            batch = TISSBatch.objects.get(batch_number=batch_number)
        except TISSBatch.DoesNotExist:
            errors.append(f"Batch '{batch_number}' not found in database.")

    # Process each guide result inside a single atomic block so partial failures
    # don't leave the batch in an inconsistent state.
    retorno_guias = _find_ns(retorno_lote, "retornoGuias")
    if retorno_guias is None:
        return {
            "batch_number": batch_number,
            "guides_updated": guides_updated,
            "glosas_created": glosas_created,
            "errors": errors,
        }

    with transaction.atomic():
        for guide_el in retorno_guias:
            guide_number_el = _find_ns(guide_el, "numeroGuiaPrestador")
            if guide_number_el is None:
                errors.append(f"Guide element <{guide_el.tag}> missing numeroGuiaPrestador")
                continue

            guide_number = _text(guide_number_el)
            try:
                guide = TISSGuide.objects.get(guide_number=guide_number)
            except TISSGuide.DoesNotExist:
                errors.append(f"Guide '{guide_number}' not found in database.")
                continue

            situacao_el = _find_ns(guide_el, "situacaoGuia")
            situacao = _text(situacao_el)
            if situacao not in SITUACAO_TO_STATUS:
                errors.append(
                    f"Guide '{guide_number}': unknown situacaoGuia code '{situacao}' — "
                    "guide status unchanged."
                )
                continue
            new_status = SITUACAO_TO_STATUS[situacao]

            guide.status = new_status
            guide.save(update_fields=["status", "updated_at"])
            guides_updated += 1

            glosas_created += _process_guide_glosas(guide, guide_el, guide_number, errors)

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
