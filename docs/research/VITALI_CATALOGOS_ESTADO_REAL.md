# Catálogos de referência — estado real, medido

**Atualizado em:** 2026-09-25 (§0) · **Primeira medição:** 2026-09-11 (§1–§5, mantidas como
histórico) · **Medido contra:** o banco de staging migrado para a lab (`vitali-lab`,
restore conferido byte a byte contra o PVE).

> **Conclusão curta, em 25/09:** os dois bloqueadores que o INTENT v5 §Prioridades 2 cita a
> partir deste arquivo — **"CBHPM está em zero"** e **"LOINC tem 6 linhas"** — deixaram de
> ser verdade. LOINC está carregado; CBHPM está carregada como **classificação**, sem preço,
> e sem preço tem de ficar até existir contrato. O que resta da CBHPM é **licença**, não
> engenharia.

---

## 0. Estado em 25/09/2026 — o que mudou desde 11/09

### LOINC — carregado

| | 11/09 | 25/09 |
|---|---:|---:|
| `core_loinccode` | 6 (amostra, sem versão) | **112.405** |
| Versão | — | **LOINC 2.83** |

*(Fonte: recibo `loinc-2-83` no ledger do maestro, 16/09/2026, e `TerminologyImportLog`
`513682cc` — `system=loinc`, `version=2.83`, 112.405 adicionadas, 0 erros.)*

A ordem 002 §7 (passo 4) deixou o caminho pronto até onde uma pessoa era necessária:
`scripts/catalogs/etl_loinc.py` converte o `Loinc.csv` oficial para o formato do
`import_loinc`. O ato de pessoa — conta gratuita e aceite da LOINC License — era o que
faltava, e a carga de 2.83 mostra que ele aconteceu. As **6 sementes antigas**, gravadas com
`version=""`, foram **removidas**: eram amostra sem proveniência ao lado de uma release
rotulada.

### CBHPM — carregada como classificação, com preço zero por desenho

A ordem 013 mediu o livro antes de importar (CBHPM 2022 rev. ago/2023, PDF público de 240
páginas) e achou o importador errado: `porte` era `DecimalField`, e **nenhum** dos 4.881
procedimentos extraíveis tem porte numérico. O porte da CBHPM é **classe** (`3B`, `13C`) e,
em 1.046 procedimentos (21% do catálogo), **fração de classe** (`0,01 de 1A`). O importador
antigo teria carregado **0 linhas**.

A ordem 013 separou classificação de valoração (`apps/core/cbhpm_models.py`):

| Campo | O que guarda | De onde vem |
|---|---|---|
| `porte` (`CharField`) | a classe publicada: `3B`, `0,01 de 1A` | do livro |
| `porte_ch` (`DecimalField`, default 0) | a quantidade de CH do porte | **só** de tabela de valoração contratada |
| `valor()` | `porte_ch × valor_ch` | **0** enquanto não houver contrato |

**Importar o livro não produz preço; preço é contrato.** O §1.2 da própria CBHPM diz que os
portes "não expressam valores monetários". `valor()` em zero sem contrato é o comportamento
**correto**, não uma lacuna: gravar `1A` como `1` inflaria o porte de 25 a 100 vezes no
capítulo mais volumoso (ordem 013; INTENT §Limites, nenhum número contratual inventado).

Staging, importada em 16/09/2026 — `TerminologyImportLog` `c7522a03` (`cbhpm`, versão
2022 rev. ago/2023, 4.881 adicionadas, 0 erros). Os 4.881 e os 1.046 batem com o dry-run da
ordem 013. Os 4.866 com porte-classe e o zero de `porte_ch` foram medidos no banco de
staging em 16/09 e estão registrados no brief de 18/09 — **sem recibo próprio no ledger**:

| Medida | Valor |
|---|---:|
| Itens em `core_cbhpmitem` | **4.881** |
| Com `porte` preenchido (classe) | 4.866 |
| Com porte fracionário (`0,01 de 1A`) | 1.046 |
| Com `porte_ch` preenchido | **0** |

O extrator vive no repositório: `scripts/catalogs/etl_cbhpm_pdf.py` (ordem 013). A cópia
versionada reproduz byte a byte o CSV que passou no dry-run de 4.881 linhas.

**Licença.** A folha de rosto diz `© 2022 Editora Manole / AMB — Todos os direitos
reservados`. O Imediato autorizou **importar em staging**; **cobrar** com base nela, não —
até decisão do Capitão (ordem 013, "O que NÃO entra").

### O que isto muda na leitura do resto do arquivo

- §1: as linhas de `core_loinccode` (6) e `core_cbhpmitem` (0) estão **superadas**.
- §3 a) (CBHPM = 0), c) (`verify_catalogs` fora da imagem), d) (CID-O `partial`) e
  e) (LOINC bloqueado) estão **superados** — ver as notas em cada item.
