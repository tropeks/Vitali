# Catálogos governados — import de fontes oficiais

O motor de import (`core.terminology_base.CatalogImporter`) e os management
commands (`import_cid10`, `import_sigtap`, `import_cbo`, …) já existem e são
idempotentes (upsert por código, log de proveniência, `--dry-run`). O que estes
scripts fazem é o **ETL**: baixar a fonte oficial e transformá-la no CSV
`;`-delimitado / UTF-8 que os importers esperam.

Dados NÃO são versionados no repo (fontes oficiais grandes). Apenas os ETLs.

## CID-10 (DATASUS) — `etl_cid10_datasus.py`

Fonte oficial (público, gratuito):
`http://www2.datasus.gov.br/cid10/V2008/downloads/CID10CSV.zip`
(contém CID-10 categorias/subcategorias/capítulos/grupos + CID-O categorias/grupos, ISO-8859-1/CRLF).

Procedimento (reproduzível):

```bash
# 1. baixar + extrair
curl -sL -o CID10CSV.zip "http://www2.datasus.gov.br/cid10/V2008/downloads/CID10CSV.zip"
unzip -o CID10CSV.zip

# 2. ETL -> cid10_full.csv (CODIGO;DESCRICAO;CAPITULO;GRUPO;CATEGORIA;PARENT;SEXO;IDADE_MIN;IDADE_MAX;NOTIFICACAO)
python3 etl_cid10_datasus.py        # roda no diretório dos CSVs extraídos

# 3. dry-run (valida, não persiste) — rode dentro do container django do ambiente-alvo
python manage.py import_cid10 --source /caminho/cid10_full.csv --cid-version 2008 --dry-run

# 4. import real
python manage.py import_cid10 --source /caminho/cid10_full.csv --cid-version 2008
```

Resultado esperado: **14.233 códigos** (2.045 categorias raiz + 12.188
subcategorias com `parent` ligado). Restrição de sexo do DATASUS (`RESTRSEXO`
F/M) preservada. Importado no staging em 2026-07-30.

Atenção: o importer ativo é o do app `core` (hierárquico → `core.CID10Code`),
não o legado de `apps.ai`. Confirme com `manage.py import_cid10 --help`
("hierarchical DATASUS CID-10 table").

## CBO-2002 (ocupações) — `etl_cbo.py`

Fonte (público): `https://raw.githubusercontent.com/datasets-br/cbo/master/data/lista_canonicos.csv`
(`codigo,termo`; código formato família-ocupação, ex `8485-05`).

```bash
curl -sL -o lista_canonicos.csv "https://raw.githubusercontent.com/datasets-br/cbo/master/data/lista_canonicos.csv"
python3 etl_cbo.py                  # -> cbo_full.csv (CODIGO;TITULO;FAMILIA, código sem hífen, família=4 díg)
# no container do ambiente-alvo:
python manage.py import_cbo --source /caminho/cbo_full.csv --cbo-version 2002 --dry-run
python manage.py import_cbo --source /caminho/cbo_full.csv --cbo-version 2002
```

Resultado: **2.445 ocupações** (602 famílias). Ex 225125 Médico clínico (fam
2251), 223505 Enfermeiro (fam 2235). Importado no staging em 2026-07-30.

## SIGTAP (procedimentos SUS) — `etl_sigtap.py`

Fonte (público, FTP DATASUS): `ftp://ftp2.datasus.gov.br/public/sistemas/tup/downloads/TabelaUnificada_AAAAMM_vNNN.zip`
(liste o diretório p/ pegar a competência mais recente; arquivo `tb_procedimento.txt`,
posicional ISO-8859-1, layout em `tb_procedimento_layout.txt`).

```bash
curl -s -o sigtap.zip "ftp://ftp2.datasus.gov.br/public/sistemas/tup/downloads/TabelaUnificada_202607_v2607101010.zip"
unzip -o sigtap.zip tb_procedimento.txt
python3 etl_sigtap.py               # -> sigtap_full.csv (valores centavos->reais, complexidade/sexo mapeados)
# no container do ambiente-alvo:
python manage.py import_sigtap --source /caminho/sigtap_full.csv --sigtap-version 202607 --dry-run
python manage.py import_sigtap --source /caminho/sigtap_full.csv --sigtap-version 202607
```

