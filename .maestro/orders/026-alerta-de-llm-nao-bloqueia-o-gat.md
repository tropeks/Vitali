<!-- maestro-order v1
id: 026
ts: 2026-09-25T10:23:11-03:00
epoch: 1790342591
head: 1970434d3cbf3d71b51f6a562829d5372480f3ad
branch: order/026-alerta-llm-nao-bloqueia
intent_version: 6
intent_hash: f6a0c0bc
author_session: desconhecido
-->
# Ordem 026 — Alerta de LLM nao bloqueia o gate, e override de dose e alergia deixa trilha


> **Direção:** INTENT v6, **§Prioridade 3** (interceptação sobre registro), **§Prioridade 4**
> e **§Fora de escopo** ("toda cunha de IA é soft-stop com override auditado"). Origem:
> `~/dev/spock/docs/PLANO-JEV-VITALI.md` §4, **ordem 025 do plano**, renumerada para 026
> porque a ordem do Whisper (024) entrou na frente.
>
> **Depende da 025.** Parte de `onda0` com a 025 mesclada. Se não estiver, pare.
>
> **Execução headless, prova pelo CI.** A forge **não roda** compose do Vitali (INTENT v6
> §Limites). Nenhuma chamada externa no CI: nada vai para Anthropic, OpenAI nem TypeSafe.
> Esta ordem não toca staging nem produção.

## O defeito, lido no código em 25/09

* **Clobber latente.** `AISafetyAlert` tem `unique_together` em `(prescription_item,
  alert_type, source)`. O modelo separa o veredito do motor determinístico
  (`source="engine"`) do alerta do LLM (`source="llm"`). Mas a task do LLM
  (`apps/emr/tasks.py:81`) faz `update_or_create(prescription_item=..., alert_type=...)`
  **sem `source`** no filtro. Quando há linha de engine do mesmo tipo, o LLM sobrescreve o
  veredito do motor, e pode apagar `override_reason`/`acknowledged_at` ou fazer um alerta de
  LLM decidir o gate. Isso contradiz o INTENT: "motor determinístico autoritativo; o LLM só
  explica". Hoje está inalcançável, porque o `prescription_safety` só liga depois da 025.
  Por isso esta ordem vem logo depois dela.
* **Override sem trilha.** O override da glosa grava `AuditLog` (`glosa_alert_overridden`,
  ordem 007). O override de dose e o de alergia não gravam: o endpoint
  `acknowledge-alert` (`apps/emr/views_safety.py:187`) chama `AISafetyAlert.acknowledge`
  (`apps/emr/models.py:1993`), que só salva os campos, e o registro fica no `logger`. Os
  serviços `dose_safety` e `allergy_safety` gravam `AuditLog` quando o alerta é levantado
  ou preservado, mas não no ato do override. O flywheel "alerta → override →
  desfecho" do INTENT fica sem a peça do meio nas duas cunhas clínicas.

## O trabalho

1. **Teste vermelho primeiro:**
   * uma linha de `source="engine"` e uma de `source="llm"` do **mesmo** `alert_type` no
     mesmo item: rodar a task do LLM deixa a linha de engine **intacta** (severidade, status
     e override) e **não muda** o resultado do gate de sign/dispense;
   * o override de dose e o override de alergia gravam `AuditLog`, com ator, alerta, motivo
     e tenant, no mesmo formato do `glosa_alert_overridden`.
2. **O conserto:** `update_or_create(..., source="llm", ...)` na task, e mais nada no
   caminho do LLM. Os endpoints de override de dose e alergia gravam o `AuditLog` na mesma
   transação do override.
3. **Guarda:** um teste que varre os `update_or_create` e `get_or_create` de `AISafetyAlert`
   no código e reprova os que não fixam `source`, para o próximo gerador não repetir isso.

## Prova exigida

* Commit vermelho antes do conserto, com o CI dele falhando nos testes novos.
* `Backend — Tests` verde no tip. Nenhuma asserção existente de dose, alergia ou glosa foi
  afrouxada.
* O override aparece no `AuditLog`, e a trilha de leitura (ordens 016 a 019) continua com
  **0 rotas sem cobertura**.
* **Recibo antes do merge:** `maestro evidence --record --label order-26 -- gh run watch
  <run-id> --exit-status`.

## Ask-First

* Mudar a semântica do gate (quem bloqueia e com que status): pare e pergunte.
* Migration em `AISafetyAlert`: não deve ser necessária. Se for, pare e passe pelo
  especialista em PostgreSQL antes.

## Fora desta ordem

* Formulário de dose validado por farmacêutico (D-T1): é o conserto real do
  `prescription_safety`, e é ordem de backlog.
* Qualquer coisa do Jev.

## Contrato de execução
- Trabalhe APENAS no branch `order/026-alerta-llm-nao-bloqueia`; NUNCA no main/master.
- Prove com o ledger: `maestro evidence --record --label order-26 -- <suíte>` no tip do branch.
- Direção vigente na criação: INTENT v6 (`.maestro/INTENT.md`) — o plano cita a seção da direção que autoriza esta ordem.
- Estourou Ask-First ou orçamento? PARE e reporte ao humano — não improvise.
- O aceite é do diretor: `maestro order --accept 026` (você não fecha a própria ordem).
