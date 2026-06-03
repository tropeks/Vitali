# Glosa-Interception Wedge — Plano Travado

> **Tese (AI-native):** o segundo wedge do padrão **Observe→Predict→Intercept→Learn**
> ([[VISION-AI-NATIVE]]), agora na espinha **operacional/financeira**: interceptar a
> **glosa (negativa de pagamento)** ANTES de a guia/lote ser enviado à operadora —
> não documentá-la depois no relatório de fim de mês.

## Por que glosa, por que agora (office-hours)

- **Demanda real:** glosa é vazamento crônico e quantificável de receita do
  estabelecimento — a "dor operacional" que o fundador citou como central.
- **Status quo:** incumbentes mandam a guia e **descobrem a glosa semanas depois**
  no retorno. Registro passivo. Vitali intercepta no clique de fechar o lote.
- **Wedge mais estreito:** os checks determinísticos de maior valor **não exigem
  dado novo** — preço contratado (`PriceTableItem.negotiated_value`),
  `authorization_number`, status de envio e cobertura de tabela **já existem**.
  Logo, ao contrário da dose (gate D-T1 do farmacêutico), o PR 1 já entra com
  checks REAIS.
- **Flywheel já fiado:** `apps.ai.GlosaPrediction` (predição LLM na edição da guia)
  + `retorno_parser` que faz `update(was_denied=True)` ao processar o retorno. Já
  temos rótulo verdade-terreno chegando. Falta o motor determinístico + o portão.

## Arquitetura — espelha o wedge de dose (padrão já provado)

| Camada de dose | Análoga de glosa |
|---|---|
| `DoseChecker` (motor puro, determinístico) | **`GlosaChecker`** (`apps/billing/services/glosa_checker.py`) |
| `DoseCheckService` (orquestra, persiste, gate) | **`GlosaSafetyService`** (`apps/billing/services/glosa_safety.py`) |
| `AISafetyAlert(source=engine\|llm)` | reusa o split: motor=engine, LLM existente=llm (ver decisão A-1) |
| soft-stop 409 em `PrescriptionViewSet.sign` | soft-stop 409 em **`TISSBatchViewSet.close()`** (já é atômico + lock) |
| flag `dose_safety` (default OFF) | flag **`glosa_safety`** (default OFF) |
| flywheel via `AuditLog` + verdict | flywheel via `GlosaPrediction.was_denied` (já existe) + `AuditLog` |

Princípio idêntico: **o motor determinístico é autoritativo** (decide bloquear);
o LLM apenas explica/prioriza. Fail-safe: na dúvida, alerta — não verde silencioso.

## Sequência de 3 PRs

### PR G1 — motor determinístico + soft-stop POR-GUIA + flywheel (backend)
**Zero dado de referência novo.** 4 checks com o schema atual, cada um num código
de glosa ANS real. **Severidade default revisada (eng-review) pra não crying-wolf:**

1. **Duplicidade** *(default `block`)* — mesma `encounter`+TUSS já em outra guia em
   status ativo. **Concorrência:** o `TISSBatch.close()` só trava as guias DO lote;
   pra pegar duplicata entre guias/lotes distintos a checagem **trava o `Encounter`**
   (`select_for_update`) — senão dois closes concorrentes passam ambos. → "procedimento
   já apresentado".
2. **Preço obsoleto/sobrescrito** *(default `advise`)* — ⚠️ NÃO é "valor vs contrato"
   (o `unit_value` já é resolvido da tabela na criação da guia — comparar seria teatro).
   O risco real: o snapshot da guia **diverge da versão ATUALMENTE vigente** da
   `PriceTable` (tabela mudou após criar a guia) **ou** houve override manual do
   faturista. Alerta, não bloqueia (override manual pode ser legítimo: coparticipação).
3. **Procedimento não tabelado** *(default `block`)* — linha TUSS sem `PriceTableItem`
   na tabela vigente da operadora → "não coberto/não tabelado".
4. **Completude estrutural** *(default `advise`)* — faltando `authorization_number`,
   `insured_card_number`, `competency`, `cid10_codes`. ⚠️ Alto risco de falso-positivo:
   muitos `consulta`/`sadt` NÃO exigem autorização (depende da regra do convênio/TUSS) →
   por isso **advise**, nunca block por padrão.

**Gate POR-GUIA (não por lote):** avaliar cada guia (no add-à-guia e re-check no
`close()` sob lock). O `close()` retorna **409 listando SÓ as guias com alerta
bloqueante não reconhecido** — o faturista remove/reconhece essas guias e fecha o
resto. NÃO segura o lote inteiro por uma guia ruim. Override-com-justificativa por
guia (espelha o `enforcement`/ack da dose v2). Partial-close automático = G2. Flag OFF.

