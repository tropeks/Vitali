# Sprint 31: Wedge Go-Live Wave 2 (com dados curados)

## ⚠️ Pré-requisito humano (bloqueante)

Antes de executar este sprint, os dados de referência DEVEM estar carregados e validados (resultado do tooling do Sprint 29):

- **Dose:** farmacêutico validou `MedicationFormulary`/`DoseRule` (decisão **D-T1**) — regras com `validated=True`
- **Glosa clínica:** tabela TUSS oficial importada (`import_tuss`) + atributos de contrato/teto do estabelecimento
- **Alergia:** `AllergenClass`/`DrugInteraction` carregados e marcados ativos
- **Controlled:** `min_refill_interval_days` configurado por droga controlada

Se algum não estiver pronto, ligar apenas os que estiverem e deixar os demais documentados como pendentes. **Nunca inventar os números para destravar.**

## Context (ler antes de começar)

- `docs/AI-NATIVE-WEDGES.md`, `backend/apps/pharmacy/`, `backend/apps/billing/services/glosa_checker.py`
- Wedges deste wave: **dose_safety**, **glosa_safety** (parte clínica), **allergy_safety** (cross-reactivity/interaction), **controlled_safety** (refill signal)
- Sprint 30 já validou o padrão closed-loop; aqui aplicamos aos wedges com dados.

## Goal

Ligar os 4 wedges que dependem de dados curados, agora que os dados existem, com os soft-stops nos pontos certos do fluxo clínico e a alça de feedback ativa. Este é o diferencial de produto (a "cunha de dose").

## Planned Scope

### S31-01: Dose-Safety Go-Live (a cunha principal)

- Habilitar `dose_safety` por tenant; soft-stop nos 3 portões: `Prescription.sign`, `DispenseView`, beira-leito.
- Confirmar que apenas `DoseRule` validadas participam; regras não validadas são ignoradas.
- `DoseSafetyModal` mostra a regra, a fonte e permite override com justificativa (gravada).
- Golden tests com as regras validadas reais (não fixtures inventadas).

### S31-02: Glosa-Interception Clinical Checks Go-Live

- Ativar os checks clínicos do `GlosaChecker` que dependem de `TUSSCode`/contrato (antes inertes), além dos de alto valor já ativos.
- Soft-stop por guia em `TISSBatchViewSet.close`; explicar o motivo do risco.
- Validar contra guias reais de staging; medir falso-positivo.

### S31-03: Allergy Cross-Reactivity & Interaction Go-Live

- Ativar cross-reactivity (`AllergenClass`) e drug-interaction (`DrugInteraction`) agora que há dados ativos.
- Match direto continua; cross/interaction adicionam camada. Soft-stop na prescrição com override.

### S31-04: Controlled-Substance Diversion Refill Signal

- Ativar o refill signal usando `min_refill_interval_days` configurado.
- Sinais cumulativos + refill cedo geram alerta de diversion (advise + audit).

### S31-05: Cross-Wedge Override Analytics

- Consolidar analytics de override/desfecho dos 7 wedges (Wave 1 + 2) num painel; é a matéria-prima do flywheel e do pitch de moat.
- Documentar como cada override melhora a próxima predição.

### S31-06: Full Soak + Go-Live Doc

- Soak dos 4 wedges em staging; atualizar `docs/AI-NATIVE-WEDGES.md` marcando cada wedge como "Live-ready" com seu pré-requisito de dados cumprido.

## Acceptance Criteria

- Dose-safety enforça nos 3 portões usando só regras validadas; override exige justificativa e é auditado.
- Glosa clínica e allergy cross/interaction ativam apenas com dados marcados; degradam se faltarem.
- Controlled refill usa config real; sem config → sem esse sinal (não inventa).
- Painel de override analytics cobre os 7 wedges.
- `docs/AI-NATIVE-WEDGES.md` reflete o estado real de prontidão.

## Verification Commands

```bash
cd backend && pytest apps/pharmacy apps/billing -q --reuse-db -k "dose or glosa or allergy or controlled"
cd frontend && npx playwright test e2e/clinical-journey.spec.ts
cd frontend && npm run build
```

## Out of Scope

- Carregar os dados (pré-requisito humano, antes do sprint)
- Per-item glosa labels (bloqueado por ANS TISS 4.02+) — Fase 3
