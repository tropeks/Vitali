# -*- coding: utf-8 -*-
"""Extrai a tabela da CBHPM (PDF da AMB) para o CSV que `import_cbhpm` consome.

Entrada: a saida de `pdftotext -layout` sobre o PDF da CBHPM.
Saida:   CSV `;` no formato do importador, e um arquivo de quarentena.

    pdftotext -layout CBHPM-2022.pdf cbhpm.txt
    python3 scripts/catalogs/etl_cbhpm_pdf.py cbhpm.txt cbhpm.csv quarentena.txt

LICENCA: a CBHPM e obra da AMB/Editora Manole, "todos os direitos reservados".
Este script NAO distribui a tabela — ele le um PDF que voce ja tem o direito de
usar. Rodar isto nao substitui a licenca.

O QUE ESTE ARQUIVO SABE, e custou achar:

1. OITO layouts de tabela, que mudam por capitulo. O cabecalho reaparece em toda
   pagina e e ele que diz quais colunas valem. Quem ignorar isso le "numero de
   auxiliares" onde esta "porte anestesico".

2. O PORTE pode ocupar TRES tokens: "0,01 de 1A" — fracao da classe 1A, a forma
   usada em toda a Medicina Laboratorial. Medido na edicao 2022 rev. ago/2023:
   1.046 linhas assim. Ler so o "1A" infla o porte de 25 a 100 vezes.

3. Codigo terminado em ".00-N" e cabecalho de SECAO, nao procedimento.

4. A CBHPM imprime 3.02.08.15-7 DUAS vezes, com dados identicos. Repeticao com
   dados identicos e deduplicada; com dados diferentes vai para a quarentena —
   nunca "o ultimo que escreveu ganha".

Nada e adivinhado: porte fora do vocabulario da CBHPM sai em quarentena, nunca
com valor inventado (INTENT §Limites).
"""
import csv, re, sys, unicodedata

TXT, OUT, QUAR = sys.argv[1], sys.argv[2], sys.argv[3]

RE_CODIGO = re.compile(r"^\s*(\d\.\d{2}\.\d{2}\.\d{2}-\d)\s+(.*)$")
RE_CAB    = re.compile(r"^\s*C.digo\s+Procedimento(.*)$")
RE_PORTE  = re.compile(r"^(?:\d{1,2}[ABC]?|[0-9]+,[0-9]+ de \d{1,2}[ABC]?|[\u2013\u2014-])$")
RE_VALOR  = re.compile(r"^(?:[\d.]*\d(?:,\d+)?|[-–—])$")

def normaliza(s):
    return unicodedata.normalize("NFKD", s).encode("ascii","ignore").decode().lower()

def colunas_do_cabecalho(anterior, cabecalho):
    """Traduz o par (linha de cima, linha do Codigo) na lista de colunas."""
    j = normaliza(anterior + " " + cabecalho)
    cols = ["porte"]
    if "oper" in j: cols.append("valor_ch")          # Custo Oper. = UCO
    if "filme" in j or "doc" in j: cols.append("numero_filme")
    if "incid" in j: cols.append("incidencias")
    if "ur" in re.findall(r"\bur\b", j): cols.append("ur")
    if "aux" in j: cols.append("numero_auxiliares")
    if "anest" in j: cols.append("porte_anestesico")
    return cols

linhas = open(TXT, encoding="utf-8").read().split("\n")
cols = ["porte"]
linhas_saida, quarentena = [], []
vistos = {}

