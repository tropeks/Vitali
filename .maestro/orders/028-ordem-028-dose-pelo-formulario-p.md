<!-- maestro-order v1
id: 028
ts: 2026-09-26T07:18:11-03:00
epoch: 1790417891
head: 4da0bf39bf846cd3fd744761938cc27ea593c272
branch: order/028-formulario-doses-validado
intent_version: 6
intent_hash: f6a0c0bc
author_session: fc8b9303-d08c-4493-a28e-e7663838f69a
-->
# Ordem 028 — Dose pelo formulário público validado: importação com procedência, linha não validada só sinaliza, o LLM só explica o motor

> **Direção:** INTENT v6, **§Prioridade 3** (interceptação sobre registro: a cunha de dose) e
> **§Limites**: "Nenhum número clínico [...] inventado em código. Dado de dose [...] entra por
> importação validada ou por humano qualificado — nunca por hardcode". Também serve ao
> **§Resultado**: "motor determinístico autoritativo (o LLM só explica)".
>
> **Decisão do Capitão (26/09/2026):** a fonte do formulário de doses é **base pública
> (bulário da ANVISA e literatura) com validação por farmacêutico**.
>
> **Decisão do Diretor (26/09/2026), que fecha o Ask-First da compilação:** nenhum agente
> transcreve posologia, nem de bula nem de literatura. Esta ordem entrega o mecanismo e o
> importador de um arquivo **num formato definido por ela**, com procedência, versão e estado
> `nao_validado`. Quem compila o arquivo é o **farmacêutico que o Capitão vai contratar**.
> Sem esse arquivo, a tabela fica vazia, e o LLM já não fala de dose.
>
> **Parte do tip da `onda0` depois da 027.** Não comece antes de a 027 entrar na `onda0`.

## O que já existe (medido em 26/09, não redescubra)

- **Motor determinístico:** `apps/pharmacy/services/dose_checker.py` (puro, sem I/O) e
  `apps/emr/services/dose_safety.py` (orquestrador). Grava `AISafetyAlert(source="engine",
  alert_type="dose")` e `AuditLog`, atrás da flag por tenant `dose_safety`, que nasce OFF.
  - `OUT_OF_RANGE`, `WEIGHT_GATE` e `UNIT_MISMATCH` **bloqueiam**; `DATA_MISSING`,
    `ENGINE_ERROR` e `NO_RULE_MATCH` são advisory.
  - O gate (`prescription_safety_gate.py`) só bloqueia com linha `source="engine"`,
    `severity="contraindication"`, `status="flagged"`.
- **Formulário:** `MedicationFormulary` (1:1 com `Drug`) e `DoseRule` (a linha que carrega os
  números: banda, basis, idade, peso, via, `enforcement` block/advise).
- **Importação:** `apps/pharmacy/services/formulary_import.py`, compartilhada pelo comando
  `import_formulary` e pela UI de upload do farmacêutico. É idempotente e falha alto, com a
  chave natural do `DoseRule`.
- **Validação hoje:** `DoseRule.validated` é um booleano, com `validated_by` e `validated_at`.
  A action `DoseRuleViewSet.validate` grava `AuditLog dose_rule_validated`. **Não registra o
  CRF.**
- **Regra não validada hoje é inerte:** o motor filtra `validated=True`
  (`dose_checker.py:184`). Ela não bloqueia e **também não sinaliza**.
- **CRF:** o cadastro profissional (`apps/emr/models.py:458`) tem `council_type="CRF"`,
  `council_number` e `council_state`, únicos em conjunto.
- **LLM:** `prescription_safety.py` ainda pede ao Haiku `dose` como tipo próprio
  (`VALID_ALERT_TYPES`, prompt nas linhas 172–187). Desde a 026 ele grava só `source="llm"` e
  nunca bloqueia, mas **emite juízo de dose sem veredito do motor**.
- **Manifesto:** `scripts/catalogs/manifest.toml`, lido por `seed_catalogs` e
  `verify_catalogs`. `version = ""` falha por desenho: procedência não se inventa.

## O trabalho

