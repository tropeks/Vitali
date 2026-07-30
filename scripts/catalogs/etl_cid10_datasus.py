"""ETL: CSVs oficiais DATASUS (CID10CSV.zip) -> formato do import_cid10 do core.

Junta CAPITULOS + GRUPOS + CATEGORIAS + SUBCATEGORIAS numa unica tabela
CODIGO;DESCRICAO;CAPITULO;GRUPO;CATEGORIA;PARENT;SEXO;IDADE_MIN;IDADE_MAX;NOTIFICACAO
UTF-8, delimitador ';'. Fonte ISO-8859-1/CRLF.
"""
import csv

SRC_ENC = "iso-8859-1"


def read(path):
    with open(path, encoding=SRC_ENC, newline="") as fh:
        return list(csv.DictReader(fh, delimiter=";"))


def clean(s):
    return " ".join((s or "").split())


# Capitulos: NUMCAP;CATINIC;CATFIM;DESCRICAO;DESCRABREV
caps = [
    (r["CATINIC"], r["CATFIM"], clean(r["DESCRICAO"]))
    for r in read("CID-10-CAPITULOS.CSV")
]
# Grupos: CATINIC;CATFIM;DESCRICAO;DESCRABREV
grupos = [
    (r["CATINIC"], r["CATFIM"], clean(r["DESCRICAO"]))
    for r in read("CID-10-GRUPOS.CSV")
]


def find_range(code3, ranges):
    for ini, fim, desc in ranges:
        if ini <= code3 <= fim:
            return ini, fim, desc
    return None


def context_for(code3):
    """Return (chapter_str, group_str, category_str) for a 3-char category."""
    cap = find_range(code3, caps)
    grp = find_range(code3, grupos)
    chapter = cap[2] if cap else ""
    if grp:
        group = f"{grp[0]}-{grp[1]} {grp[2]}"
        category = f"{grp[0]}-{grp[1]}"
    else:
        group = ""
        category = ""
    return chapter, group, category


# Pre-compute context per 3-char category (used by both categories and subcats).
ctx_cache = {}


def ctx(code3):
    if code3 not in ctx_cache:
        ctx_cache[code3] = context_for(code3)
    return ctx_cache[code3]


# DATASUS RESTRSEXO usa 'F'/'M' direto (e por vezes 1/2 em exports antigos).
SEX_MAP = {"F": "F", "M": "M", "1": "M", "2": "F"}

# Dedupe por codigo: uma categoria de 3 chars sem subdivisao aparece nas DUAS
# tabelas (categorias + subcategorias). Mantemos um registro por codigo; a versao
# de subcategorias (que traz RESTRSEXO) complementa a de categorias.
by_code = {}

# Categorias (3-char): CAT;CLASSIF;DESCRICAO;DESCRABREV;REFER;EXCLUIDOS
for r in read("CID-10-CATEGORIAS.CSV"):
    code = (r["CAT"] or "").strip()
    if not code:
        continue
    chapter, group, category = ctx(code)
    by_code[code] = {
        "CODIGO": code,
        "DESCRICAO": clean(r["DESCRICAO"]),
        "CAPITULO": chapter,
        "GRUPO": group,
        "CATEGORIA": category,
        "PARENT": "",  # categoria e raiz sob o grupo
        "SEXO": "B",
        "IDADE_MIN": "",
        "IDADE_MAX": "",
        "NOTIFICACAO": "N",
    }

# Subcategorias: len 4 = subcategoria (parent = categoria de 3 chars);
# len 3 = categoria faturavel sem subdivisao (parent vazio, nao self).
for r in read("CID-10-SUBCATEGORIAS.CSV"):
    code = (r["SUBCAT"] or "").strip()
    if not code:
        continue
    parent = code[:3] if len(code) == 4 else ""
    chapter, group, category = ctx(code[:3])
    by_code[code] = {
        "CODIGO": code,
        "DESCRICAO": clean(r["DESCRICAO"]),
        "CAPITULO": chapter,
        "GRUPO": group,
        "CATEGORIA": category,
        "PARENT": parent,
        "SEXO": SEX_MAP.get((r.get("RESTRSEXO") or "").strip(), "B"),
        "IDADE_MIN": "",
        "IDADE_MAX": "",
        "NOTIFICACAO": "N",
    }

# Ordena: 3-char antes de 4-char, depois alfabetico (pais antes de filhos).
out = sorted(by_code.values(), key=lambda x: (len(x["CODIGO"]), x["CODIGO"]))

cols = ["CODIGO", "DESCRICAO", "CAPITULO", "GRUPO", "CATEGORIA", "PARENT",
        "SEXO", "IDADE_MIN", "IDADE_MAX", "NOTIFICACAO"]
with open("cid10_full.csv", "w", encoding="utf-8", newline="") as fh:
    fh.write("# CID-10 DATASUS V2008 (CID10CSV.zip) — ETL para core.CID10Code\n")
    w = csv.DictWriter(fh, fieldnames=cols, delimiter=";")
    w.writeheader()
    w.writerows(out)

print(f"linhas: {len(out)}")
print(f"categorias(3): {sum(1 for r in out if len(r['CODIGO']) == 3)}")
print(f"subcategorias(4): {sum(1 for r in out if len(r['CODIGO']) == 4)}")
print(f"sexo M: {sum(1 for r in out if r['SEXO'] == 'M')} / F: {sum(1 for r in out if r['SEXO'] == 'F')}")
# amostra
for r in out[:2] + [x for x in out if x['CODIGO'] == 'A000'][:1]:
    print(r["CODIGO"], "|", r["DESCRICAO"][:40], "|", r["CAPITULO"][:30], "|", r["GRUPO"][:30], "|", r["CATEGORIA"], "|", r["PARENT"], "|", r["SEXO"])
