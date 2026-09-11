<!-- maestro-order v1
id: 002
ts: 2026-09-11T12:35:06-03:00
epoch: 1789140906
head: aa6636be697daa3a88ed71b991ecf8cbde8efbef
branch: order/002-catalogos-reproduziveis
intent_version: 4
intent_hash: e88157e6
author_session: desconhecido
-->
# Ordem 002 — Prioridade 2: tornar a carga de catálogos reproduzível, levar o verify_catalogs para a imagem e para o procedimento de deploy, e destravar o LOINC




**Direção:** INTENT v4 — §Prioridades **item 2**, *"Receita destravada antes de escopo novo… os
catálogos estão carregados em staging desde 04/08 … mas por mão humana, nunca por pipeline:
todo ambiente novo nasce vazio e a carga não é reproduzível a partir do repositório."*

**Escopo dado pelo Imediato:** (a) `verify_catalogs` na imagem e no gate de deploy · (b) seed de
catálogos para ambiente novo · (c) bug do CID-O `varchar(10)` · (d) LOINC por cadastro gratuito.
**CBHPM fora** — é compra, está com o Capitão.

---

## 0. Dois dos quatro itens mudaram de forma antes do plano

### (c) O bug do CID-O **já está corrigido**. Não há trabalho aqui.

Os três registros de import contam a história inteira:

| Quando | Status | Total | Inseridas | Erros |
|---|---|---:|---:|---:|
| 31/07 14:24 | `partial` | 816 | 772 | 44 |
| 31/07 14:25 | `partial` | 816 | 0 | 44 |
| **31/07 14:28** | **`success`** | 816 | **44** | **0** |

