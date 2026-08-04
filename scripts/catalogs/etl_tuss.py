"""ETL: tabelas TUSS do padrão TISS (ANS) -> formato do import_tuss do core.

Fonte (público, sem login):
`https://www.ans.gov.br/arquivos/extras/tiss/Padrao_TISS_Representacao_de_Conceitos_em_Saude_AAAAMM.zip`
(~413 MB). Liste a página do padrão TISS para a competência corrente — o slug
muda a cada release. Extraia só os XLSX que interessam:

    unzip -o -j Padrao_TISS_..._202607.zip "*TUSS 22*.xlsx" "*TUSS 18*.xlsx" \\
        "*TUSS 20*.xlsx" -d tiss/

Saída: CODIGO;DESCRICAO;GRUPO;SUBGRUPO;TABELA (UTF-8, ';').

Três tabelas entram, cada uma marcada em `TABELA`, que o importer grava em
`TUSSCode.table_number` — é o que a valoração CBHPM usa para separar um
procedimento de uma diária ou de um medicamento:

    22 → procedimentos e eventos em saúde
    18 → diárias, taxas e gases medicinais
    20 → medicamentos

`SUBGRUPO` sai vazio: as tabelas do TISS não publicam subgrupo. O código TUSS
tem estrutura hierárquica nos primeiros dígitos, mas deduzir subgrupo dele seria
inventar taxonomia que a ANS não afirma.

**Vigência.** Cada termo traz início/fim de vigência. Termos com fim de vigência
já passado estão revogados, e `import_tuss` grava `active=True` em tudo que
recebe — importá-los ressuscitaria código que não pode mais ser faturado. Então
são filtrados aqui, do mesmo jeito que os registros inativos da ANVISA.

**Sem openpyxl.** O XLSX é lido com `zipfile` + `ElementTree` da stdlib, como o
resto dos ETLs desta pasta (nenhum tem dependência externa, e openpyxl não está
instalado nem no host nem na imagem do django).

Pegadinhas da fonte, todas tratadas abaixo:
  * as linhas de cabeçalho variam de altura entre as tabelas (a T20 tem uma
    linha a mais de título), então o header é localizado pelo texto
    "Código do Termo", nunca por índice fixo;
  * a posição das colunas de data MUDA entre tabelas (na T20 entram
    Apresentação/Laboratório antes), então as colunas são resolvidas por NOME;
  * as datas vêm como serial numérico do Excel (ex. `39857`), não como texto;
  * o código do termo às vezes vem como número, perdendo o zero à esquerda —
    é normalizado de volta para 8 dígitos.

Roda no diretório que contém a pasta tiss/.
"""
import csv
import datetime
import re
import xml.etree.ElementTree as ET
import zipfile

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
# Serial do Excel: dias desde 1899-12-30 (o "bug" do ano 1900 já embutido).
EXCEL_EPOCH = datetime.date(1899, 12, 30)
HOJE_SERIAL = (datetime.date.today() - EXCEL_EPOCH).days

TABELAS = [
    ("22", "Procedimentos e eventos em saúde", "TUSS 22"),
    ("18", "Diárias, taxas e gases medicinais", "TUSS 18"),
    ("20", "Medicamentos", "TUSS 20"),
]


