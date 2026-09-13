<!-- maestro-order v1
id: 010
ts: 2026-09-13T05:21:15-03:00
epoch: 1789287675
head: fe8d971b6daaa0e4cb48fa43d08aacb2a633f88b
branch: order/010-submit-e-settings-local
intent_version: 5
intent_hash: a6120b3c
author_session: desconhecido
-->
# Ordem 010 — Duas dividas: o submit da guia respeita o ciclo de vida, e o settings local sai do versionamento

## Contexto

Autoriza a ordem: **`.maestro/INTENT.md` v5, §Limites** — *"Sinal verde tem que significar
verde. Healthcheck, CI e alerta que vivem vermelhos ensinam a equipe a ignorar vermelho — e
aí o vermelho real passa batido."* Os dois itens são a mesma doença: um estado que declara
algo que não aconteceu, e uma permissão concedida por padrão sem ninguém ter decidido.

### (a) `TISSGuideViewSet.submit` contradiz o que a ordem 009 estabeleceu

`views.py:1300-1321` (issue **#213**): aceita guia em `draft` e grava `submitted` direto,
pulando `pending`, apesar da docstring dizer `"(status: pending → submitted)"`.

```python
if guide.status not in ("draft", "pending"):
    return Response(..., status=400)
guide.status = "submitted"
```

Uma guia vira **"Enviada"** sem ter entrado em lote, sem validação contra o XSD da ANS e
sem ninguém tê-la declarado pronta. E `submitted` não é rótulo inofensivo: entra em
`_ACTIVE_GUIDE_STATUSES` (`services/glosa_safety.py:85`), contando como apresentada para a
checagem `duplicate` da cunha, e entra no denominador da taxa de glosa
(`docs/PLAN_SPRINT10.md:83`). Guia marcada sem envio real infla os dois.

A ordem 009 fez `draft → pending` ser ato explícito e auditado, e `pending → submitted`
acontecer no fechamento do lote. Este endpoint é a porta dos fundos que anula as duas.

**Quem chama, verificado:** um único lugar no frontend —
`frontend/app/(dashboard)/billing/guides/[id]/page.tsx:177`, o botão **"Enviar Guia"**,
exibido quando `canSubmit = status === 'draft' || status === 'pending'` (linha 304). Não há
outro chamador em todo o `frontend/`. No backend, cinco pontos de chamada em teste:
quatro em `test_guide_immutability.py` (126, 150, 231, 251) e um em `test_billing.py:397`.

### (b) `.claude/settings.local.json` versionado desde o primeiro commit

Está no repo desde `57de3bb` (Sprint 0), com **113 regras de permissão**. Pela convenção do
Claude Code, `settings.local.json` é o arquivo **pessoal da máquina** e o compartilhado é o
`settings.json`. Versionar o local faz todo clone herdar o allowlist de quem o criou —
entre as regras, `Bash(git push:*)`, `Bash(git commit:*)`, `Bash(docker exec:*)`,
`Bash(docker run:*)`, `Bash(docker cp:*)` e caminhos de outra máquina
(`Bash(ls /c/dev/healthos/.env*)`). Não há segredo no arquivo — são regras, não valores. O
problema é conceder permissão ampla por padrão, sem decisão de ninguém.

`.gitignore` já ignora `local_settings.py`, mas não este.

## Abordagem

### (a) O endpoint passa a exigir `pending`

1. **`backend/apps/billing/views.py`** — `submit` recusa `draft` com **400**
   (`code: "guide_not_ready"`), dizendo que a guia precisa ser declarada pronta antes e
   nomeando o endpoint `marcar-pronta`. Só `pending` transiciona.
2. A transição passa a ser **validada e auditada** como a irmã dela: move para
   `services/batch_lifecycle.py` como `marcar_enviada(*, guia, actor)`, ao lado de
   `marcar_pronta_para_envio`, com `select_for_update`, recusa tipada e `AuditLog`
   (`guide_submitted`). Hoje o registro é um `_write_audit` com a ação montada por
   f-string (`views.py:1314`), que não é consultável por ação como as outras.
3. **Frontend** (`billing/guides/[id]/page.tsx`) — o botão deixa de ser um só. Com
   `status === 'draft'`, mostra **"Declarar pronta"** (chamando `markGuideReady`, que já
   existe em `lib/glosa-safety.ts` desde a 009); com `status === 'pending'`, mostra
   **"Enviar Guia"**. O caminho de uma guia rascunho para enviada passa a exigir dois atos
   deliberados, cada um com sua linha no `AuditLog`.

### (b) O arquivo sai do versionamento

`git rm --cached .claude/settings.local.json`, entrada no `.gitignore`, e **nada mais
muda**: `.claude/settings.json` e `.claude/hooks/ponte-waiting.sh` continuam versionados
como estão — é por ali que o hook da Ponte vive. O arquivo continua existindo no disco de
quem já o tem; só deixa de viajar.

Se alguma das 113 regras for mesmo de equipe, ela se move **explicitamente** para o
`settings.json` — mas isso é decisão de política, então esta ordem **não move nenhuma**:
apenas para de distribuir o allowlist pessoal, e reporta a lista para você decidir.

## Teste que falha antes

- `test_guide_submit_requires_pending.py`: `submit` sobre `draft` devolve 400 nomeando o
  caminho certo, e a guia **não** muda de estado; sobre `pending` devolve 200, grava
  `submitted` e deixa linha `guide_submitted` no `AuditLog`. Hoje o primeiro caso devolve
  200 e grava `submitted` — falha por asserção, não por importação.
- Frontend: a tela mostra "Declarar pronta" para rascunho e "Enviar Guia" para pendente,
  e o fluxo de dois passos chega a `submitted`.
- **Os cinco pontos de chamada existentes recebem edição ADITIVA**, como na 009: um
  `POST /guides/{id}/marcar-pronta/` antes do `submit` que já afirmavam. Verifico com
  `git diff --numstat` que só há linhas adicionadas. Se algum exigir remover ou afrouxar
  asserção, **paro e reporto** — pode ser sinal de que a mudança está errada.
- Rede de proteção: `test_billing.py`, `test_glosa_safety.py` e `test_guide_immutability.py`
  passam sem nenhuma outra edição.

## Prova

1. Par antes/depois em container na lab, sha256 dos logs no ledger.
2. Gate completo antes de cada push: `ruff check`, `ruff format --check`, `lint-imports`,
   `mypy`, `tsc --noEmit`, `next lint`, `vitest`.
3. CI verde nos cinco jobs no tip.
4. Em staging, por comando, **lido do banco**: guia em `draft` recusada pelo `submit` (e
   ainda `draft`); depois declarada pronta e enviada, terminando `submitted` com as duas
   linhas de `AuditLog` (`guide_marked_ready`, `guide_submitted`).
5. Para (b): `git ls-files .claude/` deixa de listar o `settings.local.json`, `git check-ignore`
   confirma a regra, e `settings.json` + `ponte-waiting.sh` continuam listados.
6. Recibo `order-10` como **última** ação no tip — a regra que você fixou na 009.

## Risco

Muda contrato HTTP de um endpoint que o frontend usa. O frontend entra no mesmo changeset,
e a mudança é de um botão para dois — nenhum fluxo perde capacidade, ganha um passo
explícito. O item (b) não muda comportamento de código nenhum.

## Fora de escopo

Não move nenhuma das 113 regras para o `settings.json` (é decisão de política, vai como
relatório). Não mexe no fechamento de lote nem na cunha. Não toca nas guias e lotes já em
staging.


## Contrato de execução
- Trabalhe APENAS no branch `order/010-submit-e-settings-local`; NUNCA no main/master.
- Prove com o ledger: `maestro evidence --record --label order-10 -- <suíte>` no tip do branch.
- Direção vigente na criação: INTENT v5 (`.maestro/INTENT.md`) — o plano cita a seção da direção que autoriza esta ordem.
- Estourou Ask-First ou orçamento? PARE e reporte ao humano — não improvise.
- O aceite é do diretor: `maestro order --accept 010` (você não fecha a própria ordem).

## Aprovação

Aprovada pelo Imediato em 13/09, nas palavras dele:

> `submit` exige `pending` (400 nomeando `marcar-pronta`), transição auditada no service,
> frontend com dois atos explícitos; `settings.local.json` sai do versionamento **sem mover
> regra nenhuma** para o `settings.json` — a lista das 113 vem no relatório para eu decidir.
> Testes que falham antes. Nada para master.
accepted_at: 2026-09-13T07:25:24-03:00
accepted_session: desconhecido
accepted_tree: 02ae73beb501108edf5379c877cfaa23c6790451
accepted_intent: 5