- A CBHPM **nunca** bloqueou a cadeia de receita: `TISSGuide.honorario_cbhpm` e
  `TISSGuide.price_table` são FK opcionais (ordem 006 §1). A cadeia guia → lote →
  fechamento foi provada sem ela (ordens 006, 008, 009).

### O que continua aberto

- ~~INTENT v5 §Prioridades 2 ainda diz "CBHPM está em zero" e "LOINC tem 6 linhas"~~ —
  **corrigido no INTENT v6** (25/09, aprovado pelo Capitão): a receita saiu das prioridades
  e virou guarda permanente em §Limites, com o estado dos catálogos atualizado.
- **`scripts/catalogs/manifest.toml`** ainda marca `loinc` e `cbhpm` como `blocked`, com
  `version = ""` e `expected_rows = 0`. Um ambiente novo semeado pelo `seed_catalogs` não
  reproduz o estado de staging para esses dois catálogos até o manifesto receber rótulo e
  contagem.
- **Valoração CBHPM** depende de tabela contratada por operadora; nenhuma existe.

---

> **Histórico.** As seções abaixo registram a medição de **11/09/2026**, antes das ordens
> 002 e 013. Ficam como estavam, com notas de superação; não descrevem o banco de hoje.

## 1. O que o banco tinha em 11/09

| Tabela | Linhas | Proveniência (`core_terminologyimportlog`) |
|---|---:|---|
| `core_cnesestablishment` | 627.706 | CNES/DATASUS, versão **202606**, 04/08 |
| `core_tusscode` | 54.139 | `core_tusssynclog`, 04/08 — **sem campo de versão** |
| `core_anvisapresentation` | 24.346 | ANVISA, **2026-08**, 04/08 |
| `core_cid10code` | 14.233 | DATASUS, versão **2008**, 30/07 |
| `core_anvisaproduct` | 10.276 | ANVISA, **2026-08**, 04/08 |
| `core_sigtapprocedure` | 5.004 | DATASUS/SIGTAP, **202607**, 30/07 |
| `core_cbocode` | 2.455 | MTE/DATASUS, **2002**, 30/07 |
| `core_cidomorphology` | 816 | DATASUS, **2008** — importação **`partial`** (superado: ver §3 d) |
| `core_ucumunit` | 316 | UCUM, **2.2**, 04/08 |
| `core_loinccode` | **6** | LOINC, sem versão — amostra, não catálogo (**superado em 25/09: 112.405, LOINC 2.83**) |
| `core_cbhpmitem` | **0** | **nunca importado** (**superado em 25/09: 4.881, sem preço** — §0) |

O `docs/DEPTH_BACKLOG.md` §P1 já registrava isto em 04/08, com os mesmos números. Bateu.

## 2. O erro que eu propaguei

`docs/research/VITALI_VIABILIDADE_VS_CE.md` (30/08) lista "catálogos vazios em produção"
como o único bloqueador de receita sobrevivente, marcado **intocado**. O método foi `grep`
por `import_tuss`/`import_cid10` em `.github/workflows/`, `docker/`, `docker-compose*.yml` e
migrations — **zero ocorrências**. O `grep` está certo. A conclusão não.

Nada chama os importers **automaticamente**. Disso não segue que ninguém os chamou: alguém
os rodou à mão em 30/07 e 04/08, e o `core_terminologyimportlog` guarda quem, quando, de
qual fonte e em qual versão.

Levei o erro para o **INTENT v2, §Prioridades item 2**, onde escrevi que os importers *"nunca
são chamados em nenhum ambiente — sem eles, toda guia sai com código inválido"*. Em staging,
são chamados e as guias saem com código válido. **Correção proposta** (o carimbo é do
Capitão):

> 2. **Receita destravada antes de escopo novo.** O caminho guia TISS válida → lote →
>    faturamento tem precedência sobre qualquer módulo adicional. Os catálogos públicos estão
>    carregados em staging desde 04/08, com proveniência em `TerminologyImportLog` — mas
>    **por mão humana, nunca por pipeline**: todo ambiente novo nasce vazio e a carga não é
>    reproduzível a partir do repositório. E o que falta não se resolve com código: **CBHPM
>    está em zero e é catálogo licenciado.**

## 3. O que de fato bloqueava em 11/09, em ordem de custo

