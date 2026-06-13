# Sprint 33: Pilot Onboarding & GTM → GA

## ⚠️ Pré-requisito

Sprints 27–32 concluídos (ops, enforcement, tooling, wedges Wave 1+2, compliance). Uma clínica piloto selecionada (decisão comercial do Romulo).

## Context (ler antes de começar)

- `docs/DEPLOY.md`, `docs/RUNBOOK.md`, `docs/USER_GUIDE.md`, `app/setup/` (wizard de first-tenant), `backend/apps/hr/`
- Estado: produção provisionável (S27), tenant enforcement ON (S28), wedges ligáveis (S30/31), compliance fechado (S32). Falta o processo repetível de colocar UMA clínica real para dentro e operar.

## Goal

Levar a primeira clínica piloto pagante de "contrato assinado" a "operando em produção com os wedges ligados" por um caminho repetível e documentado. Este é o GA.

## Planned Scope

### S33-01: Tenant Provisioning Playbook

- Documentar + scriptar (onde fizer sentido) a criação de um tenant de produção: schema, domínio/subdomínio, admin inicial, plano/módulos ativos, TLS.
- `scripts/provision_tenant.sh` (ou management command) idempotente que cria o tenant e roda `migrate_schemas` para ele.
- Checklist em `docs/DEPLOY.md`: do DNS ao primeiro login.

### S33-02: Onboarding Wizard Hardening

- Revisar `app/setup/` e o wizard de onboarding para o fluxo real da clínica: dados da empresa, primeiro admin, importação inicial de profissionais (via HR), configuração de convênios.
- QA do wizard fim-a-fim (usar a skill gstack /qa se disponível); corrigir o que travar um operador não-técnico.

### S33-03: Data Onboarding Tools

- Importadores para o dia 1 da clínica: profissionais/usuários (CSV), pacientes existentes (CSV mínimo viável), convênios/operadoras.
- Idempotentes, com relatório de erro por linha. Reusar padrões do Sprint 29.

### S33-04: Wedge Activation Runbook (por tenant)

- Procedimento operacional para ligar os wedges no tenant piloto na ordem certa: Wave 1 primeiro (sem dados), depois Wave 2 conforme os dados curados do tenant entram.
- Critérios de "ligar agora vs esperar" e kill-switch por wedge.

### S33-05: User Guide & Training Material

- Atualizar `docs/USER_GUIDE.md` para os fluxos reais (recepção, médico, farmácia, faturamento, admin).
- Material curto de treino (1 página por persona) — o que a clínica precisa saber no dia 1.

### S33-06: Pilot Success Metrics & Feedback Loop

- Definir e instrumentar as métricas de sucesso do piloto: nº de atendimentos, guias TISS geradas, glosas evitadas, alertas de wedge úteis vs ruído, no-shows reduzidos.
- Painel/relatório que o Romulo usa para acompanhar o piloto e fechar o caso de venda.

### S33-07: Go-Live Smoke & Rollback

- Smoke test de produção do tenant piloto (login, criar paciente, encounter, prescrição assinada, guia TISS, wedge dispara) usando `scripts/smoke_test.sh` adaptado.
- Plano de rollback documentado se algo crítico falhar no go-live.

## Acceptance Criteria

- `provision_tenant.sh` cria um tenant de produção idempotente, com migrations aplicadas.
- Wizard de onboarding passa QA fim-a-fim sem necessidade de engenheiro.
- Importadores de profissionais/pacientes/convênios funcionam com relatório de erro.
- Runbook de ativação de wedges por tenant documentado, com kill-switch.
- `docs/USER_GUIDE.md` atualizado + 1-pager por persona.
- Métricas de sucesso instrumentadas e visíveis.
- Smoke de produção verde no tenant piloto; rollback documentado.

## Verification Commands

```bash
cd backend && pytest apps/hr apps/core -q --reuse-db -k "provision or onboarding or import"
cd frontend && npx playwright test
COMPOSE_FILE=docker-compose.prod.yml scripts/smoke_test.sh
```

## Definition of GA (saída deste sprint)

Clínica piloto pagante operando em produção: tenant provisionado, equipe treinada, atendimentos reais sendo registrados, faturamento TISS rodando, Wave 1 de wedges ligado (Wave 2 conforme dados do tenant), métricas de sucesso sendo coletadas. **Vitali em produção real.**

## Out of Scope

- Escala multi-clínica / self-serve signup (pós-GA)
- Marketing site / billing automation de assinaturas (pós-GA)
- App mobile, telemedicina, BI Superset (Fase 3)