Resultado: **4.996 procedimentos** (competência 202607). Ex 0303010010 Tratamento
de dengue clássica SH=R$229,44. Idade/instrumento ficam vazios (unidade de idade e
tabela de instrumento não estão no tb_procedimento — não fabricar). Importado no
staging em 2026-07-30.

## CID-O morfologia (oncologia) — `etl_cido.py`

Fonte: mesmo `CID10CSV.zip` do DATASUS (arquivo `CID-O-CATEGORIAS.CSV`, morfologia;
a topografia CID-O são os códigos `C` do CID-10, já governados em `core.CID10Code`).

```bash
# (o CID10CSV.zip já traz CID-O-CATEGORIAS.CSV)
python3 etl_cido.py                 # -> cido_full.csv (tira prefixo 'M', extrai comportamento, REFER)
# no container do ambiente-alvo (precisa do model/importer CIDO-1 deployado):
python manage.py import_cido --source /caminho/cido_full.csv --cido-version 2008 --dry-run
python manage.py import_cido --source /caminho/cido_full.csv --cido-version 2008
```

Resultado: **816 morfologias** (448 malignas / comportamento 3). Ex 8500/3
Carcinoma ductal invasivo (ref C50.-). `cid10_ref` pode listar múltiplos CID-10
(ex C40.-,C41.-). Importado no staging em 2026-07-31.

## UCUM (unidades de medida) — `etl_ucum.py`

Fonte (público): `https://raw.githubusercontent.com/ucum-org/ucum/main/ucum-essence.xml`

```bash
curl -sL -o ucum-essence.xml "https://raw.githubusercontent.com/ucum-org/ucum/main/ucum-essence.xml"
python3 etl_ucum.py                 # -> ucum_full.csv (UCUM_CODE;DISPLAY)
python manage.py import_ucum --source /caminho/ucum_full.csv --ucum-version 2.2 --dry-run
python manage.py import_ucum --source /caminho/ucum_full.csv --ucum-version 2.2
```

Resultado: **312 unidades** (UCUM 2.2). O código sai do atributo `Code`
(case-sensitive), nunca do `CODE` maiúsculo. Importado no staging em 2026-08-04.

⚠️ **Limite conhecido**: o arquivo oficial só traz as unidades **atômicas**.
As compostas que o laboratório usa de fato (`mg/dL`, `mmol/L`, `10*3/uL`) são
expressões UCUM derivadas e **não existem como linha** — o catálogo hoje tem as
312 atômicas mais as 5 compostas que já estavam lá. A fonte natural para o resto
é o "example UCUM units" que acompanha o LOINC, hoje bloqueado (ver Pendências).

## ANVISA medicamentos — `etl_anvisa.py`

Fonte (público): `https://dados.anvisa.gov.br/dados/DADOS_ABERTOS_MEDICAMENTOS.csv`

```bash
curl -skL -o anvisa_medicamentos.csv "https://dados.anvisa.gov.br/dados/DADOS_ABERTOS_MEDICAMENTOS.csv"
python3 etl_anvisa.py anvisa_medicamentos.csv   # -> anvisa_full.csv
python manage.py import_anvisa --source /caminho/anvisa_full.csv --anvisa-version 2026-08 --dry-run
python manage.py import_anvisa --source /caminho/anvisa_full.csv --anvisa-version 2026-08
```

Resultado: **10.276 medicamentos ativos** (de 43.400 linhas: 26.146 com registro
inativo e 6.978 sem número de registro ficam de fora). Ex 170 registros de
dipirona. `APRESENTACAO`/`EAN`/`TARJA` saem vazios — o dataset não os traz e
tarja errada em controlado é dado clínico perigoso. Importado no staging em
2026-08-04.

- **GOTCHA encoding**: o CSV é **ISO-8859-1**, não UTF-8 (estoura em `0xca`).
- **GOTCHA certificado**: o host tem cert inválido — `curl -k`.
- **GOTCHA varchar**: a DCB de fitoterápicos lista a associação inteira e chega a
  380 chars; `AnvisaProduct.dcb` foi de 200 → 500 (core 0038).

