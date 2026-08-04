"""ETL: DADOS_ABERTOS_MEDICAMENTOS (ANVISA) -> formato do import_anvisa do core.

Fonte (público, sem login):
`https://dados.anvisa.gov.br/dados/DADOS_ABERTOS_MEDICAMENTOS.csv`
(`;`-delimitado, **ISO-8859-1** — NÃO é UTF-8, decodificar como latin-1 ou o
parse estoura em `0xca`; o certificado do host é inválido, `curl -k`.)

Colunas da fonte: TIPO_PRODUTO;NOME_PRODUTO;DATA_FINALIZACAO_PROCESSO;
CATEGORIA_REGULATORIA;NUMERO_REGISTRO_PRODUTO;DATA_VENCIMENTO_REGISTRO;
NUMERO_PROCESSO;CLASSE_TERAPEUTICA;EMPRESA_DETENTORA_REGISTRO;
SITUACAO_REGISTRO;PRINCIPIO_ATIVO

Saída: REGISTRO;PRODUTO;DCB;APRESENTACAO;EAN;CLASSE_TERAPEUTICA;TARJA
(UTF-8, ';').

Duas exclusões deliberadas, ambas por fidelidade à fonte:

1. **Só `SITUACAO_REGISTRO == "Ativo"`.** O `AnvisaImporter.build_defaults`
   grava `active=True` em tudo que passa; importar os 26.146 registros
   `Inativo` os marcaria como ativos no catálogo — uma inversão do dado, não
   uma cópia dele. Filtrar aqui é o que preserva a verdade da fonte.
2. **Só linhas com `NUMERO_REGISTRO_PRODUTO` preenchido.** ~6.978 medicamentos
   ativos (notificados/baixo risco) não têm número de registro; o modelo é
   chaveado nele e o importer aborta em código vazio (fail-loud).

`APRESENTACAO`, `EAN` e `TARJA` saem **vazios de propósito**: o dataset aberto
de medicamentos não traz apresentação, código de barras nem tarja/lista da
Portaria 344. Ficam nos defaults inertes do importer em vez de serem inventados
— tarja errada em medicamento controlado é dado clínico perigoso.

Roda no diretório onde está DADOS_ABERTOS_MEDICAMENTOS.csv (renomeado ou não).
"""
import csv
import sys

SRC = sys.argv[1] if len(sys.argv) > 1 else "anvisa_medicamentos.csv"

with open(SRC, encoding="latin-1", newline="") as fh:
    rows = list(csv.DictReader(fh, delimiter=";"))

out = []
seen = set()
skipped_inativo = 0
skipped_sem_registro = 0
for r in rows:
    registro = (r.get("NUMERO_REGISTRO_PRODUTO") or "").strip()
    produto = (r.get("NOME_PRODUTO") or "").strip()
    if (r.get("SITUACAO_REGISTRO") or "").strip() != "Ativo":
        skipped_inativo += 1
        continue
    if not registro:
        skipped_sem_registro += 1
        continue
    if not produto or registro in seen:
        continue
    seen.add(registro)
    out.append(
        {
            "REGISTRO": registro,
            "PRODUTO": produto,
            "DCB": (r.get("PRINCIPIO_ATIVO") or "").strip(),
            "APRESENTACAO": "",
            "EAN": "",
            "CLASSE_TERAPEUTICA": (r.get("CLASSE_TERAPEUTICA") or "").strip(),
            "TARJA": "",
        }
    )

cols = ["REGISTRO", "PRODUTO", "DCB", "APRESENTACAO", "EAN", "CLASSE_TERAPEUTICA", "TARJA"]
with open("anvisa_full.csv", "w", encoding="utf-8", newline="") as fh:
    fh.write("# ANVISA dados abertos de medicamentos (só registros Ativos) -> core.AnvisaProduct\n")
    w = csv.DictWriter(fh, fieldnames=cols, delimiter=";")
    w.writeheader()
    w.writerows(out)

print(f"linhas na fonte: {len(rows)}")
print(f"  descartadas — situação != Ativo: {skipped_inativo}")
print(f"  descartadas — sem nº de registro: {skipped_sem_registro}")
print(f"medicamentos ativos: {len(out)}")
sem_dcb = sum(1 for r in out if not r["DCB"])
sem_classe = sum(1 for r in out if not r["CLASSE_TERAPEUTICA"])
print(f"  sem princípio ativo: {sem_dcb} | sem classe terapêutica: {sem_classe}")
for r in out[:3]:
    print(" ", r["REGISTRO"], "|", r["PRODUTO"][:28], "|", r["DCB"][:30], "|", r["CLASSE_TERAPEUTICA"][:22])
# spot-check: princípios ativos de uso hospitalar corriqueiro
for want in ("dipirona", "amoxicilina", "omeprazol"):
    hit = [r for r in out if want in r["DCB"].lower()]
    print(f"  {want}: {len(hit)} registros", f"(ex {hit[0]['REGISTRO']} {hit[0]['PRODUTO'][:24]})" if hit else "")
