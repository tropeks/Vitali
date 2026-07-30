"""
S3 — Remessa DATASUS BPA-Magnético / APAC (texto posicional).
=============================================================
DATASUS faturamento ambulatorial is transmitted as a **fixed-width positional
text file** (``.txt``), not XML — this module is the SUS analogue of
``apps.billing.services.xml_engine`` (which emits a TISS batch XML). Two pure
functions read a competência's production rows and emit the remessa *string*
(the view wraps it as a downloadable file; no file I/O happens here):

  * :func:`gerar_remessa_bpa`  — BPA-Magnético (BPA-C + BPA-I lines).
  * :func:`gerar_remessa_apac` — APAC authorizations + secondary procedures.

Everything is deterministic: given the same rows, byte-identical output. Rows are
ordered by ``id`` so the line order (and therefore the control field) is stable.

Positional layout — design note
--------------------------------
This is a **coherent, documented, structurally-faithful** BPA-Magnético-style
layout (header + typed detail lines, fixed widths, zero/space padding, a
control/count field), NOT the byte-exact official DATASUS field map. The offsets
and widths below are the contract the S4 frontend and any real-DATASUS
conformance work build on — change them deliberately. Every field is a
module-level ``(offset, width)`` constant; a record's total width is the
``*_WIDTH`` constant and equals the sum of its fields.

Padding rules (documented, applied by the helpers below):
  * **num**   — an integer value, right-justified and **zero**-padded, truncated
    from the left if it overflows (``_num``). Used for counts, quantidades,
    idade, CNES, control.
  * **code**  — a fixed catalog code (SIGTAP/CBO), right-justified **zero**-padded
    to its width (``_code``). SIGTAP codes are 10 digits, CBO 6.
  * **txt**   — free text (CNS, CID), left-justified **space**-padded, truncated
    from the right (``_txt``).
  * **valor** — a Decimal amount emitted in **centavos** (value × 100, integer),
    right-justified zero-padded (``_centavos``) — the remessa never carries a
    decimal separator.
  * **competência** — ``AAAAMM`` (the stored ``AAAA-MM`` with the dash removed).
  * **datas** — ``AAAAMMDD``.

Line terminator is ``\\r\\n`` (CRLF — the DATASUS convention); there is no
trailing terminator after the last line.

Header line (tipo ``01``) — total :data:`HEADER_WIDTH` = 25
    ``01`` (2) | competência AAAAMM (6) | nº de linhas de detalhe (6, zero) |
    controle (4, zero) | CNES de origem (7, zero)

    ``controle`` = ``(Σ quantidades de todas as linhas de detalhe + nº de linhas)
    mod 10000`` — a deterministic count/quantity checksum (documented, not the
    official DATASUS algorithm).

BPA-C detail line (tipo ``02``) — total :data:`BPA_C_WIDTH` = 50
    ``02`` (2) | competência (6) | CNES (7) | SIGTAP (10) | CBO (6) | idade (3) |
    quantidade (6) | valor centavos (10)

BPA-I detail line (tipo ``03``) — total :data:`BPA_I_WIDTH` = 66
    ``03`` (2) | competência (6) | CNES (7) | SIGTAP (10) | CBO (6) | CNS (15) |
    CID (4) | quantidade (6) | valor centavos (10)

APAC line (tipo ``11``) — total :data:`APAC_WIDTH` = 83
    ``11`` (2) | competência (6) | CNES (7) | número APAC (13) | SIGTAP principal
    (10) | CID (4) | CNS (15) | validade início AAAAMMDD (8) | validade fim
    AAAAMMDD (8) | valor centavos (10)

APAC secondary line (tipo ``12``) — total :data:`APAC_SEC_WIDTH` = 47
    ``12`` (2) | competência (6) | número APAC (13) | SIGTAP (10) | quantidade
    (6) | valor centavos (10)

AIH line (tipo ``21``) — total :data:`AIH_WIDTH` = 87 (SISAIH-style; AI3)
    ``21`` (2) | competência (6) | CNES (7) | número AIH (13) | SIGTAP principal
    (10) | CID (4) | CNS (15) | data internação AAAAMMDD (8) | data saída
    AAAAMMDD (8) | caráter (2) | motivo saída/permanência (2, código) | valor
    centavos (10)

AIH secondary line (tipo ``22``) — total :data:`AIH_SEC_WIDTH` = 47
    ``22`` (2) | competência (6) | número AIH (13) | SIGTAP (10) | quantidade
    (6) | valor centavos (10)

The AIH remessa is the SISAIH analogue of the APAC remessa above and follows the
SAME house convention: **coherent, documented, structurally-faithful — NOT the
byte-exact official DATASUS/SISAIH field map**. See :func:`gerar_remessa_aih` for
the two known real-DATASUS conformance gaps (official 13-digit AIH number vs. the
AI2 provisional number; the abbreviated ``motivo_saida`` code table).
"""

