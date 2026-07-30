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

## Pendências (fontes)

- **Públicas, importáveis** (mesmo padrão): CBO (MTE/DATASUS), SIGTAP (DATASUS),
  CNES, TUSS (ANS), LOINC, ANVISA (dados abertos).
- **CID-O**: greenfield — a fonte (`CID-O-CATEGORIAS.CSV`/`GRUPOS.CSV`) vem no
  mesmo zip, mas NÃO há model nem importer (é texto livre em `PathologyReport`).
  Exige criar `CIDOCode(TerminologyCatalog)` + `import_cido` + FK.
- **Licenciados (bloqueados sem fonte paga)**: NANDA/NIC/NOC, Simpro/Brasíndice, CBHPM.