def _rows(path):
    """Devolve as linhas da última aba do XLSX como listas de (coluna, valor)."""
    z = zipfile.ZipFile(path)
    wb = z.read("xl/workbook.xml").decode("utf-8")
    rels = z.read("xl/_rels/workbook.xml.rels").decode("utf-8")
    rel_map = dict(re.findall(r'Id="(rId\d+)"[^>]*Target="([^"]+)"', rels))
    sheets = re.findall(r'<sheet[^>]*name="([^"]+)"[^>]*r:id="(rId\d+)"', wb)
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")):
            shared.append("".join(t.text or "" for t in si.iter(f"{NS}t")))
    # A aba de dados é a última; a primeira é sempre a CAPA.
    target = rel_map[sheets[-1][1]]
    if not target.startswith("xl/"):
        target = "xl/" + target.lstrip("/")
    for row in ET.fromstring(z.read(target)).iter(f"{NS}row"):
        vals = {}
        for c in row.iter(f"{NS}c"):
            col = "".join(ch for ch in (c.get("r") or "") if ch.isalpha())
            if c.get("t") == "inlineStr":
                is_el = c.find(f"{NS}is")
                v = "".join(x.text or "" for x in is_el.iter(f"{NS}t")) if is_el is not None else ""
            else:
                v_el = c.find(f"{NS}v")
                v = v_el.text if v_el is not None and v_el.text else ""
                if c.get("t") == "s" and v:
                    v = shared[int(v)]
            vals[col] = (v or "").strip()
        yield vals


def _find(header, *nomes):
    """Letra da coluna cujo cabeçalho casa com um dos nomes (case-insensitive)."""
    for col, txt in header.items():
        low = txt.lower()
        for n in nomes:
            if n in low:
                return col
    return None


out = []
seen = set()
resumo = []
for numero, grupo, prefixo in TABELAS:
    import glob

    matches = glob.glob(f"tiss/{prefixo}*.xlsx")
    if not matches:
        print(f"  ATENÇÃO — nenhum arquivo para {prefixo}, tabela {numero} ficou de fora")
        continue
    path = matches[0]
    header = None
    col_cod = col_desc = col_fim = None
    total = revogados = dup = 0
    for row in _rows(path):
        if header is None:
            if any("código do termo" in v.lower() for v in row.values()):
                header = row
                col_cod = _find(header, "código do termo")
                col_desc = _find(header, "termo")
                col_fim = _find(header, "fim de vigência")
                # "Termo" casaria com "Código do Termo"; garante colunas distintas.
                if col_desc == col_cod:
                    col_desc = _find({k: v for k, v in header.items() if k != col_cod}, "termo")
            continue
        code = row.get(col_cod, "")
        desc = row.get(col_desc, "")
        if not code or not desc:
            continue
        # Código puramente numérico perde o zero à esquerda no XLSX.
        if code.isdigit() and len(code) < 8:
            code = code.zfill(8)
        total += 1
        fim = row.get(col_fim, "") if col_fim else ""
        if fim.isdigit() and int(fim) < HOJE_SERIAL:
            revogados += 1
            continue
        if code in seen:
            dup += 1
            continue
        seen.add(code)
        out.append(
            {
                "CODIGO": code,
                "DESCRICAO": desc,
                "GRUPO": grupo,
                "SUBGRUPO": "",
                "TABELA": numero,
            }
        )
    resumo.append((numero, grupo, total, revogados, dup))

cols = ["CODIGO", "DESCRICAO", "GRUPO", "SUBGRUPO", "TABELA"]
with open("tuss_full.csv", "w", encoding="utf-8", newline="") as fh:
    fh.write("# TUSS — padrão TISS/ANS, tabelas 22/18/20 vigentes -> core.TUSSCode\n")
    w = csv.DictWriter(fh, fieldnames=cols, delimiter=";")
    w.writeheader()
    w.writerows(out)

print(f"hoje = serial Excel {HOJE_SERIAL}")
for numero, grupo, total, revogados, dup in resumo:
    print(f"tabela {numero} ({grupo}): {total} termos | revogados {revogados} | duplicados {dup}")
print(f"total vigente exportado: {len(out)}")
for r in out[:2]:
    print(" ", r["CODIGO"], "|", r["DESCRICAO"][:44], "| tab", r["TABELA"])
# spot-check: códigos TUSS de uso corrente
for want in ("10101012", "60015071"):
    hit = [r for r in out if r["CODIGO"] == want]
    print(f"  {want}:", f"{hit[0]['DESCRICAO'][:46]} (tab {hit[0]['TABELA']})" if hit else "AUSENTE")