from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.billing.sus_models import SusCompetencia

# ─── Line terminator + record type tags ──────────────────────────────────────
LINE_TERMINATOR = "\r\n"

TIPO_HEADER = "01"
TIPO_BPA_C = "02"
TIPO_BPA_I = "03"
TIPO_APAC = "11"
TIPO_APAC_SEC = "12"
TIPO_AIH = "21"
TIPO_AIH_SEC = "22"

# ─── Header (tipo 01) field offsets/widths ───────────────────────────────────
HEADER_TIPO = (0, 2)
HEADER_COMPETENCIA = (2, 6)
HEADER_NUM_LINHAS = (8, 6)
HEADER_CONTROLE = (14, 4)
HEADER_CNES = (18, 7)
HEADER_WIDTH = 25

# ─── BPA-C (tipo 02) field offsets/widths ────────────────────────────────────
BPA_C_TIPO = (0, 2)
BPA_C_COMPETENCIA = (2, 6)
BPA_C_CNES = (8, 7)
BPA_C_SIGTAP = (15, 10)
BPA_C_CBO = (25, 6)
BPA_C_IDADE = (31, 3)
BPA_C_QUANTIDADE = (34, 6)
BPA_C_VALOR = (40, 10)
BPA_C_WIDTH = 50

# ─── BPA-I (tipo 03) field offsets/widths ────────────────────────────────────
BPA_I_TIPO = (0, 2)
BPA_I_COMPETENCIA = (2, 6)
BPA_I_CNES = (8, 7)
BPA_I_SIGTAP = (15, 10)
BPA_I_CBO = (25, 6)
BPA_I_CNS = (31, 15)
BPA_I_CID = (46, 4)
BPA_I_QUANTIDADE = (50, 6)
BPA_I_VALOR = (56, 10)
BPA_I_WIDTH = 66

# ─── APAC (tipo 11) field offsets/widths ─────────────────────────────────────
APAC_TIPO = (0, 2)
APAC_COMPETENCIA = (2, 6)
APAC_CNES = (8, 7)
APAC_NUMERO = (15, 13)
APAC_SIGTAP = (28, 10)
APAC_CID = (38, 4)
APAC_CNS = (42, 15)
APAC_VALIDADE_INICIO = (57, 8)
APAC_VALIDADE_FIM = (65, 8)
APAC_VALOR = (73, 10)
APAC_WIDTH = 83

# ─── APAC secundário (tipo 12) field offsets/widths ──────────────────────────
APAC_SEC_TIPO = (0, 2)
APAC_SEC_COMPETENCIA = (2, 6)
APAC_SEC_NUMERO = (8, 13)
APAC_SEC_SIGTAP = (21, 10)
APAC_SEC_QUANTIDADE = (31, 6)
APAC_SEC_VALOR = (37, 10)
APAC_SEC_WIDTH = 47

# ─── AIH (tipo 21) field offsets/widths — SISAIH-style ───────────────────────
AIH_TIPO = (0, 2)
AIH_COMPETENCIA = (2, 6)
AIH_CNES = (8, 7)
AIH_NUMERO = (15, 13)
AIH_SIGTAP = (28, 10)
AIH_CID = (38, 4)
AIH_CNS = (42, 15)
AIH_DATA_INTERNACAO = (57, 8)
AIH_DATA_SAIDA = (65, 8)
AIH_CARATER = (73, 2)
AIH_MOTIVO = (75, 2)
AIH_VALOR = (77, 10)
AIH_WIDTH = 87

# ─── AIH secundário (tipo 22) field offsets/widths ───────────────────────────
AIH_SEC_TIPO = (0, 2)
AIH_SEC_COMPETENCIA = (2, 6)
AIH_SEC_NUMERO = (8, 13)
AIH_SEC_SIGTAP = (21, 10)
AIH_SEC_QUANTIDADE = (31, 6)
AIH_SEC_VALOR = (37, 10)
AIH_SEC_WIDTH = 47

