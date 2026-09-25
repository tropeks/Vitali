<!-- maestro-order v1
id: 024
ts: 2026-09-25T10:23:10-03:00
epoch: 1790342590
head: 1970434d3cbf3d71b51f6a562829d5372480f3ad
branch: order/024-whisper-fora-do-dpa
intent_version: 6
intent_hash: f6a0c0bc
author_session: desconhecido
-->
# Ordem 024 — Whisper sai do caminho ate constar no DPA: flag OFF de fabrica, consentimento negado vira 403, na frente das ordens do plano Jev


> **Direção:** INTENT v6, **§Prioridade 4** (compliance como critério de aceite: LGPD) e
> **§Limites**: "Flag de IA nasce **OFF** e não processa dado de saúde sem DPA assinado".
> Origem: `~/dev/spock/docs/PLANO-JEV-VITALI.md` §5, que pede esta ordem **na frente** das
> ordens do plano. Ela vai na frente da 025 e da 026 (as 024 e 025 do plano, renumeradas
> porque esta entrou antes delas).
>
> **Execução headless, prova pelo CI.** A forge **não roda** compose do Vitali (INTENT v6
> §Limites). Nenhuma chamada externa no CI: nada vai para Anthropic, OpenAI nem TypeSafe.
> Esta ordem não toca staging nem produção.

## O defeito, lido no código em 25/09

O áudio da consulta é voz (dado biométrico, LGPD art. 5º II) mais o que se diz nela: nome,
queixa e diagnóstico. O `WhisperGateway` (`apps/emr/services/whisper.py`) o manda **sem
possibilidade de desidentificação** para a OpenAI. O docstring do próprio módulo diz isso.

* **A flag nasce LIGADA:** `FEATURE_WHISPER_FALLBACK = env.bool(..., default=True)`
  (`vitali/settings/base.py:372`), e `.env.example:106` repete `True`. Foi decisão de gosto
  do Sprint 17 (`docs/PLAN_SPRINT17.md:239`), anterior ao INTENT.
* **O DPA não nomeia a OpenAI.** O texto que a clínica assina
  (`frontend/components/settings/DPASignModal.tsx`, §2 "Suboperador") nomeia **só a
  Anthropic, PBC**. `docs/DPA_TEMPLATE.md` não tem seção de suboperador. Mesmo assim, o
  gate `requires_ai_consent("whisper", ...)` (`apps/ai/consent.py`) aceita o **mesmo**
  `AIDPAStatus` assinado. A clínica autoriza um suboperador e o áudio vai para outro.
* **Consentimento negado responde 503.** `WhisperConsentError` herda de `WhisperError`, e o
  `ScribeTranscribeView` (`apps/emr/views_scribe.py`) captura `WhisperError` e devolve `503
  "Serviço de transcrição indisponível. Tente novamente mais tarde."`. Uma recusa de
  compliance aparece como falha transitória e convida a tentar de novo.

## O que a leitura de staging mostrou (25/09, só leitura)

Consulta em transação `read_only` no Postgres da lab, e leitura das settings efetivas do
contêiner `vitali-lab-django-1` (imagem `c320d6b`):

```
tenant demo     AIDPAStatus assinado em 2026-07-21 (com signatário)
tenant public   sem DPA
settings        FEATURE_WHISPER_FALLBACK=True · FEATURE_AI_SCRIBE=False · OPENAI_API_KEY vazia
demo            ai_aiusagelog: 0 linhas (nenhuma chamada de IA registrada)
```

**Nenhum áudio saiu.** O `ScribeTranscribeView` recusa antes do gateway porque
`FEATURE_AI_SCRIBE=False` (404), e sem chave da OpenAI a chamada nem teria para onde ir.
Mas o que está entre o áudio e a OpenAI é **uma variável de ambiente de outra feature**, não
o DPA. Ligar o Scribe e pôr a chave, os dois atos plausíveis de um piloto, mandaria o áudio
da clínica `demo` para um suboperador que ela não autorizou. Produção não existe.

## O trabalho

