"""ETL: BASE_DE_DADOS_CNES (DATASUS) -> formato do import_cnes do core.

Fonte (público, FTP DATASUS):
`ftp://ftp.datasus.gov.br/cnes/BASE_DE_DADOS_CNES_AAAAMM.ZIP` (~730 MB; liste o
diretório para a competência mais recente). Deste ZIP só interessam dois
membros — extraia só eles, o pacote inteiro descompactado passa de 3 GB:

    unzip -o BASE_DE_DADOS_CNES_202606.ZIP \\
        "tbEstabelecimento202606.csv" "tbTipoUnidade202606.csv" -d cnes/

Ambos `;`-delimitados, com aspas, **ISO-8859-1** (não UTF-8).

Saída: CNES;NOME;TIPO;MUNICIPIO_IBGE;ATIVO (UTF-8, ';').

Mapeamento:
  CNES           <- CO_CNES
  NOME           <- NO_FANTASIA, caindo para NO_RAZAO_SOCIAL quando vazio (29
                    estabelecimentos ativos não têm nome fantasia)
  TIPO           <- DS_TIPO_UNIDADE, resolvido de TP_UNIDADE via
                    tbTipoUnidade (a coluna CO_TIPO_UNIDADE do arquivo de
                    estabelecimentos vem **inteiramente vazia** na competência
                    202606 — é TP_UNIDADE que carrega o código de fato)
  MUNICIPIO_IBGE <- CO_MUNICIPIO_GESTOR
  ATIVO          <- 0 quando CO_MOTIVO_DESAB está preenchido, senão 1

Sobre MUNICIPIO_IBGE: o DATASUS entrega o código do município com **6 dígitos**
(sem o dígito verificador do IBGE) e é assim que ele é gravado. O DV não é
calculado aqui: seria fabricar dado, e o campo não é chave de junção com
nenhuma outra tabela do sistema — só é exposto na API de terminologia.

Estabelecimentos desabilitados NÃO são descartados: entram com ATIVO=0, que o
`CNESImporter` respeita (`active` sai da linha, não é forçado). O catálogo
guarda a baixa em vez de fingir que o estabelecimento nunca existiu, e a busca
de terminologia filtra por ativo.

Roda no diretório que contém a pasta cnes/ (ou passe o sufixo da competência).
"""
import csv
import sys

COMP = sys.argv[1] if len(sys.argv) > 1 else "202606"
EST = f"cnes/tbEstabelecimento{COMP}.csv"
TIPOS = f"cnes/tbTipoUnidade{COMP}.csv"

# csv default é 128 KB por campo; linhas do CNES têm campos livres longos.
csv.field_size_limit(10 * 1024 * 1024)

with open(TIPOS, encoding="latin-1", newline="") as fh:
    tipos = {
        (r["CO_TIPO_UNIDADE"] or "").strip().lstrip("0"): (r["DS_TIPO_UNIDADE"] or "").strip()
        for r in csv.DictReader(fh, delimiter=";")
    }

out = []
seen = set()
sem_nome = 0
sem_tipo = set()
inativos = 0
with open(EST, encoding="latin-1", newline="") as fh:
    for r in csv.DictReader(fh, delimiter=";"):
        code = (r.get("CO_CNES") or "").strip()
        nome = (r.get("NO_FANTASIA") or "").strip() or (r.get("NO_RAZAO_SOCIAL") or "").strip()
        if not code or code in seen:
            continue
        if not nome:
            sem_nome += 1
            continue
        seen.add(code)
        tp = (r.get("TP_UNIDADE") or "").strip().lstrip("0")
        desc = tipos.get(tp, "")
        if tp and not desc:
            sem_tipo.add(tp)
        ativo = "0" if (r.get("CO_MOTIVO_DESAB") or "").strip() else "1"
        if ativo == "0":
            inativos += 1
        out.append(
            {
                "CNES": code,
                "NOME": nome,
                "TIPO": desc,
                "MUNICIPIO_IBGE": (r.get("CO_MUNICIPIO_GESTOR") or "").strip(),
                "ATIVO": ativo,
            }
        )

cols = ["CNES", "NOME", "TIPO", "MUNICIPIO_IBGE", "ATIVO"]
with open("cnes_full.csv", "w", encoding="utf-8", newline="") as fh:
    fh.write(f"# CNES {COMP} (BASE_DE_DADOS_CNES DATASUS) -> core.CNESEstablishment\n")
    w = csv.DictWriter(fh, fieldnames=cols, delimiter=";")
    w.writeheader()
    w.writerows(out)

print(f"competência: {COMP}")
print(f"estabelecimentos: {len(out)}  (ativos {len(out) - inativos} | desabilitados {inativos})")
print(f"  descartados por não ter nome nenhum: {sem_nome}")
if sem_tipo:
    print(f"  ATENÇÃO — TP_UNIDADE sem correspondência em tbTipoUnidade: {sorted(sem_tipo)}")
sem_desc = sum(1 for r in out if not r["TIPO"])
print(f"  sem descrição de tipo: {sem_desc}")
for r in out[:3]:
    print(" ", r["CNES"], "|", r["NOME"][:32], "|", r["TIPO"][:28], "| mun", r["MUNICIPIO_IBGE"])
# spot-check: hospitais de referência que têm de estar no catálogo
for want in ("HOSPITAL DAS CLINICAS", "INCA", "SIRIO LIBANES"):
    hit = [r for r in out if want in r["NOME"].upper()][:1]
    print(f"  {want}:", f"{hit[0]['CNES']} {hit[0]['NOME'][:38]}" if hit else "não encontrado")