⚠️ **Este ETL sozinho não ativa o casamento de NF-e**: o dado aberto de
medicamentos **não publica EAN nenhum**, e o único consumidor do `AnvisaProduct`
é `match_anvisa_product_by_ean`. Rode o `etl_anvisa_cmed.py` a seguir.

## ANVISA apresentações / preços CMED — `etl_anvisa_cmed.py`

Fonte (público): `https://dados.anvisa.gov.br/dados/TA_PRECO_MEDICAMENTO.csv`

```bash
curl -skL -o cmed_precos.csv "https://dados.anvisa.gov.br/dados/TA_PRECO_MEDICAMENTO.csv"
python3 etl_anvisa_cmed.py cmed_precos.csv   # -> anvisa_cmed_full.csv
# rode DEPOIS do import_anvisa — apresentação órfã é pulada, nunca cria produto fantasma
python manage.py import_anvisa_cmed --source /caminho/anvisa_cmed_full.csv --cmed-version 2026-08 --dry-run
python manage.py import_anvisa_cmed --source /caminho/anvisa_cmed_full.csv --cmed-version 2026-08
```

Resultado: **25.701 apresentações** (25.700 com EAN, todas com preço de fábrica),
referenciando 8.935 produtos distintos. É o que faz `AnvisaProduct.by_ean` — e
portanto o casamento de linha de NF-e — parar de voltar vazio.

- **Chave**: o `REGISTRO` da CMED tem **13 dígitos = 9 do produto + 4 da
  apresentação**. ~80% dos 10.276 produtos ativos casam pelo prefixo de 9; o
  resto são apresentações de produto inativo/sem registro no outro dataset e o
  importer as reporta como órfãs.
- **GOTCHA cabeçalho na linha 42** (as anteriores são título e notas da CMED) —
  localizado pelo texto "REGISTRO", nunca por índice fixo.
- **GOTCHA EAN ausente** vem como `    -     `, não vazio. Preço usa vírgula
  decimal e ponto de milhar (`1.234,56`); vazio vira NULL, nunca R$ 0,00.
- **TARJA não é importada**: a CMED classifica em "Tarja Vermelha/Preta/Sem
  Tarja" e o modelo quer a lista da Portaria 344/98 (A1, A2, B1…). O mapeamento
  não é 1:1 (tarja preta cobre A1/A2/A3/B1/B2) e errar a lista de um controlado é
  dado clínico perigoso. `controlled_class` segue em `none` até haver fonte 1:1.
- **Limite**: só o **EAN 1** é guardado (preenchido em 25.700 de 25.701). EAN 2
  aparece em 1.129 apresentações (4%) e EAN 3 em 59 — NF-e que traga um desses
  códigos alternativos não casa.

## CNES (estabelecimentos de saúde) — `etl_cnes.py`

Fonte (público, FTP DATASUS):
`ftp://ftp.datasus.gov.br/cnes/BASE_DE_DADOS_CNES_AAAAMM.ZIP` (~730 MB).

```bash
curl -s -o cnes.zip "ftp://ftp.datasus.gov.br/cnes/BASE_DE_DADOS_CNES_202606.ZIP"
# extraia SÓ estes dois membros — o pacote inteiro passa de 3 GB
unzip -o cnes.zip "tbEstabelecimento202606.csv" "tbTipoUnidade202606.csv" -d cnes/
python3 etl_cnes.py 202606          # -> cnes_full.csv (~45 MB)
python manage.py import_cnes --source /caminho/cnes_full.csv --cnes-version 202606
```

Resultado: **627.705 estabelecimentos** (490.186 ativos + 137.519 desabilitados,
que entram com `ATIVO=0` em vez de sumir). Import leva ~40 min (~280 linhas/s) —
valide o formato com um `head -5000` em `--dry-run` antes de soltar o arquivo todo.
Importado no staging em 2026-08-04.

- **GOTCHA `CO_TIPO_UNIDADE` vem vazio** na competência inteira; quem carrega o
  código de tipo é `TP_UNIDADE`, resolvido contra `tbTipoUnidade`.
- **GOTCHA tipo órfão**: `TP_UNIDADE=16` não existe em `tbTipoUnidade` (257
  estabelecimentos) — ficam sem descrição de tipo, e o ETL avisa em vez de inventar.
