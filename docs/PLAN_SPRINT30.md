# Sprint 30: Wedge Go-Live Wave 1 (sem dados curados)

## Context (ler antes de começar)

- `docs/AI-NATIVE-WEDGES.md`, `docs/VISION-AI-NATIVE.md`
- Wedges deste wave (100% derivados de histórico do próprio tenant, sem dados externos a curar):
  - **no_show_prediction** — risco de falta via histórico de agendamentos
  - **stockout_safety** — SMA 30d sobre `StockMovement` (advise-only)
  - **deterioration** (NEWS2) — algoritmo publicado, escalation é config operacional
- Padrão de todo wedge: Observe → Predict → Intercept → Learn. Flag por tenant (`FeatureFlag`). Engine determinístico; LLM só explica.
- Depende de S27 (staging sólido) para validar com tráfego realista.

## Goal

Ligar com segurança os 3 wedges que não dependem de dados curados, em staging primeiro, com telemetria de qualidade e a alça de feedback (flywheel) funcionando. Provar o padrão closed-loop end-to-end antes do Wave 2.

## Planned Scope

### S30-01: No-Show Prediction Go-Live

- Habilitar `no_show_prediction` por tenant em staging; superfície proativa em `/faltas` e badge no front-desk.
- Validar o cálculo de risco contra um dataset sintético de histórico; documentar a faixa de score e o significado.
- Feedback loop: registrar desfecho real (compareceu/faltou) alimentando o flywheel (`AuditLog`/sinal de treino).

### S30-02: Stockout Advisory Go-Live

- Habilitar `stockout_safety` (advise-only — NUNCA bloqueia dispensa) em staging.
- Verificar SMA 30d com `StockMovement` real de staging; alertas em `StockRiskView`.
- Degradação graciosa quando não há config de `lead_time`/`safety_stock` (advise genérico).

### S30-03: Deterioration (NEWS2) Go-Live

- Habilitar deterioration; validar o cálculo NEWS2 contra casos de teste publicados (golden tests com escores conhecidos).
- Escalation routing configurável por tenant (quem é notificado); nunca bloqueia o registro de vitals.
- Painel `/deterioracao` mostrando escores e tendência.

### S30-04: Wedge Telemetry & Quality Panel

- Métrica unificada por wedge: nº de alertas, taxa de override, latência da engine, "zero-result rate".
- Painel admin (reusar `ReadinessPanel`/`KpiTile`) para o operador ver se o wedge está agregando valor ou só ruído.
- Threshold de ruído documentado: se override rate > X%, recomendar reavaliar config.

### S30-05: Flywheel Wiring Verification

- Garantir que override do clínico + desfecho são persistidos como sinal de treino (não só log).
- Teste end-to-end: alerta → override → desfecho → sinal gravado e consultável.

### S30-06: Staging Soak + Runbook

- Rodar os 3 wedges em staging por um período de soak; documentar em `docs/AI-NATIVE-WEDGES.md` o procedimento de go-live por tenant (checklist) e como desligar (kill switch).

## Acceptance Criteria

- Os 3 wedges ligáveis por tenant via `FeatureFlag` em staging, sem afetar tenants com flag OFF.
- NEWS2 passa golden tests; stockout nunca bloqueia dispensa; no-show não altera fluxo de agendamento (só informa).
- Telemetria por wedge visível no painel; flywheel grava sinais (teste prova).
- Procedimento de go-live e kill-switch documentados.

## Verification Commands

```bash
cd backend && pytest apps/emr apps/pharmacy -q --reuse-db -k "deterioration or news2 or stockout or no_show"
cd frontend && npx playwright test e2e/clinical-journey.spec.ts
cd frontend && npm run build
```

## Out of Scope

- Wedges que exigem dados curados (dose, glosa clínica, allergy cross, controlled) → Sprint 31
- Ligar em produção (acontece no piloto, Sprint 33)