**0. Teste vermelho antes de tudo** (commit `test(...) — FAILS here`, sozinho, com este
   arquivo):
   * uma regra importada e **não validada**, com dose fora da banda, gera alerta do motor
     **advisory** (`severity="caution"`, `status="flagged"`), com a mensagem dizendo que a
     regra ainda não foi validada por farmacêutico, e **não** entra no gate. Hoje ela é inerte:
     nenhum alerta;
   * validar uma regra **sem** CRF de farmacêutico é recusado. Hoje aceita qualquer usuário
     com permissão;
   * o `prescription_safety` não produz alerta `alert_type="dose"` do LLM quando o motor não
     deu veredito. Hoje produz.

   Pelo caminho real: importação pelo serviço, validação pela action e prescrição pelo
   orquestrador. Nada de SQL preparado pela fixture (lição da 021).

**1. Importação reproduzível da base pública, com procedência.**
   * `manifest.toml` ganha o catálogo `formulario_doses`, com `version` (a data da compilação
     da base), `sha256` do arquivo-fonte, `source_kind = "bulario_anvisa+literatura"` e
     `expected_rows`. `seed_catalogs` e `verify_catalogs` o carregam e conferem como os
     demais. `version` vazio ou `sha256` divergente falha alto, nomeando o catálogo.
   * O CSV ganha colunas de procedência **por linha**, obrigatórias:
     - `fonte_tipo` (`bula_anvisa` | `literatura`);
     - `fonte_ref`: para bula, o registro ANVISA e a data da bula; para literatura, a
       referência ou o DOI;
     - `fonte_trecho`: a posologia citada.

     Linha sem procedência é erro de importação. `notes` deixa de ser o lugar da citação.
   * **O formato do arquivo é contrato desta ordem.** Ele fica em
     `docs/FORMULARIO_DOSES.md` (colunas, tipos, unidades aceitas, regras de banda,
     procedência obrigatória, exemplo **sem números clínicos reais**), escrito para o
     farmacêutico que vai compilar o arquivo. O importador rejeita qualquer desvio do contrato
     nomeando a linha física e a coluna.
   * Nenhum número de dose é digitado no código nem nos testes que vão para o caminho real, e
     nenhum agente transcreve posologia. O arquivo-fonte fica fora do repositório (como as
     outras fontes), num diretório que o operador aponta com `--source-dir`. Os testes usam
     uma fonte marcada como sintética (cabeçalho `# sintetico: true`, valores
     reconhecidamente fictícios), que o importador e o manifesto recusam carregar fora de
     teste.
   * Enquanto o arquivo real não existe, o catálogo `formulario_doses` fica declarado no
     manifesto com `version = ""`. `seed_catalogs` o relata como **pendente de fonte**,
     nomeando quem a fornece, e não o carrega. A tabela fica vazia, e o motor dá
     `NOT_APPLICABLE`, como hoje.

**2. Toda linha nasce `nao_validado`, e o motor não bloqueia com ela.**
   * `DoseRule.validated` (bool) vira `status_validacao`, com `nao_validado` e `validado`.
     Migration com dados: `validated=True` sem CRF registrado **não** vira `validado`; volta
     a `nao_validado`, e a migration relata quantas linhas voltaram, por tenant.
   * **O motor usa a linha não validada para sinalizar, nunca para bloquear.** Quando a regra
     que casou está `nao_validado`, qualquer veredito que bloquearia (`OUT_OF_RANGE`,
     `WEIGHT_GATE`, `UNIT_MISMATCH`) sai **advisory**: caution, flagged, fora do gate. A
     mensagem é determinística e diz "regra ainda não validada por farmacêutico". Se houver
     regra validada e não validada para o mesmo caso, vence a validada.
   * **A linha validada exige quem validou, com CRF e data.** A validação grava:
     - `validado_por` (usuário);
     - `validado_crf_numero` e `validado_crf_uf`, um **retrato** do cadastro profissional no
       momento (o cadastro pode mudar depois; o registro não);
     - `validado_em`.

     Usuário sem cadastro profissional `CRF` ativo é recusado com 403 e código próprio.
     `AuditLog dose_rule_validated` passa a levar o CRF.
   * **Reimportação que muda número desvalida.** Se uma nova versão da base altera banda,
     teto ou unidade de uma linha `validado`, ela volta a `nao_validado`, grava `AuditLog
     dose_rule_invalidated_by_import` com a versão antiga e a nova, e o import relata a
     contagem. Linha que não mudou mantém a validação.