1. **Teste vermelho primeiro** (commit `test(...)` que **falha** no tip atual):
   * sem `FEATURE_WHISPER_FALLBACK` no ambiente, `settings.FEATURE_WHISPER_FALLBACK` é
     `False`;
   * com DPA assinado **e** as duas flags ligadas, `requires_ai_consent("whisper", ...)`
     **nega** com um motivo nomeado (`provider_not_in_dpa`), e o cliente da OpenAI **não é
     instanciado** (mock que falha se for chamado);
   * consentimento negado em `/scribe/transcribe/` responde **403** com o motivo, e não
     503. Falha real da API da OpenAI (rede, 5xx) continua 503.
2. **Flag OFF de fábrica:** `default=False` em `base.py`, e `FEATURE_WHISPER_FALLBACK=False`
   no `.env.example`, com comentário dizendo por quê e apontando esta ordem.
3. **A OpenAI sai do caminho até constar no DPA.** O gate passa a conferir o **provedor**,
   não só a feature:
   * uma lista explícita de suboperadores cobertos pelo DPA vigente, no código (por exemplo
     `DPA_SUBPROCESSORS = frozenset({"anthropic"})` em `apps/ai/consent.py`), com o motivo
     escrito e o caminho do texto do DPA;
   * cada feature declara o provedor (`whisper` → `openai`; `tuss`, `glosa` e `scribe` →
     `anthropic`);
   * provedor fora da lista → `ConsentResult(False, "provider_not_in_dpa")`, **antes** de
     qualquer outra checagem, e sem ler setting nem banco.

   Pôr a OpenAI na lista **não é desta ordem**. Exige mudar o texto do DPA, dar versão ao
   `AIDPAStatus` e fazer as clínicas assinarem de novo, e isso é a decisão D2 do Capitão no
   plano Jev.
4. **403 na recusa.** `WhisperConsentError` é tratada antes de `WhisperError` no
   `ScribeTranscribeView`, e responde 403 com `detail` e `reason`. Nenhum outro status muda.
5. **Frontend:** `frontend/components/emr/AudioRecorder.tsx` trata o 403 como "transcrição
   por áudio indisponível para esta clínica". Não oferece "tentar de novo" e não repete a
   chamada. Teste vitest para esse ramo.
6. **Docs:** a linha do `OPENAI_API_KEY` na tabela de variáveis de IA do `README.md` e o
   `docs/SECURITY.md` dizem que o Whisper está bloqueado por provedor até o DPA nomear a
   OpenAI.

## Prova exigida

* Commit vermelho **antes** do conserto, com o CI desse commit falhando nos testes novos.
* Job `Backend — Tests` e job `Frontend — Lint, Types & Unit` verdes no tip.
* Nenhum teste existente de `tuss`, `glosa` ou `scribe` muda de resultado: o gate de
  provedor só nega a OpenAI.
* **Recibo antes do merge:** PR aberto contra `onda0-perimetro-multitenant`, CI verde no tip,
  `maestro evidence --record --label order-24 -- gh run watch <run-id> --exit-status`.

## Ask-First

* Pôr qualquer provedor novo em `DPA_SUBPROCESSORS`, ou mudar o texto do DPA: pare e
  pergunte. É a D2 do Capitão.
* Mudar status HTTP de qualquer outra recusa de IA (`tuss`, `glosa`, `scribe`): pare e
  pergunte.
* Mexer em staging, inclusive para "desligar a flag lá": é deploy, e deploy vai por ship com
  gate.

## Fora desta ordem

* Versionar o `AIDPAStatus` e registrar a lista de suboperadores por assinatura (D2).
* Transcrição local (Whisper self-hosted) como alternativa: seria uma ordem de produto.
* As ordens do plano Jev (025 em diante).

## Contrato de execução
- Trabalhe APENAS no branch `order/024-whisper-fora-do-dpa`; NUNCA no main/master.
- Prove com o ledger: `maestro evidence --record --label order-24 -- <suíte>` no tip do branch.
- Direção vigente na criação: INTENT v6 (`.maestro/INTENT.md`) — o plano cita a seção da direção que autoriza esta ordem.
- Estourou Ask-First ou orçamento? PARE e reporte ao humano — não improvise.
- O aceite é do diretor: `maestro order --accept 024` (você não fecha a própria ordem).
