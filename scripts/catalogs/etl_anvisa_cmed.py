"""ETL: lista de preços CMED (ANVISA) -> formato do import_anvisa_cmed do core.

Fonte (público, sem login):
`https://dados.anvisa.gov.br/dados/TA_PRECO_MEDICAMENTO.csv`
(`;`-delimitado, **ISO-8859-1**; certificado inválido, use `curl -k`.)

Saída: REGISTRO;REGISTRO_PRODUTO;APRESENTACAO;EAN;PF;PMC (UTF-8, ';').

Esta é a fonte que **completa** o `etl_anvisa.py`: o dado aberto de medicamentos
é por produto e não publica código de barras nenhum, enquanto a CMED publica EAN
e preço por apresentação. Sem isso, `AnvisaProduct.by_ean` — o casamento de
linha de NF-e com o catálogo — nunca acha nada.

Chave: `REGISTRO` da CMED tem **13 dígitos = 9 do produto + 4 da apresentação**.
`REGISTRO_PRODUTO` são os 9 primeiros, que é como o dado aberto de medicamentos
identifica o produto. Na competência 202608, 8.223 dos 10.276 produtos ativos
casam por esse prefixo (~80%); o resto são apresentações cujo produto está
inativo ou sem registro no outro dataset, e o importer as reporta como órfãs em
vez de inventar o produto.

Pegadinhas da fonte, todas tratadas abaixo:
  * o cabeçalho real está na **linha 42** (as anteriores são título//notas da
    CMED), então é localizado pelo texto "REGISTRO", nunca por índice fixo;
  * EAN ausente vem como `    -     ` (traços e espaços), não vazio;
  * preços usam vírgula decimal e ponto de milhar (`1.234,56`);
  * a coluna TARJA existe, mas **não é importada**: a CMED classifica em
    "Tarja Vermelha/Preta/Sem Tarja", enquanto `AnvisaProduct.controlled_class`
    quer a lista da Portaria 344/98 (A1, A2, B1, C1…). O mapeamento não é 1:1
    (tarja preta cobre A1/A2/A3/B1/B2) e errar a lista de um controlado é dado
    clínico perigoso.

Limite conhecido: só o **EAN 1** é guardado. `AnvisaPresentation` tem um campo de
EAN e a chave é o registro de 13 dígitos, que é fato da fonte. EAN 1 está
preenchido em 25.701 das 25.702 apresentações; EAN 2 aparece em 1.129 (4%) e
EAN 3 em 59 (0,2%) — uma NF-e que traga um desses códigos alternativos não casa.

Roda no diretório onde está TA_PRECO_MEDICAMENTO.csv.
"""
import csv
import sys

SRC = sys.argv[1] if len(sys.argv) > 1 else "cmed_precos.csv"

csv.field_size_limit(10 * 1024 * 1024)


def _limpo(v):
    """Campo da CMED -> string. Marcadores de ausência viram vazio."""
    v = (v or "").strip()
    return "" if not v or set(v) <= {"-", "*", "(", ")", " "} else v


def _num(v):
    """Preço da CMED -> string decimal com ponto. Vazio continua vazio."""
    v = _limpo(v)
    return v.replace(".", "").replace(",", ".") if v else ""


with open(SRC, encoding="latin-1", newline="") as fh:
    linhas = list(csv.reader(fh, delimiter=";"))

# O cabeçalho não está na linha 1 — a CMED põe título e notas antes.
idx_header = None
for i, row in enumerate(linhas):
    if any((c or "").strip().upper() == "REGISTRO" for c in row):
        idx_header = i
        break
if idx_header is None:
    raise SystemExit("ERRO: cabeçalho com coluna REGISTRO não encontrado — layout da CMED mudou.")

header = [(c or "").strip().upper() for c in linhas[idx_header]]


def col(*nomes):
    for n in nomes:
        if n in header:
            return header.index(n)
    return None


c_reg, c_ean, c_apr = col("REGISTRO"), col("EAN 1", "EAN1"), None
for i, h in enumerate(header):
    if h.startswith("APRESENTA"):
        c_apr = i
        break
c_pf = next((i for i, h in enumerate(header) if h.startswith("PF SEM IMPOSTO")), None)
c_pmc = next((i for i, h in enumerate(header) if h.startswith("PMC SEM IMPOSTO")), None)
if c_reg is None or c_ean is None:
    raise SystemExit(f"ERRO: colunas REGISTRO/EAN 1 não encontradas. Header: {header[:12]}")

out = []
seen = set()
sem_registro = registro_curto = 0
for row in linhas[idx_header + 1 :]:
    if len(row) <= c_reg:
        continue
    registro = "".join(ch for ch in _limpo(row[c_reg]) if ch.isdigit())
    if not registro:
        sem_registro += 1
        continue
    if len(registro) < 13:
        registro_curto += 1
        continue
    if registro in seen:
        continue
    seen.add(registro)
    out.append(
        {
            "REGISTRO": registro,
            "REGISTRO_PRODUTO": registro[:9],
            "APRESENTACAO": _limpo(row[c_apr]) if c_apr is not None else "",
            "EAN": "".join(ch for ch in _limpo(row[c_ean]) if ch.isdigit()),
            "PF": _num(row[c_pf]) if c_pf is not None else "",
            "PMC": _num(row[c_pmc]) if c_pmc is not None else "",
        }
    )

cols = ["REGISTRO", "REGISTRO_PRODUTO", "APRESENTACAO", "EAN", "PF", "PMC"]
with open("anvisa_cmed_full.csv", "w", encoding="utf-8", newline="") as fh:
    fh.write("# CMED lista de preços (ANVISA) -> core.AnvisaPresentation\n")
    w = csv.DictWriter(fh, fieldnames=cols, delimiter=";")
    w.writeheader()
    w.writerows(out)

print(f"cabeçalho encontrado na linha {idx_header + 1}")
print(f"apresentações: {len(out)}")
print(f"  descartadas — sem registro: {sem_registro} | registro com menos de 13 díg: {registro_curto}")
print(f"  com EAN: {sum(1 for r in out if r['EAN'])}")
print(f"  com preço de fábrica: {sum(1 for r in out if r['PF'])}")
print(f"  produtos distintos referenciados: {len({r['REGISTRO_PRODUTO'] for r in out})}")
for r in out[:3]:
    print(" ", r["REGISTRO"], "| prod", r["REGISTRO_PRODUTO"], "|", r["APRESENTACAO"][:30], "| EAN", r["EAN"], "| PF", r["PF"])