### PR G2 — interceptação no frontend (UX)
Modal no fechar-lote: badge de risco por guia (alto/médio), motivo + recomendação por
linha, override-com-justificativa por guia, retry. Espelha o `DoseSafetyModal`.

### PR G3 — checks que exigem dado novo (LOCKED pós eng-review Gemini → 4 sub-PRs)
**Tudo `advise` por padrão** (dado inicial esparso/com typo; nunca bloquear o `close()`).
Dado clínico/ANS/contrato é **verdade externa** (análogo ao D-T1): schema+check shipam,
valores vêm de import ANS / config do estabelecimento — **nunca inventados em código**.

- **G3a — Backfill (PRIORIDADE MÁXIMA, corrige o flywheel):** o `retorno_parser.py`
  hoje grava glosa nível-guia com `guide_item=None`; o backfill `was_denied` então
  marca TODOS os itens da guia (1 glosado de 5 → 5 rotulados) — **envenena o
  ground-truth**. Fix: drill-down em `<procedimentosRealizados>`/`<glosasProcedimento>`
  → mapear `Glosa`→`TISSGuideItem`; `was_denied=True` só quando o `Glosa` casa o item;
  glosa nível-guia (ex. sem assinatura) NUNCA é espalhada pros itens. Pura lógica, sem dado novo.
- **G3b — Compat clínica:** `core.TUSSCode` (schema público — regras ANS são universais)
  ganha `age_min_days`/`age_max_days`/`sex_allowed`(M/F/B)/`cid10_whitelist`; `import_tuss`
  popula do ANS (não inventar). Check usa `Patient.birth_date`/`gender` + CID da guia → `advise`.
- **G3c — Teto por procedimento:** `PriceTableItem.max_per_procedure` (Integer). Check
  local em memória (`item.quantity > max`), **sem query**. Agregado mensal **adiado**
  (race + custo no `close()`). `advise`.
- **G3d — Autorização:** flag `PriceTableItem.requires_authorization` (default False) →
  engine só checa quando True. Modelo `Authorization` (tenant: patient/provider/tuss?/
  valid_from/valid_until/status/number). Passa se `guide.authorization_number` preenchido
  OU existe `Authorization` aprovada e vigente. `advise`.

## Decisões travadas (revisadas pós eng-review Gemini)

- **A-1 — Modelo de alerta (REVISTO):** **NÃO** reusar `GlosaPrediction` (é artefato
  LLM, gerado na edição da guia, ligado a `AIUsageLog` — misturar verdict determinístico
  ali conflita ciclos de vida e arrisca clobber). Criar **`GlosaSafetyAlert`** dedicado
  (espelha `AISafetyAlert`: `guide`+`guide_item` FK, `check_code`, `severity` block|advise,
  `source=engine`, `status`, `acknowledged_by`/`override_reason`/`acknowledged_at`,
  `unique_together` p/ evitar clobber na reavaliação). `GlosaPrediction` fica **puro** pro
  flywheel LLM.
- **A-2 — Gate (REVISTO):** avaliação **por-guia** (no add-à-guia + re-check no
  `TISSBatchViewSet.close()` sob lock). 409 lista **só as guias** com alerta bloqueante
  não reconhecido — não bloqueia o lote inteiro. Duplicidade **trava o `Encounter`**.
- **A-3 — Fail posture:** motor lança → advisory (fail-open), igual à dose (D-T3). E
  default conservador: só duplicidade/não-tabelado bloqueiam; resto avisa.
- **A-4 — Multi-tenant:** tudo per-tenant; TUSS é schema público (FK app-layer).
- **A-5 — Flywheel preciso (NOVO):** o backfill `was_denied` do `retorno_parser` deve
  mapear a glosa no nível **`guide_item`/TUSS** (o `Glosa` já aponta `guide_item`), não
  marcar todas as predições da guia — senão injeta falso-positivo no ground-truth (uma
  guia com 5 itens, 1 glosado). Vale tanto pro `GlosaSafetyAlert.was_denied` quanto pra
  corrigir o `GlosaPrediction` (hoje guia-level) — este último pode virar item-level no G3.

## Fora de escopo (agora)
Retreino do LLM, dashboard de acurácia, tetos agregados mensais, e o modelo de
`Authorization` (vão pro G3). Nenhuma submissão real à operadora muda — o gate é
interno, antes do envio.