# ─── AIH motivo de saída/permanência → código posicional (2 dígitos) ─────────
# Conversão dos rótulos internos do modelo (AihAutorizacao.MotivoSaida) para o
# código posicional de 2 dígitos que entra na linha AIH. Segue a convenção SUS
# de motivo de saída/permanência (dezena = classe do desfecho: 1x alta, 3x
# transferência, 4x óbito, 5x permanência) e é **estruturalmente-fiel, NÃO
# byte-exato oficial** — a tabela byte-exata do SISAIH (com todos os subcódigos
# de alta/óbito/transferência) é trabalho de conformidade real-DATASUS futuro.
# Vazio/desconhecido → "00".
AIH_MOTIVO_CODIGO = {
    "alta_curado": "11",
    "alta_melhorado": "12",
    "transferencia": "31",
    "obito": "41",
    "permanencia": "51",
}


# ─── Padding helpers ─────────────────────────────────────────────────────────
def _scrub(value) -> str:
    """Strip control chars (CR/LF/tab + other C0/C1 controls) from a field value
    BEFORE it enters a fixed-width positional record. Without this a staff-entered
    CNS/CID containing a newline would inject a line break — and thus a forged
    production line — into the DATASUS remessa (CSO 2026-07-28, finding #1)."""
    return "".join(ch for ch in str(value or "") if ch >= " " and ch != "\x7f")


def _num(value, width: int) -> str:
    """Integer value → right-justified, zero-padded, left-truncated to ``width``."""
    s = str(int(value))
    return s[-width:].rjust(width, "0")


def _code(value, width: int) -> str:
    """Catalog code (str) → right-justified, zero-padded, left-truncated to ``width``."""
    s = _scrub(value)
    return s[-width:].rjust(width, "0")


def _txt(value, width: int) -> str:
    """Free text → left-justified, space-padded, right-truncated to ``width``."""
    s = _scrub(value)
    return s[:width].ljust(width, " ")


def _centavos(value, width: int) -> str:
    """Decimal amount → integer centavos, zero-padded, left-truncated to ``width``."""
    cents = int((Decimal(value) * 100).to_integral_value())
    return str(cents)[-width:].rjust(width, "0")


def _competencia_aaaamm(competencia: str) -> str:
    """``AAAA-MM`` → ``AAAAMM`` (6 chars)."""
    return _txt(str(competencia).replace("-", ""), 6)


def _data_aaaammdd(value) -> str:
    """A ``date`` → ``AAAAMMDD`` (8 chars); blank/None → 8 zeros."""
    if value is None:
        return "0" * 8
    return value.strftime("%Y%m%d")


def _header_line(competencia_aaaamm: str, cnes: str, num_linhas: int, controle: int) -> str:
    return (
        TIPO_HEADER
        + _txt(competencia_aaaamm, HEADER_COMPETENCIA[1])
        + _num(num_linhas, HEADER_NUM_LINHAS[1])
        + _num(controle % 10000, HEADER_CONTROLE[1])
        + _code(cnes, HEADER_CNES[1])
    )


def _cnes_of(competencia: SusCompetencia) -> str:
    """The establishment's CNES code (governed FK or legacy text), digits only."""
    return "".join(ch for ch in (competencia.establishment.cnes_code or "") if ch.isdigit())


# ─── Public API ──────────────────────────────────────────────────────────────
def gerar_remessa_bpa(competencia: SusCompetencia) -> str:
    """Return the BPA-Magnético remessa text (header + BPA-C + BPA-I detail lines).

    Pure: reads ``competencia.bpa_c`` / ``competencia.bpa_i`` (ordered by id for
    determinism), emits fixed-width positional lines, no file I/O. Zero rows → a
    lone header with count 0. See the module docstring for the field layout.
    """
    comp_aaaamm = _competencia_aaaamm(competencia.competencia)
    cnes = _cnes_of(competencia)

    detail: list[str] = []
    total_quantidade = 0

    for bc in competencia.bpa_c.order_by("id"):
        total_quantidade += int(bc.quantidade)
        detail.append(
            TIPO_BPA_C
            + comp_aaaamm
            + _code(cnes, BPA_C_CNES[1])
            + _code(bc.sigtap.code, BPA_C_SIGTAP[1])
            + _txt(bc.cbo.code if bc.cbo_id else "", BPA_C_CBO[1])
            + _num(bc.idade, BPA_C_IDADE[1])
            + _num(bc.quantidade, BPA_C_QUANTIDADE[1])
            + _centavos(bc.valor, BPA_C_VALOR[1])
        )

    for bi in competencia.bpa_i.order_by("id"):
        total_quantidade += int(bi.quantidade)
        detail.append(
            TIPO_BPA_I
            + comp_aaaamm
            + _code(cnes, BPA_I_CNES[1])
            + _code(bi.sigtap.code, BPA_I_SIGTAP[1])
            + _txt(bi.cbo.code if bi.cbo_id else "", BPA_I_CBO[1])  # type: ignore[union-attr]
            + _txt(bi.cns, BPA_I_CNS[1])
            + _txt(bi.cid, BPA_I_CID[1])
            + _num(bi.quantidade, BPA_I_QUANTIDADE[1])
            + _centavos(bi.valor, BPA_I_VALOR[1])
        )

    controle = total_quantidade + len(detail)
    header = _header_line(comp_aaaamm, cnes, len(detail), controle)
    return LINE_TERMINATOR.join([header, *detail])