Alguém bateu no `varchar(10)`, tentou de novo, alargou a coluna e reimportou as 44 que
faltavam — tudo em quatro minutos. Hoje `core_cidomorphology` tem **816 linhas**, exatamente
o que o `scripts/catalogs/README.md` declara como resultado esperado ("816 morfologias, 448
malignas"), e **nenhuma coluna da tabela é `varchar(10)`**: são 32, 500, 32, 500, 32, 1 e 60.

Eu levei este item para o relatório lendo a primeira linha do log e não a terceira. **Não
existe bug para corrigir nem linha para recuperar.** O que sobra é uma lição barata, e ela vai
para o item 3 do plano: o log de proveniência já sabia, e ninguém o consultava.

### (a) Não existe pipeline de deploy para gatear.

Os três workflows — `ci.yml`, `deploy-staging.yml`, `release-deploy.yml` — **só constroem e
publicam imagem**. Nenhum faz deploy: nenhum tem `ssh`, nenhum roda `docker compose up`. O
nome `deploy-staging.yml` é enganoso; ele é *build*. Quem faz deploy é humano, seguindo o
`docs/DEPLOY.md`.

Então "entrar no gate de deploy" não é acrescentar um `step` a um YAML. É decidir **onde** o
gate mora quando o deploy é um humano com um terminal. O plano abaixo propõe dois lugares, não
um.

---

## 1. O que o ambiente tem hoje (medido em 11/09, na lab)

| Catálogo | Linhas | Versão registrada | Estado |
|---|---:|---|---|
| CNES | 627.706 | 202606 | ok |
| TUSS | 54.139 | — (log próprio, **sem campo de versão**) | ok, proveniência fraca |
| ANVISA | 24.346 + 10.276 | 2026-08 | ok |
| CID-10 | 14.233 | 2008 | ok |
| SIGTAP | 5.004 | 202607 | ok |
| CBO | 2.455 | 2002 | ok |
| CID-O | 816 | 2008 | ok (ver §0) |
| UCUM | 316 | 2.2 | ok |
| **LOINC** | **6** | — | **amostra** — item (d) |
| **CBHPM** | **0** | — | **fora desta ordem** (compra) |

`scripts/catalogs/README.md` **já é o procedimento reproduzível**: fonte oficial, URL, ETL,
`--dry-run`, import real e contagem esperada, catálogo por catálogo. O que falta não é a
receita — é alguém além de um humano atento conseguir executá-la.

---

## 2. Plano

### Passo 1 — Subir a imagem de staging para o HEAD do branch

`verify_catalogs` entrou no repo em 18/08 (`edb3302`, Onda 2). A imagem que roda é de 05/08.
São **45 commits** de diferença, e o comando simplesmente não existe lá:

```
$ manage.py verify_catalogs
Unknown command: 'verify_catalogs'
```

Sem este passo, (a) é impossível. **E é o passo de maior risco da ordem**, porque não traz só
o `verify_catalogs`: traz a Onda 2 inteira — receita e conformidade TISS. É mudança de
software num ambiente que acabou de migrar.

Proposta: **build da imagem a partir do HEAD, subir na lab com `IMAGE_TAG` fixado no digest
novo, e manter o digest atual anotado para rollback** (`docker compose up -d` com o digest
antigo desfaz em um minuto — os volumes não são tocados). Suíte completa no CI antes, e o
`smoke_test.sh` depois.

### Passo 2 — `seed_catalogs`: um comando que executa o README

Hoje o conhecimento vive num `.md` e o resultado vive num banco; nenhum dos dois é executável
por um ambiente novo. Proposta: um management command **orquestrador**, não um novo importer:

- lê um **manifesto versionado no repo** (`scripts/catalogs/manifest.toml`) com, por catálogo:
  comando, caminho da fonte, **rótulo de versão** e contagem esperada;
- chama os `import_*` existentes na ordem certa, cada um com o seu `--<x>-version`;
- **falha se a contagem final divergir da esperada** — é o que teria gritado no CID-O em 31/07;
- `--dry-run` propaga para todos.

**O rótulo de versão continua sendo entrada explícita, nunca adivinhada.** É o que o docstring
do `verify_catalogs` exige e o que o INTENT §Limites proíbe inventar. O manifesto é onde o
humano escreve o que baixou; o comando só executa.

As **fontes** continuam fora do git (são grandes e oficiais). O manifesto aponta para um
diretório que o operador preenche — e o comando diz, nome a nome, o que falta.

### Passo 3 — `verify_catalogs` nos dois lugares onde o deploy acontece

1. **No `docs/DEPLOY.md`**, como passo obrigatório **depois** dos imports e **antes** do smoke
   test — que é onde o próprio docstring do comando manda pôr.
2. **No `smoke_test.sh`**, como verificação nova: hoje ele checa health, auth, schema, front,
   estáticos e Celery — e não olha se o sistema tem os códigos sem os quais toda guia TISS sai
   inválida. É o lugar certo, porque é o script que alguém já roda depois de todo deploy.

Sem pipeline para gatear, o gate mora no que o humano executa. Isso é honesto e é o que existe.

### Passo 4 — LOINC (item d), com um limite claro

`loinc.org` exige **cadastro gratuito** — não licença paga. Destrava também as unidades UCUM
**compostas** (`mg/dL`, `10*3/uL`), que não existem no `ucum-essence.xml`.

O cadastro é ato de pessoa: aceita termos em nome de alguém. **Não crio conta, não aceito
termos.** O que faço: o ETL e a entrada no manifesto, prontos para o arquivo. Quem faz o
cadastro e baixa é o Imediato ou o Capitão. Se não couber agora, o passo cai sem afetar 1–3.

---

## 3. O que esta ordem NÃO faz

- **CBHPM.** Fora por decisão do Imediato: é compra, está com o Capitão. Enquanto for zero,
  a Prioridade 2 **não fecha** — e o plano não finge que fecha.
- **Não mexe no conteúdo carregado.** Nenhum reimport dos catálogos que já estão certos.
- **Não cria conta em serviço externo** (§Passo 4).
- **Não leva nada para `master`.** A merge é para `onda0-perimetro-multitenant`, como a 001.

## 4. Risco, e como sai

| Risco | Mitigação |
|---|---|
| Passo 1 traz a Onda 2 para um ambiente recém-migrado | Digest antigo anotado; rollback é `up -d` com ele. Volumes intocados. Suíte no CI antes, smoke depois |
| `seed_catalogs` rodar em ambiente que já tem dado | Os `import_*` são upsert idempotente; `--dry-run` obrigatório antes do real |
| Manifesto virar lugar de adivinhar versão | O comando **falha** sem rótulo explícito; não há default |

## 5. Prova

- `verify_catalogs` existindo e saindo **0** na lab, com o relatório por catálogo.
- `seed_catalogs --dry-run` num banco vazio listando os 10 catálogos e o que falta de fonte.
- `smoke_test.sh` passando **9/9** (os 8 de hoje + o gate de catálogo).
- Contagens idênticas às da tabela do §1 depois do passo 1 — a imagem nova não pode mexer no dado.
- `maestro evidence --record --label order-2 -- <comando>` no tip do branch.

## 6. Divergência que levo ao Imediato

O `PLAN_GA_ROADMAP.md` põe os **7 wedges AI ligados** como item 3 da definição de GA. O INTENT
v4 põe receita (2) e recuperação provada (3) **antes** de interceptação (4). **INTENT manda** —
wedge sobre sistema que não fatura e não restaura é demo. Registrado, não resolvido aqui.

---

## Contrato de execução
- Trabalhe APENAS no branch `order/002-catalogos-reproduziveis`; NUNCA no main/master.
- Prove com o ledger: `maestro evidence --record --label order-2 -- <suíte>` no tip do branch.
- Direção vigente na criação: INTENT v4 (`.maestro/INTENT.md`) — o plano cita a seção da direção que autoriza esta ordem.
- Estourou Ask-First ou orçamento? PARE e reporte ao humano — não improvise.
- O aceite é do diretor: `maestro order --accept 002` (você não fecha a própria ordem).

---

## 7. Passos 2, 3 e 4 — FEITOS (11/09). Passo 1 aguarda o CI.

### Passo 2 — `seed_catalogs` + `scripts/catalogs/manifest.toml`

Orquestrador sobre os `import_*` que já existem: não importa nada por conta própria, não
conhece formato de fonte, não baixa nada. O que acrescenta é a **conferência de contagem**
— reprova quando o total fica **abaixo** do esperado; acima não reprova, porque banco
semeado tem linhas legítimas a mais (staging: 2.455 CBO contra 2.445 do ETL).

Duas recusas, ambas deliberadas:

- **Versão vazia é erro**, nomeando o catálogo e o que preencher, **sem default em lugar
  nenhum**. O rótulo diz qual release da fonte foi carregada; adivinhá-lo fabrica
  proveniência (INTENT §Limites).
- **`--manifest` é obrigatório**, e isso é fato de empacotamento, não preferência: a imagem
  do backend é construída de `./backend`, então `scripts/` **não está nela** — verificado
  contra `vitali-backend@sha256:da58aae3`. Default apontando para caminho inexistente dentro
  do container seria pior que default nenhum.

### Passo 3 — o gate nos dois lugares onde o deploy acontece

`docs/DEPLOY.md` como passo numerado **depois** dos imports, e `scripts/smoke_test.sh` como
**check 7**. Imagem anterior a 18/08 não tem o comando: o check **avisa** em vez de reprovar
— "sua imagem é velha" não é o mesmo defeito que "seus catálogos estão vazios", e confundir
os dois faz o smoke mentir nos dois sentidos.

**Erro corrigido no próprio DEPLOY.md:** ele mandava anexar o gate ao *"script que o
`deploy-staging.yml` SSHes in and runs after `migrate_schemas`"*. Esse script não existe.

### Passo 4 — LOINC pronto até onde uma pessoa é necessária

`scripts/catalogs/etl_loinc.py` converte o `Loinc.csv` oficial, filtra
`DEPRECATED`/`DISCOURAGED`/`TRIAL` e emite o formato que o `import_loinc` espera — testado
contra fixture. Entrada no manifesto criada, marcada `blocked`.

**O que falta é ato de pessoa:** conta gratuita em <https://loinc.org/downloads/> e
**aceite da LOINC License** no download. Aceitar termos é declaração em nome de alguém; não
faço por ninguém. A licença permite redistribuição — uma vez baixado, o CSV circula entre
ambientes. Destrava junto as unidades UCUM compostas (`mg/dL`, `10*3/uL`).

### O que ainda NÃO foi provado

**Nada deste passo 2–4 foi executado.** Não há pytest na forge nem dev-deps na imagem de
staging, então o CI é a primeira execução destes testes. O lint eu consegui rodar:
**ruff 0.9.0**, a versão que o CI fixa, instalada pela convenção `~/opt` do `AMBIENTES.md`.
Comecei com a 0.16.7 e ela acusava quatro regras que **não existem** na versão do gate —
"limpo aqui" não queria dizer nada sobre "limpo lá". Backend inteiro passa em `check` e
`format`, 1.086 arquivos.

### Armadilha do fluxo, para a próxima ordem

**Branch de ordem não dispara CI.** O `ci.yml` roda em push para `main|master|develop` e em
`pull_request` **contra** essas bases. Um PR de `order/NNN` para `onda0-perimetro-multitenant`
não casa o filtro. Então código de ordem só entra sob o gate quando é mesclado no `onda0` e o
PR #211 roda. Não é defeito desta ordem; é do desenho do `ci.yml`, e vale registrar antes que
alguém confunda "nenhum run vermelho" com "testado".

---

## 8. Passo 1 — FEITO na segunda tentativa. E a primeira provou mais que a segunda.

### A tentativa que caiu, e por que ela valeu

Subi as imagens do HEAD, `celery-worker` entrou em crash loop e levou o `django` junto
(gunicorn: *"Worker failed to boot"*). Uma leitura de log deu a causa inteira, em
`vitali/settings/production.py:62`:

```
ImproperlyConfigured: BACKUP_ENCRYPTION_KEY must be set. scripts/backup.sh dumps
LGPD-regulated clinical data (EMR — apps.emr); without this key the nightly dump is
written to disk in plaintext.
```

**É o achado da §10 da ordem 001 chegando pelo outro lado.** A Onda 2 acrescentou um
**guard de boot** para a mesma variável que faltava. A imagem de 05/08 é anterior ao guard —
por isso ela subia feliz com o mesmo ambiente, sem nunca produzir um backup.

Rollback imediato, sem investigar no ambiente quebrado: serviço restaurado, smoke 8/8,
nenhum volume tocado. E o repo foi revertido junto, para não ficar prescrevendo um deploy
que não sobe.

O guard está certo e a queda foi útil: converteu dois meses de silêncio numa parada
barulhenta, no lugar certo, antes de servir tráfego.

### A tentativa que subiu

Chave provisionada pelo Imediato. Repin, deploy, **dez containers, nove healthy** (o
`db-backup` não tem healthcheck).

**`verify_catalogs` → EXIT=0**, pela primeira vez num ambiente, com as nove contagens
**idênticas** às medidas na ordem 001 §1 — a imagem nova não encostou no dado:

```
CID-10 14.233 · TUSS 54.139 · CNES 627.706 · ANVISA 10.276 · CMED 24.346
SIGTAP 5.004 · CBO 2.455 · CID-O 816 · UCUM 316
```

**`smoke_test.sh` → 9 passaram, 0 falharam**, agora com o check 7 rodando de verdade em vez
de pular por imagem velha.

### A prova que faltava há dois meses

`backup.sh` rodado uma vez, `BACKUP_SH_EXIT=0`:

```
[backup] Written: /backups/vitali_20260911T230846Z.dump (25.5M)
[backup] Encrypting (AES256)…
[backup] Encrypted: /backups/vitali_20260911T230846Z.dump.gpg
[backup] Metric written: /backups/metrics/vitali_backup.prom
```

E, porque "nasceu um arquivo" não é prova de recuperação, fui além:

| Verificação | Resultado |
|---|---|
| É mesmo GPG, não texto claro? | `gpg --list-packets`: `symkey enc packet, cipher 9` (**AES256**), s2k 3 |
| **Abre com a chave do ambiente?** | sim |
| **O que sai é um dump válido?** | primeiros bytes = **`PGDMP`** — formato custom do `pg_dump` |
| Sobrou texto claro? | o `.dump` novo foi removido após cifrar |
| Observabilidade | `vitali_backup_last_success_timestamp_seconds 1789168257` — a métrica tem valor real pela primeira vez |

### Duas coisas que ficam para o Imediato

**1. Divergência no comprimento da chave — 46, não 48.** O valor no `.env.staging` tem
**46 bytes** (linha de 68 = `BACKUP_ENCRYPTION_KEY=` + 46), sem aspas e sem CR, e o `mtime`
não mudou entre a gravação e a conferência. O arquivo cresceu exatamente uma linha, então o
resto do `.env.staging` está intacto.

Se o cofre guardar 48, **todo dump nasce inabrível pela cópia do cofre** — que é exatamente
o risco que o docstring do `backup.sh` descreve. Comparação sem imprimir segredo nenhum:

```
fingerprint do arquivo : b40e33e7af3a1066
comparar com           : printf '%s' '<chave do cofre>' | sha256sum | cut -c1-16
```

Bateu, foi contagem. Não bateu, a chave do cofre precisa substituir a do arquivo **antes**
de este dump ser considerado recuperável.

**2. Ainda há um dump em texto claro no volume.** `vitali_20260723T171954Z.dump`, 686 KB, de
23/07 — anterior ao guard de criptografia. É dado clínico em claro, em repouso, e agora é o
único. Cifrar ou apagar é decisão do Imediato; não apago nada sem 'vai'.