**a) CBHPM = 0, e é decisão de compra, não de engenharia.** *(Superado. A ordem 006 §1
mediu que a CBHPM não bloqueia a cadeia; a ordem 013 mostrou que o `import_cbhpm` de então
carregaria 0 linhas do livro real e o corrigiu; staging tem 4.881 itens desde então, sem
preço — §0. A licença segue com o Capitão.)* `import_cbhpm` existe, é
idempotente, isola erro por linha e grava proveniência — só falta o CSV. O
`DEPTH_BACKLOG` §P1 é explícito: *"Licenciados sem fonte paga: NANDA/NIC/NOC,
Simpro/Brasíndice, CBHPM seguem simbólicos."* `apps/billing/revenue_models.py` e
`apps/billing/models.py` dependem de `CBHPMItem`. **Isto é item para o Capitão: comprar a
tabela AMB/CBHPM ou aceitar operar sem ela, e o que isso custa em glosa.**

**b) Nenhum caminho reproduzível.** A carga de 04/08 não está em lugar nenhum além do banco
que a recebeu. Se a lab fosse recriada do zero, nasceria vazia. É a diferença entre ter o
resultado e ter a receita.

*(Superado em parte pela ordem 002: `seed_catalogs` + `scripts/catalogs/manifest.toml`
executam o README; as fontes seguem fora do git.)*

**c) `verify_catalogs` existe no repo e NÃO existe na imagem que roda.** *(Superado. A ordem
002 §8 subiu a imagem; `verify_catalogs` saiu 0 na lab em 11/09 e virou o check 7 do
`smoke_test.sh`.)* O comando é o gate
de deploy escrito exatamente para este problema — e o próprio docstring explica por que a
carga **não** deve ser automática (o rótulo de versão vem do arquivo que o operador baixou;
adivinhar fabricaria proveniência, o que o INTENT §Limites proíbe). Medido na lab:

```
$ manage.py verify_catalogs
Unknown command: 'verify_catalogs'
```

Entrou no repo em **18/08** (`edb3302`, Onda 2). A imagem de staging foi construída em
**05/08**. O branch tem **45 commits** que a imagem não tem — a Onda 2 inteira, que é
justamente o trabalho de receita, não está no ar.

**d) CID-O importou `partial`: 44 de 816 linhas rejeitadas.** Erro real, repetido:
`value too long for type character varying(10)`. Um campo do modelo é curto demais para a
fonte. É bug de schema, barato, e tem o número exato de linhas perdidas. *(Errado já em
11/09. A ordem 002 §0 leu os três registros de import: a terceira execução, de 31/07 14:28,
saiu `success` com as 44 linhas; `core_cidomorphology` tem 816 e nenhuma coluna é
`varchar(10)`. Não havia bug.)*

**e) LOINC tem 6 linhas** e está bloqueado por **cadastro** (grátis) em `loinc.org`, não por
licença. Trava junto as unidades UCUM compostas (`mg/dL`, `10*3/uL`). *(Superado. O cadastro
foi feito, e staging tem LOINC 2.83 com 112.405 linhas — §0.)*

## 4. Divergências roadmap × INTENT

| Tema | Roadmap | INTENT | Quem manda |
|---|---|---|---|
| Wedges AI ligados | `PLAN_GA_ROADMAP` põe os 7 wedges ON como item 3 da definição de GA | §Prioridades põe receita (2) e recuperação (3) antes de interceptação (4) | **INTENT.** Wedge sem receita e sem backup é produto que não fatura e não se recupera |
| Ordem de execução | S27→S33 sequencial, wedges em S30/S31 | Isolamento (1) → receita (2) → recuperação provada (3) | **INTENT.** S27 (ops) e o drill de restore coincidem; o resto reordena |
| `ENFORCE_TENANT_MEMBERSHIP` | S28, "default OFF" | §Prioridades 1 trata isolamento como precondição | **Já convergiu:** está `True` em staging desde 30/08 |
| Catálogos | `DEPTH_BACKLOG` §P1 marca ✅ em 04/08 | INTENT v2 diz que nunca rodam | **O roadmap está certo e o INTENT errado** — ver §2 |

A única divergência real de *prioridade* é a dos wedges. As outras são o INTENT
desatualizado em relação ao que já foi feito.

## 5. Forma proposta da ordem 002

Autorizada por INTENT §Prioridades 2. **Não** é "rodar os importers":

1. Corrigir o INTENT (§2 acima) — carimbo do Capitão.
2. Tornar a carga **reproduzível**: `scripts/catalogs/` já tem os ETLs; falta o runbook que
   um ambiente novo executa, com os rótulos de versão como entrada explícita, nunca
   adivinhada.
3. Subir a imagem de staging para o HEAD do branch — 45 commits, incluindo a Onda 2 e o
   `verify_catalogs`.
4. Ligar `verify_catalogs` como gate de deploy, **depois** dos imports (como o docstring manda).
5. Corrigir o `varchar(10)` do CID-O e reimportar as 44 linhas.
6. Levar ao Capitão a decisão CBHPM: comprar a tabela ou operar sem ela, com o custo de cada
   lado.

O item 6 é o único que decide se a Prioridade 2 fecha. Os outros cinco são trabalho.