def gerar_remessa_apac(competencia: SusCompetencia) -> str:
    """Return the APAC remessa text (header + APAC lines + secondary-procedure lines).

    Pure: reads ``competencia.apacs`` and each APAC's
    ``procedimentos_secundarios`` (ordered by id), emits fixed-width positional
    lines, no file I/O. Zero APACs → a lone header with count 0.
    """
    comp_aaaamm = _competencia_aaaamm(competencia.competencia)
    cnes = _cnes_of(competencia)

    detail: list[str] = []
    total_quantidade = 0

    for apac in competencia.apacs.order_by("id"):
        detail.append(
            TIPO_APAC
            + comp_aaaamm
            + _code(cnes, APAC_CNES[1])
            + _code(apac.numero_apac, APAC_NUMERO[1])
            + _code(apac.procedimento_principal.code, APAC_SIGTAP[1])
            + _txt(apac.cid_principal_code, APAC_CID[1])
            + _txt(apac.cns, APAC_CNS[1])
            + _data_aaaammdd(apac.validade_inicio)
            + _data_aaaammdd(apac.validade_fim)
            + _centavos(apac.valor, APAC_VALOR[1])
        )
        for sec in apac.procedimentos_secundarios.order_by("id"):
            total_quantidade += int(sec.quantidade)
            detail.append(
                TIPO_APAC_SEC
                + comp_aaaamm
                + _code(apac.numero_apac, APAC_SEC_NUMERO[1])
                + _code(sec.sigtap.code, APAC_SEC_SIGTAP[1])
                + _num(sec.quantidade, APAC_SEC_QUANTIDADE[1])
                + _centavos(sec.valor, APAC_SEC_VALOR[1])
            )

    controle = total_quantidade + len(detail)
    header = _header_line(comp_aaaamm, cnes, len(detail), controle)
    return LINE_TERMINATOR.join([header, *detail])


def _motivo_saida_codigo(motivo_saida: str) -> str:
    """``AihAutorizacao.motivo_saida`` (rótulo) → código posicional de 2 dígitos.

    Estruturalmente-fiel (ver :data:`AIH_MOTIVO_CODIGO`). Vazio/desconhecido → ``00``.
    """
    return AIH_MOTIVO_CODIGO.get(motivo_saida or "", "00")