**3. O LLM perde o tipo `dose` e só explica o veredito do motor.**
   * `dose` sai de `VALID_ALERT_TYPES` e do prompt. Resposta do LLM com `type="dose"` é
     descartada e conta em log, sem virar alerta.
   * Quando o motor grava um veredito de dose que não seja `SAFE` nem `NOT_APPLICABLE`, o LLM
     recebe **esse veredito** (a banda calculada, o teto, a regra, o `status_validacao` e o
     motivo determinístico) e devolve só texto explicativo. O texto vive na **própria linha**
     (regra da 026): `source="llm"`, `alert_type="dose_explicacao"`, com FK `explica` para o
     alerta do motor. Ele nunca muda severidade, status nem gate, e não existe sem alerta do
     motor.
   * O caminho passa pelo mesmo gate de consentimento, scrub, `AIUsageLog` e teto mensal da 025.
     Flag OFF, sem DPA ou com o circuito aberto: nenhuma explicação, e o veredito do motor fica
     intacto.
   * Guarda por AST, como a da 026: nenhum código grava `AISafetyAlert` com `source="llm"` e
     `alert_type="dose"`.

## Prova exigida

* os três vermelhos ficam verdes, com o histórico mostrando o vermelho antes do conserto;
* `seed_catalogs` com o catálogo novo falha nomeando o catálogo quando `version` está vazio ou
  o `sha256` diverge, e carrega quando os dois conferem;
* linha sem procedência reprova o import inteiro (falha alto, sem import parcial);
* matriz do motor: {regra validada, não validada} × {`SAFE`, `OUT_OF_RANGE` block, `OUT_OF_RANGE`
  advise, `WEIGHT_GATE`, `UNIT_MISMATCH`}. Só "validada × bloqueante" entra no gate;
* validação: com CRF ativo, grava o retrato e o `AuditLog`; sem CRF, 403. Mudar o cadastro
  depois não altera o retrato;
* reimportação: número alterado desvalida e gera `AuditLog`; número igual mantém a validação;
* LLM: sem veredito do motor, nenhuma linha `dose*` do LLM; com veredito, uma linha
  `dose_explicacao` ligada ao alerta do motor, e o gate idêntico com e sem ela;
* **a receita não regride** (§Limites): `verify_revenue_chain` continua fechando, se algum
  catálogo de faturamento for tocado;
* recibo da suíte inteira na lab no tip, `maestro evidence --record --label order-28 --
  scripts/pytest.sh`; revisor antes do PR; PR contra a `onda0`, sem merge.

## Ask-First

* ~~Quem compila o arquivo-fonte~~: **decidido pelo Diretor em 26/09** (ver o topo). Se a
  execução esbarrar em qualquer ponto que pareça pedir um número clínico real (um teste, um
  default, um exemplo de documentação), pare e pergunte.
* Qualquer mudança na tabela de bloqueio do motor além de "não validado nunca bloqueia".
* Ligar a flag `dose_safety` em qualquer tenant, inclusive a `demo` do staging.
* Se a migration encontrar em staging uma `DoseRule` validada, pare e relate antes de rebaixá-la.

## Fora desta ordem

* Compilar a base (é do farmacêutico contratado); importar em staging; deploy.
* Interação medicamentosa e alergia (cunha própria, `allergy_safety`).
* Porta de julgamento do plano Jev e decisões D1–D3.

## Contrato de execução
- Trabalhe APENAS no branch `order/028-formulario-doses-validado`; NUNCA no main/master.
- Prove com o ledger: `maestro evidence --record --label order-28 -- <suíte>` no tip do branch.
- Direção vigente na criação: INTENT v6 (`.maestro/INTENT.md`) — o plano cita a seção da direção que autoriza esta ordem.
- Estourou Ask-First ou orçamento? PARE e reporte ao humano — não improvise.
- O aceite é do diretor: `maestro order --accept 028` (você não fecha a própria ordem).
accepted_at: 2026-09-26T15:38:35-03:00
accepted_session: desconhecido
accepted_tree: 51927b416628832808a1b10dd32781dfd474c542
accepted_intent: 6
