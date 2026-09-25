<!-- maestro-order v1
id: 025
ts: 2026-09-25T10:23:10-03:00
epoch: 1790342590
head: 1970434d3cbf3d71b51f6a562829d5372480f3ad
branch: order/025-ia-atual-para-de-mentir
intent_version: 6
intent_hash: f6a0c0bc
author_session: desconhecido
-->
# Ordem 025 — A IA atual para de mentir: consent gate do CID-10, flags lidas de onde o DPA grava, prompt e parser do TUSS concordam


> **Direção:** INTENT v6, **§Prioridade 4** (compliance como critério de aceite) e
> **§Limites** ("Flag de IA nasce OFF e não processa dado de saúde sem DPA assinado").
> Origem: `~/dev/spock/docs/PLANO-JEV-VITALI.md` §4, **ordem 024 do plano**, renumerada
> para 025 porque a ordem do Whisper (024) entrou na frente dela. Onda 0 do plano:
> consertar a IA atual antes de medir qualquer coisa contra ela.
>
> **Depende da 024.** Esta ordem parte de `onda0` com a 024 mesclada, porque as duas mexem
> em `apps/ai/consent.py`. Se a 024 não estiver mesclada, pare.
>
> **Execução headless, prova pelo CI.** A forge **não roda** compose do Vitali (INTENT v6
> §Limites). Nenhuma chamada externa no CI: nada vai para Anthropic, OpenAI nem TypeSafe.
> Esta ordem não toca staging nem produção.

## O defeito, lido no código em 25/09

A IA generativa atual está quebrada ou inalcançável em três pontos, e um deles abriria
vazamento se fosse consertado na ordem errada:

* **CID-10 sem gate.** `CID10Suggester.suggest` (`apps/ai/services_cid10.py:162`) não passa
  por `requires_ai_consent`, não passa por `scrub_for_llm` e não grava `AIUsageLog`. Hoje
  está inalcançável porque lê `TenantAIConfig.ai_cid10_suggest`, que **não existe** no
  model (os campos são `ai_tuss_enabled` e `ai_glosa_prediction_enabled`). Consertar a flag
  primeiro abriria o caminho de PHI para a Anthropic sem gate.
* **Flags lidas do lugar errado.** O `DPASigningService` (`apps/core/services/dpa.py:30`)
  grava `FeatureFlag` para `ai_scribe`, `ai_tuss`, `ai_prescription_safety` e `ai_cid10`.
  O CID-10 e o `PrescriptionSafetyChecker` (`apps/emr/services/prescription_safety.py:118`)
  leem `getattr(TenantAIConfig, ...)` com default `False`: nunca ligam. Em staging, a
  clínica `demo` tem `ai_cid10` e `ai_prescription_safety` desligados no `FeatureFlag`
  (leitura de 25/09), então o conserto não liga nada sozinho.
* **TUSS sempre degradado.** O prompt semeado (`seed_prompt_templates`) pede um array com
  `tuss_code`, e o parser (`apps/ai/services.py:247`) espera `{"suggestions": [{"code":
  ...}]}`. Toda resposta real cai no ramo degradado.
* **`run_llm_task`** (`apps/ai/tasks.py:19`): wrapper genérico de Celery sem consent gate,
  sem scrub e **sem nenhum chamador**. É uma porta sem gate esperando o primeiro uso.

## O trabalho, nesta ordem

1. **Teste vermelho primeiro**, um por defeito, **sem fixture feita à mão** para a condição
   medida (lição da 021):
   * o CID-10 com DPA ausente **não** chama o gateway, e com DPA assinado chama **com**
     texto já passado por `scrub_for_llm` e grava `AIUsageLog`;
   * o CID-10 e o `prescription_safety` leem o `FeatureFlag` que o `DPASigningService`
     grava: assinar o DPA pelo serviço real, ligar a flag pelo caminho real e só então
     afirmar;
   * o parser do TUSS aceita a resposta **no formato que o template semeado pede**. O teste
     carrega o template pelo `seed_prompt_templates` real, não por string copiada;
   * `run_llm_task` não existe mais (import falha).
2. **Gate antes de flag:** o CID-10 ganha `requires_ai_consent` (feature nova `cid10`,
   provedor `anthropic`, na tabela da 024), `scrub_for_llm` e `AIUsageLog` **no mesmo commit
   ou antes** do conserto da flag. O histórico do branch tem de mostrar essa ordem.
3. **Flags:** CID-10 e `prescription_safety` passam a ler `FeatureFlag` (o mesmo
   `tenant_has_feature` que o resto do sistema usa). O atributo fantasma de
   `TenantAIConfig` sai do código.
4. **TUSS:** prompt e parser passam a concordar. Escolha **um** formato, o do parser ou o do
   template, e mude o outro. Se o template semeado mudar, a mudança vai por migration de
   dados ou pelo comando de seed, idempotente.
5. **`run_llm_task` sai.**

## Prova exigida

* Um teste vermelho por defeito, **antes** do conserto, com o CI do commit vermelho
  falhando neles.
* O gate recusa quando o DPA está ausente, para CID-10 e `prescription_safety`, com o
  motivo nomeado.
* Nenhuma chamada externa no CI: o gateway é substituído por dublê que falha se for chamado
  fora do caso esperado.
* **Guarda da receita** (INTENT v6 §Limites): os testes de `verify_revenue_chain` e de glosa
  continuam verdes sem editar asserção.
* **Recibo antes do merge:** `maestro evidence --record --label order-25 -- gh run watch
  <run-id> --exit-status` com o CI verde no tip.

## Ask-First

* Ligar qualquer flag de IA em qualquer ambiente: pare. Esta ordem conserta o caminho, não
  liga nada.
* Mudar o texto clínico do prompt além do formato de saída: pare e pergunte.

## Fora desta ordem

* Qualquer coisa do Jev/TypeSafe: porta de julgamento, `AIDecisionLog` e eval (ordens
  seguintes do plano).
* O clobber de alerta e a trilha do override: ordem 026.

## Contrato de execução
- Trabalhe APENAS no branch `order/025-ia-atual-para-de-mentir`; NUNCA no main/master.
- Prove com o ledger: `maestro evidence --record --label order-25 -- <suíte>` no tip do branch.
- Direção vigente na criação: INTENT v6 (`.maestro/INTENT.md`) — o plano cita a seção da direção que autoriza esta ordem.
- Estourou Ask-First ou orçamento? PARE e reporte ao humano — não improvise.
- O aceite é do diretor: `maestro order --accept 025` (você não fecha a própria ordem).