- **Município com 6 dígitos**: o DATASUS entrega o código IBGE sem o dígito
  verificador. É gravado como vem; o DV não é calculado (seria fabricar, e o
  campo não é chave de junção com nada).

## TUSS (padrão TISS / ANS) — `etl_tuss.py`

Fonte (público): `https://www.ans.gov.br/arquivos/extras/tiss/Padrao_TISS_Representacao_de_Conceitos_em_Saude_AAAAMM.zip`
(~413 MB; o slug da página do padrão muda a cada release — parseie a página
índice do padrão TISS em vez de hardcodar a competência).

```bash
curl -sL -o tiss.zip "https://www.ans.gov.br/arquivos/extras/tiss/Padrao_TISS_Representacao_de_Conceitos_em_Saude_202607.zip"
unzip -o -j tiss.zip "*TUSS 22*.xlsx" "*TUSS 18*.xlsx" "*TUSS 20*.xlsx" -d tiss/
python3 etl_tuss.py                 # -> tuss_full.csv (CODIGO;DESCRICAO;GRUPO;SUBGRUPO;TABELA)
python manage.py import_tuss --file /caminho/tuss_full.csv --tuss-version 202607
```

Resultado: **54.136 termos vigentes** — tabela 22 (5.967 procedimentos), 18
(3.595 diárias/taxas/gases) e 20 (44.574 medicamentos). A coluna `TABELA`
alimenta `TUSSCode.table_number`, que a valoração CBHPM usa para distinguir
procedimento de diária e de medicamento (o importer não preenchia esse campo até
2026-08-04). Termos com fim de vigência no passado são filtrados — `import_tuss`
grava `active=True` em tudo que recebe, e importá-los ressuscitaria código não
faturável. Importado no staging em 2026-08-04.

- **GOTCHA HEAD/403**: `www.ans.gov.br` aceita HEAD, `www.gov.br/ans` devolve 403
  no HEAD (WAF) — healthcheck dessas URLs só com GET.
- **GOTCHA XLSX**: os ETLs desta pasta não têm dependência externa e openpyxl não
  está instalado em lugar nenhum, então o XLSX é lido com `zipfile`+`ElementTree`.
  A altura do cabeçalho e a **posição das colunas mudam entre tabelas** (a T20 tem
  Apresentação/Laboratório no meio), então header e colunas são achados por NOME.
- **Datas em serial do Excel** (`39857`), não texto.
- ✅ **Ponte TUSS↔ANVISA (2026-08-04)**: o `REGISTRO ANVISA` da tabela 20 vai para
  `TUSSCode.anvisa_registro` (core 0040). Está preenchido em **44.563 dos 44.574**
  termos de medicamento, e é o que permite saber qual TUSS cobrar por um
  medicamento dispensado — o material já tinha esse caminho via
  `SimproMaterial.tuss_code`, o medicamento não tinha nenhum. Use
  `apps.core.terminology.tuss_for_anvisa_registro`, que casa pelo registro de 13
  dígitos e cai para o produto (9 dígitos) quando a apresentação exata não tem
  TUSS. Cobertura medida: 25.566 registros casam com apresentação CMED importada.
- **Não importado**: `Apresentação` e `Laboratório` da tabela 20 não têm campo em
  `TUSSCode` (a apresentação vive em `core.AnvisaPresentation`, alcançável pela
  ponte acima).

## Pendências (fontes)

- **LOINC — BLOQUEADO por cadastro** (não por licença). `loinc.org/download/*`
  redireciona para login; `Top 2000` idem; UMLS/NLM exige licença UMLS. A licença
  LOINC **permite** redistribuição, e a conta é gratuita — o caminho certo é criar
  conta no loinc.org, não caçar mirror. Investigadas e descartadas: o pacote FHIR
  da RNDS (`rnds-fhir.saude.gov.br/package.tgz`) **não enumera nenhum código
  LOINC**, e `hl7.terminology.r4` também não. Só `https://tx.fhir.org/r4` serve
  lookup anônimo código-a-código (LOINC 2.82) — serve para validar, não para dump.
- **Licenciados (bloqueados sem fonte paga)**: NANDA/NIC/NOC, Simpro/Brasíndice, CBHPM.
