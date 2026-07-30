"""ETL: SIGTAP tb_procedimento.txt (posicional, DATASUS) -> import_sigtap do core.

Fonte: ftp://ftp2.datasus.gov.br/public/sistemas/tup/downloads/TabelaUnificada_AAAAMM_vNNN.zip
(arquivo tb_procedimento.txt, ISO-8859-1/CRLF, layout fixo em tb_procedimento_layout.txt).
Saída: CODIGO;PROCEDIMENTO;VALOR_SA;VALOR_SH;VALOR_SP;COMPETENCIA;COMPLEXIDADE;FINANCIAMENTO;SEXO
(valores convertidos de centavos p/ reais; complexidade e sexo mapeados p/ os enums do model).
Idade e instrumento ficam vazios (unidade/tabela não presentes no tb_procedimento — não fabricar).
Roda no diretório onde está tb_procedimento.txt.
"""
import csv

# Slices 0-indexed do layout tb_procedimento_layout.txt.
SL = {
    "code": (0, 10),
    "name": (10, 260),
    "complex": (260, 261),
    "sex": (261, 262),
    "vl_sh": (282, 294),
    "vl_sa": (294, 306),
    "vl_sp": (306, 318),
    "financ": (318, 320),
    "competencia": (330, 336),
}

COMPLEX_MAP = {"0": "nao_se_aplica", "1": "atencao_basica", "2": "media", "3": "alta"}
SEX_MAP = {"M": "M", "F": "F"}


def cents_to_reais(raw):
    v = int((raw or "0").strip() or "0")
    return f"{v // 100}.{v % 100:02d}"


out = []
with open("tb_procedimento.txt", encoding="iso-8859-1", newline="") as fh:
    for line in fh:
        line = line.rstrip("\r\n")
        if len(line) < 336:
            continue

        def f(key):
            a, b = SL[key]
            return line[a:b].strip()

        code = f("code")
        name = " ".join(f("name").split())
        if not code or not name:
            continue
        out.append({
            "CODIGO": code,
            "PROCEDIMENTO": name,
            "VALOR_SA": cents_to_reais(f("vl_sa")),
            "VALOR_SH": cents_to_reais(f("vl_sh")),
            "VALOR_SP": cents_to_reais(f("vl_sp")),
            "COMPETENCIA": f("competencia"),
            "COMPLEXIDADE": COMPLEX_MAP.get(f("complex"), "nao_se_aplica"),
            "FINANCIAMENTO": f("financ"),
            "SEXO": SEX_MAP.get(f("sex"), ""),
        })

cols = ["CODIGO", "PROCEDIMENTO", "VALOR_SA", "VALOR_SH", "VALOR_SP",
        "COMPETENCIA", "COMPLEXIDADE", "FINANCIAMENTO", "SEXO"]
with open("sigtap_full.csv", "w", encoding="utf-8", newline="") as fh:
    fh.write("# SIGTAP TabelaUnificada tb_procedimento -> core.SIGTAPProcedure\n")
    w = csv.DictWriter(fh, fieldnames=cols, delimiter=";")
    w.writeheader()
    w.writerows(out)

from collections import Counter
print(f"procedimentos: {len(out)}")
print("complexidade:", Counter(r["COMPLEXIDADE"] for r in out))
print("sexo:", Counter(r["SEXO"] for r in out))
for want in ("0303010010", "0101010010"):
    ex = [r for r in out if r["CODIGO"] == want]
    if ex:
        r = ex[0]
        print(f"  {r['CODIGO']}: {r['PROCEDIMENTO'][:38]!r} SH={r['VALOR_SH']} SA={r['VALOR_SA']} SP={r['VALOR_SP']} {r['COMPLEXIDADE']}")
