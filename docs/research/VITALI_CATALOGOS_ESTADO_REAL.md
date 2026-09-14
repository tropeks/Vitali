# Catálogos de referência — estado real, medido

**Data:** 2026-09-11 · **Medido contra:** o banco de staging migrado para a lab
(`vitali-lab`, restore conferido byte a byte contra o PVE) · **Motivo:** preparar a
Prioridade 2 do INTENT antes de ela virar ordem.

> **Conclusão curta:** a Prioridade 2 do INTENT está escrita sobre um fato errado — meu.
> Os catálogos **estão carregados** em staging desde 04/08, com proveniência gravada. O que
> não existe é caminho automatizado, e o que sobra não é trabalho de código: é **licença**.

---

## 1. O que o banco tem, agora

| Tabela | Linhas | Proveniência (`core_terminologyimportlog`) |
|---|---:|---|
| `core_cnesestablishment` | 627.706 | CNES/DATASUS, versão **202606**, 04/08 |
| `core_tusscode` | 54.139 | `core_tusssynclog`, 04/08 — **sem campo de versão** |
| `core_anvisapresentation` | 24.346 | ANVISA, **2026-08**, 04/08 |
| `core_cid10code` | 14.233 | DATASUS, versão **2008**, 30/07 |
| `core_anvisaproduct` | 10.276 | ANVISA, **2026-08**, 04/08 |
| `core_sigtapprocedure` | 5.004 | DATASUS/SIGTAP, **202607**, 30/07 |
| `core_cbocode` | 2.455 | MTE/DATASUS, **2002**, 30/07 |
| `core_cidomorphology` | 816 | DATASUS, **2008** — importação **`partial`** |
| `core_ucumunit` | 316 | UCUM, **2.2**, 04/08 |
| `core_loinccode` | **6** | LOINC, sem versão — amostra, não catálogo |
| `core_cbhpmitem` | **0** | **nunca importado** |

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

## 3. O que de fato bloqueia, em ordem de custo

**a) CBHPM = 0, e é decisão de compra, não de engenharia.** `import_cbhpm` existe, é
idempotente, isola erro por linha e grava proveniência — só falta o CSV. O
`DEPTH_BACKLOG` §P1 é explícito: *"Licenciados sem fonte paga: NANDA/NIC/NOC,
Simpro/Brasíndice, CBHPM seguem simbólicos."* `apps/billing/revenue_models.py` e
`apps/billing/models.py` dependem de `CBHPMItem`. **Isto é item para o Capitão: comprar a
tabela AMB/CBHPM ou aceitar operar sem ela, e o que isso custa em glosa.**

**b) Nenhum caminho reproduzível.** A carga de 04/08 não está em lugar nenhum além do banco
que a recebeu. Se a lab fosse recriada do zero, nasceria vazia. É a diferença entre ter o
resultado e ter a receita.

**c) `verify_catalogs` existe no repo e NÃO existe na imagem que roda.** O comando é o gate
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
fonte. É bug de schema, barato, e tem o número exato de linhas perdidas.

**e) LOINC tem 6 linhas** e está bloqueado por **cadastro** (grátis) em `loinc.org`, não por
licença. Trava junto as unidades UCUM compostas (`mg/dL`, `10*3/uL`).

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