i = 0
while i < len(linhas):
    l = linhas[i]
    if RE_CAB.match(l):
        cols = colunas_do_cabecalho(linhas[i-1] if i else "", l)
        i += 1; continue
    m = RE_CODIGO.match(l)
    if not m:
        i += 1; continue
    codigo, resto = m.group(1), m.group(2).rstrip()
    # Codigo terminado em ".00-N" e CABECALHO DE SECAO ("MEDICINA LABORATORIAL
    # 4.03.00.00-5"), nao procedimento. Um deles arrastava um bloco inteiro de
    # OBSERVACOES para dentro da descricao, e o importador recusou a linha ao
    # tentar ler "CARDIOLOGIA" como decimal — achado no dry-run das 4.883.
    if re.search(r"\.00-\d$", codigo):
        i += 1
        continue
    partes = resto.split()
    n = len(cols)
    if len(partes) <= n:
        quarentena.append((codigo, resto, "colunas insuficientes")); i += 1; continue
    # O PORTE e a PRIMEIRA coluna do grupo final, e na Medicina Laboratorial ele
    # ocupa TRES tokens: "0,01 de 1A" — fracao do porte 1A. Popar n tokens da
    # direita levaria so "1A" e empurraria "0,01 de" para dentro da descricao,
    # inflando o porte de 25 a 100 vezes. Medido no PDF: 1.045 linhas assim, 943
    # extraidas erradas na primeira versao — achadas pela prova dos 20 codigos.
    # Entao: tira primeiro as n-1 colunas DEPOIS do porte, e so entao decide se
    # o porte tem um token ou tres.
    posteriores = partes[-(n - 1):] if n > 1 else []
    resto_esq = partes[:-(n - 1)] if n > 1 else list(partes)
    if (len(resto_esq) >= 3 and resto_esq[-2] == "de"
            and re.match(r"^[0-9]+,[0-9]+$", resto_esq[-3])):
        porte = " ".join(resto_esq[-3:])
        descricao = " ".join(resto_esq[:-3]).strip()
    else:
        porte = resto_esq[-1] if resto_esq else ""
        descricao = " ".join(resto_esq[:-1]).strip()
    valores = [porte] + posteriores
    # continuacao: proxima linha sem codigo, sem cabecalho, nao vazia e nao rodape
    j = i + 1
    while j < len(linhas):
        s = linhas[j].strip()
        if not s or RE_CODIGO.match(linhas[j]) or RE_CAB.match(linhas[j]): break
        if re.match(r"^(CBHPM|\d+\s*$|Edicao|EDICAO)", s): break
        # Continuacao de UMA palavra existe e e legitima ("Fluxo", "Schilling)").
        # O que NAO e continuacao e cabecalho de secao: caixa alta, ou carregando
        # um codigo de secao. Rejeitar por "tem uma palavra so" cortava descricao
        # no meio — achado na conferencia contra o PDF (4.04.03.08-4, 4.07.05.06-4).
        if s.isupper() or re.search(r"\d\.\d{2}\.\d{2}\.\d{2}-\d", s): break
        descricao += " " + s
        j += 1
    if not RE_PORTE.match(valores[0]):
        quarentena.append((codigo, resto, f"porte nao reconhecido: {valores[0]!r}")); i = j; continue
    if not descricao or descricao.isupper() and len(descricao) < 15:
        quarentena.append((codigo, resto, "descricao vazia/suspeita")); i = j; continue
    linha = {"CODIGO": codigo, "DESCRICAO": descricao}
    for nome, v in zip(cols, valores):
        linha[nome] = v
    ja = vistos.get(codigo)
    if ja is not None:
        if ja != linha:
            quarentena.append((codigo, resto, "codigo repetido com dados DIFERENTES"))
        i = j
        continue
    vistos[codigo] = linha
    linhas_saida.append(linha)
    i = j

def limpa(v):
    return "" if v in (None,"-","–","—") else v

with open(OUT,"w",newline="",encoding="utf-8") as f:
    w = csv.writer(f, delimiter=";")
    w.writerow(["CODIGO","DESCRICAO","PORTE","VALOR_CH","PORTE_ANESTESICO","NUMERO_FILME","NUMERO_AUXILIARES","VIGENCIA"])
    for r in linhas_saida:
        w.writerow([r["CODIGO"], r["DESCRICAO"], limpa(r.get("porte")), limpa(r.get("valor_ch")),
                    limpa(r.get("porte_anestesico")), limpa(r.get("numero_filme")),
                    limpa(r.get("numero_auxiliares")), "CBHPM 2022 rev. ago/2023"])

with open(QUAR,"w",encoding="utf-8") as f:
    for c,r,m in quarentena: f.write(f"{c}\t{m}\t{r[:90]}\n")

print("extraidas:", len(linhas_saida))
print("quarentena:", len(quarentena))