def gerar_remessa_aih(competencia: SusCompetencia) -> str:
    """Return the AIH (SISAIH) remessa text (header + AIH lines + secundário lines).

    Pure: reads ``competencia.aihs`` and each AIH's ``procedimentos_secundarios``
    (ordered by id for determinism), emits fixed-width positional lines, no file
    I/O. Zero AIHs → a lone header with count 0. Mirrors
    :func:`gerar_remessa_apac`; see the module docstring for the AIH field layout.

    Design note (SISAIH conformance) — this is a **coherent, documented,
    structurally-faithful** SISAIH-style layout, NOT the byte-exact official
    DATASUS/SISAIH field map (same convention as the BPA/APAC remessas above).
    Two known gaps for real-DATASUS conformance, left as future work:
      * The real SISAIH remessa requires the **official 13-digit AIH number**
        issued by the gestor SUS. The AI2 bridge may emit an internal
        *provisional* number (``AAAAMM`` + sequence); provisional numbers do NOT
        pass real-DATASUS conformance — reconciling the official number is future
        work. Generation is intentionally NOT blocked (the layout is
        structurally-faithful, for the frontend/contract).
      * ``motivo_saida`` is mapped to a 2-digit code by :data:`AIH_MOTIVO_CODIGO`
        (structurally-faithful, not the full official subcode table).
    """
    comp_aaaamm = _competencia_aaaamm(competencia.competencia)
    cnes = _cnes_of(competencia)

    detail: list[str] = []
    total_quantidade = 0

    for aih in competencia.aihs.order_by("id"):
        detail.append(
            TIPO_AIH
            + comp_aaaamm
            + _code(cnes, AIH_CNES[1])
            + _code(aih.numero_aih, AIH_NUMERO[1])
            + _code(aih.procedimento_principal.code, AIH_SIGTAP[1])
            + _txt(aih.cid_principal_code, AIH_CID[1])
            + _txt(aih.cns, AIH_CNS[1])
            + _data_aaaammdd(aih.data_internacao)
            + _data_aaaammdd(aih.data_saida)
            + _code(aih.carater_internacao, AIH_CARATER[1])
            + _motivo_saida_codigo(aih.motivo_saida)
            + _centavos(aih.valor, AIH_VALOR[1])
        )
        for sec in aih.procedimentos_secundarios.order_by("id"):
            total_quantidade += int(sec.quantidade)
            detail.append(
                TIPO_AIH_SEC
                + comp_aaaamm
                + _code(aih.numero_aih, AIH_SEC_NUMERO[1])
                + _code(sec.sigtap.code, AIH_SEC_SIGTAP[1])
                + _num(sec.quantidade, AIH_SEC_QUANTIDADE[1])
                + _centavos(sec.valor, AIH_SEC_VALOR[1])
            )

    controle = total_quantidade + len(detail)
    header = _header_line(comp_aaaamm, cnes, len(detail), controle)
    return LINE_TERMINATOR.join([header, *detail])


def remessa_filename(competencia: SusCompetencia, *, tipo: str = "BPA") -> str:
    """Downloadable filename, e.g. ``BPA_1234567_202607.txt`` / ``APAC_..._....txt``."""
    cnes = _cnes_of(competencia) or "0000000"
    return f"{tipo}_{cnes}_{_competencia_aaaamm(competencia.competencia)}.txt"


def exportar_competencia(competencia: SusCompetencia, *, actor=None) -> dict:
    """Generate + persist the BPA/APAC remessa and transition ``fechada → exportada``.

    Lifecycle rule: only a ``fechada`` competência may be exported (an ``aberta``
    one still accepts production; an already-``exportada`` one has an immutable
    remessa). Anything else raises ``django.core.exceptions.ValidationError``
    (→ 409 at the view) with a Portuguese message.

    Storage decision (documented): the generated text is **stored** on the
    competência (``remessa_bpa`` / ``remessa_apac`` + ``exportada_at``), NOT
    regenerated on download — so the exact exported bytes are an immutable,
    auditable record even if BPA/APAC rows later change. Download re-serves the
    stored string. Atomic + ``select_for_update`` so a concurrent export cannot
    double-transition.

    Returns ``{"remessa_bpa", "remessa_apac", "remessa_aih", "filename_bpa",
    "filename_apac", "filename_aih"}`` (AIH keys ADDED in AI3 — BPA/APAC unchanged).
    """
    with transaction.atomic():
        comp = SusCompetencia.objects.select_for_update().get(pk=competencia.pk)
        if comp.status == SusCompetencia.Status.ABERTA:
            raise ValidationError(
                f"Competência {comp.competencia} está aberta; feche a competência antes de exportar."
            )
        if comp.status != SusCompetencia.Status.FECHADA:
            raise ValidationError(
                f"Competência {comp.competencia} não está fechada "
                f"(status={comp.status}); exportação bloqueada."
            )

        bpa = gerar_remessa_bpa(comp)
        apac = gerar_remessa_apac(comp)
        aih = gerar_remessa_aih(comp)
        comp.remessa_bpa = bpa
        comp.remessa_apac = apac
        comp.remessa_aih = aih
        comp.exportada_at = timezone.now()
        comp.status = SusCompetencia.Status.EXPORTADA
        comp.save(
            update_fields=[
                "remessa_bpa",
                "remessa_apac",
                "remessa_aih",
                "exportada_at",
                "status",
                "updated_at",
            ]
        )

    return {
        "remessa_bpa": bpa,
        "remessa_apac": apac,
        "remessa_aih": aih,
        "filename_bpa": remessa_filename(comp, tipo="BPA"),
        "filename_apac": remessa_filename(comp, tipo="APAC"),
        "filename_aih": remessa_filename(comp, tipo="AIH"),
    }
