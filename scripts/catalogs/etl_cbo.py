"""ETL: lista canônica CBO-2002 -> formato do import_cbo do core.

Fonte: https://raw.githubusercontent.com/datasets-br/cbo/master/data/lista_canonicos.csv
(colunas `codigo,termo`; código no formato família-ocupação, ex "8485-05").
Saída: CODIGO;TITULO;FAMILIA (UTF-8, ';'), família = 4 primeiros dígitos.
Roda no diretório onde está lista_canonicos.csv.
"""
import csv

with open("lista_canonicos.csv", encoding="utf-8", newline="") as fh:
    rows = list(csv.DictReader(fh))

out = []
seen = set()
for r in rows:
    raw = (r["codigo"] or "").strip()
    termo = (r["termo"] or "").strip()
    code = raw.replace("-", "").replace(".", "")
    if not code or not termo or code in seen:
        continue
    seen.add(code)
    out.append({"CODIGO": code, "TITULO": termo, "FAMILIA": code[:4]})

with open("cbo_full.csv", "w", encoding="utf-8", newline="") as fh:
    fh.write("# CBO-2002 (datasets-br/cbo, lista canônica) -> core.CBOCode\n")
    w = csv.DictWriter(fh, fieldnames=["CODIGO", "TITULO", "FAMILIA"], delimiter=";")
    w.writeheader()
    w.writerows(out)

print(f"ocupações: {len(out)}")
fams = {r["FAMILIA"] for r in out}
print(f"famílias distintas: {len(fams)}")
for r in out[:3]:
    print(" ", r["CODIGO"], "|", r["TITULO"][:40], "| fam", r["FAMILIA"])
# spot-check: médico clínico 2251xx, enfermeiro 2235xx
for want in ("2251", "2235"):
    ex = [r for r in out if r["FAMILIA"] == want][:2]
    print(f"  família {want}:", [(r["CODIGO"], r["TITULO"][:30]) for r in ex])
