"""ETL: ucum-essence.xml (UCUM oficial) -> formato do import_ucum do core.

Fonte: https://raw.githubusercontent.com/ucum-org/ucum/main/ucum-essence.xml
(XML canônico do Unified Code for Units of Measure, namespace
`http://unitsofmeasure.org/ucum-essence`; a versão fica no atributo `version`
do elemento raiz).

Saída: UCUM_CODE;DISPLAY (UTF-8, ';').

`UCUM_CODE` sai do atributo **`Code`** (case-sensitive, o que a especificação
chama de "print/case-sensitive code" — ex `mg`, `mmol/L`, `Cel`), NUNCA do
`CODE` maiúsculo (a variante case-INsensitive, ex `MG`, `CEL`): o modelo
`core.UcumUnit` é chaveado no símbolo case-sensitive, e usar a outra coluna
colapsaria `mg` com `Mg` e quebraria a unicidade.

Cobre `<base-unit>` (as 7 unidades de base do SI) e `<unit>` (as derivadas e
não-métricas). Prefixos (`<prefix>`: k, m, µ…) NÃO são unidades e ficam de fora
— eles se combinam com unidades em tempo de uso (`mg` já vem no catálogo).

Roda no diretório onde está ucum-essence.xml.
"""
import csv
import xml.etree.ElementTree as ET

NS = "{http://unitsofmeasure.org/ucum-essence}"

tree = ET.parse("ucum-essence.xml")
root = tree.getroot()
version = (root.get("version") or "").strip()

out = []
seen = set()
for tag in ("base-unit", "unit"):
    for el in root.findall(f"{NS}{tag}"):
        # Atributo `Code` = símbolo case-sensitive. Ver docstring.
        code = (el.get("Code") or "").strip()
        name_el = el.find(f"{NS}name")
        display = (name_el.text or "").strip() if name_el is not None else ""
        if not code or not display or code in seen:
            continue
        seen.add(code)
        out.append({"UCUM_CODE": code, "DISPLAY": display})

with open("ucum_full.csv", "w", encoding="utf-8", newline="") as fh:
    fh.write(f"# UCUM {version} (ucum-essence.xml oficial) -> core.UcumUnit\n")
    w = csv.DictWriter(fh, fieldnames=["UCUM_CODE", "DISPLAY"], delimiter=";")
    w.writeheader()
    w.writerows(out)

print(f"versão UCUM: {version}")
print(f"unidades: {len(out)}")
for r in out[:3]:
    print(" ", r["UCUM_CODE"], "|", r["DISPLAY"][:50])
# spot-check: unidades que o LIS usa de fato
for want in ("mg", "mmol/L", "Cel", "g/dL", "U/L", "10*3/uL"):
    hit = [r for r in out if r["UCUM_CODE"] == want]
    print(f"  {want!r}:", hit[0]["DISPLAY"][:45] if hit else "AUSENTE (derivada por prefixo/anotação)")
