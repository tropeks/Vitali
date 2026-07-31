"""ETL: CID-O-CATEGORIAS.CSV (DATASUS, morfologia) -> import_cido do core.

Fonte: mesmo CID10CSV.zip (arquivo CID-O-CATEGORIAS.CSV; colunas CAT;DESCRICAO;REFER,
ISO-8859-1). O código vem como "M8000/0"; armazenamos sem o prefixo "M" (padrão
clínico "8000/0"). Comportamento = dígito após "/". REFER = CID-10 correlato.
Saída: CODIGO;TITULO;COMPORTAMENTO;CID10_REF (UTF-8, ';').
Roda no diretório onde está CID-O-CATEGORIAS.CSV.
"""
import csv

out = []
with open("CID-O-CATEGORIAS.CSV", encoding="iso-8859-1", newline="") as fh:
    for r in csv.DictReader(fh, delimiter=";"):
        raw = (r["CAT"] or "").strip()
        desc = " ".join((r["DESCRICAO"] or "").split())
        if not raw or not desc:
            continue
        code = raw[1:] if raw.upper().startswith("M") else raw  # tira prefixo M
        behaviour = code.rsplit("/", 1)[-1][:1] if "/" in code else ""
        out.append({
            "CODIGO": code,
            "TITULO": desc,
            "COMPORTAMENTO": behaviour,
            "CID10_REF": (r.get("REFER") or "").strip(),
        })

cols = ["CODIGO", "TITULO", "COMPORTAMENTO", "CID10_REF"]
with open("cido_full.csv", "w", encoding="utf-8", newline="") as fh:
    fh.write("# CID-O morfologia DATASUS (CID10CSV.zip) -> core.CIDOMorphology\n")
    w = csv.DictWriter(fh, fieldnames=cols, delimiter=";")
    w.writeheader()
    w.writerows(out)

from collections import Counter
print(f"morfologias: {len(out)}")
print("comportamento:", Counter(r["COMPORTAMENTO"] for r in out))
print("com CID-10 correlato:", sum(1 for r in out if r["CID10_REF"]))
for want in ("8500/3", "9732/3", "8000/0"):
    ex = [r for r in out if r["CODIGO"] == want]
    if ex:
        r = ex[0]
        print(f"  {r['CODIGO']}: {r['TITULO'][:40]!r} comp={r['COMPORTAMENTO']} ref={r['CID10_REF']}")
