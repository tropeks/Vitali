# Sprint 28: Tenant Enforcement + Security Hardening

> **STATUS (2026-06-12): código entregue para S28-01, S28-04, S28-05 (sink) + testes;
> verificação dependente de stack/browser/staging PENDENTE (host sem Docker).**
> - S28-01 ✅ `backfill_tenant_memberships --report` (lista emails por tenant).
> - S28-02 ⏳ enforcement já estava implementado e robusto (`tenant_auth.py`); falta
>   rodar a suíte de regressão A↔B com pytest (precisa DB).
> - S28-03 ⏳ go-live da flag em staging — documentado em `TENANT_MIGRATIONS.md`;
>   execução exige staging.
> - S28-04 ✅ MFA obrigatório para admin/médico/dentista + grace de enrolamento
>   (`MFA_REQUIRED_ROLES`, `MFA_GRACE_PERIOD_DAYS`); testes unitários escritos.
> - S28-05 ⚠️ PARCIAL: coletor de violações CSP (`report-uri`) entregue; **flip para
>   enforcing NÃO feito** — Next.js exige nonce antes de remover inline; precisa QA de
>   browser. Mantido report-only.
> - S28-06 ⏳ teste de regressão de segurança consolidado — pendente (precisa DB).
> Verificação a rodar onde houver Docker: `pytest apps/core`, E2E com flag ON,
> `npm run build`, e QA de browser para CSP.

## Context (ler antes de começar)

- `docs/SECURITY.md`, `docs/TENANT_MIGRATIONS.md`
- `backend/apps/core/` — modelos `Tenant`, `User`, `Role`, `UserTenantMembership`, `AuditLog`; middleware de tenant; `FeatureFlag`
- `backend/apps/core/tests/test_tenant_membership.py`, `test_mfa.py`
- Estado: Model B (tenant membership binding) COMPLETO — PRs #106–109 merged. Flag `ENFORCE_TENANT_MEMBERSHIP` default **OFF**. Go-live = rodar `backfill_tenant_memberships` e setar a flag ON. MFA implementado (`pyotp`), enforcement é Phase 2 (grace 7d). CSP report-only.

## Goal

Virar a chave do isolamento de tenant de "permissivo" para "enforçado" com segurança (backfill verificado, rollback claro), e fechar os itens de hardening que faltam para operação real (MFA enforced para papéis sensíveis, CSP enforcing).

## Planned Scope

### S28-01: Backfill Verification & Dry-Run

- Garantir que o management command `backfill_tenant_memberships` tem modo `--dry-run` que reporta: quantos users sem membership, quantos seriam criados, conflitos.
- Adicionar `--report` que lista por tenant os users afetados.
- Teste: a partir de um estado sem memberships, dry-run não escreve; run real cria exatamente os esperados; idempotente (rodar 2x não duplica).

### S28-02: Enforcement Rollout Safety

- Confirmar que com `ENFORCE_TENANT_MEMBERSHIP=ON` um user sem membership recebe 403 consistente (não 500, não vazamento de dados de outro tenant).
- Adicionar teste de regressão: user do tenant A com flag ON não acessa nada do tenant B em nenhum endpoint core/emr/billing.
- Documentar em `docs/TENANT_MIGRATIONS.md` o procedimento de go-live com rollback (flag OFF reverte comportamento sem perda de dados).

### S28-03: Staging Go-Live da Flag

- Rodar backfill + flag ON em staging; rodar a suíte E2E completa (clinical-journey, hr-onboarding, invite-flow, auth) com a flag ON.
- Corrigir qualquer endpoint que assuma acesso sem membership.
- Deixar staging com a flag ON permanentemente (atualizar `.env.staging.example`).

### S28-04: MFA Enforcement para Papéis Sensíveis

- Tornar MFA obrigatório (após grace period configurável, default 7 dias) para roles `admin` e papéis médicos.
- Middleware/permission que bloqueia ações sensíveis sem MFA enrolado após o grace, com mensagem clara e fluxo de enrolamento.
- Testes: user admin novo tem grace; após expirar, é forçado a enrolar; usuário comum não é afetado.

### S28-05: CSP Enforcement

- Migrar CSP de report-only para enforcing no nginx/headers, com allowlist correta para Next.js (scripts, styles, Sentry, fontes).
- Validar que o frontend carrega sem violações (testar todas as rotas principais).
- Manter um endpoint/log de report para detectar regressões.

### S28-06: Security Regression Suite

- Consolidar um teste de fumaça de segurança: headers presentes (HSTS, X-Frame-Options, CSP enforcing), rate limits ativos, lockout funcionando, PII não aparece em logs.

## Acceptance Criteria

- `backfill_tenant_memberships --dry-run` não escreve e reporta corretamente; run real é idempotente.
- Com flag ON, cross-tenant access retorna 403 em todos os apps; teste de regressão cobre A↔B.
- Suíte E2E passa inteira com `ENFORCE_TENANT_MEMBERSHIP=ON` em staging.
- MFA obrigatório para admin/médico após grace; testes verdes.
- CSP enforcing sem quebrar nenhuma rota do frontend.
- `docs/TENANT_MIGRATIONS.md` e `docs/SECURITY.md` atualizados.

## Verification Commands

```bash
cd backend && python manage.py backfill_tenant_memberships --dry-run
cd backend && pytest apps/core -q --reuse-db
cd frontend && npx playwright test
cd frontend && npm run build
```

## Out of Scope

- Hardware token A3 (PKCS#11) — permanece fora de escopo
- Rotação automática de secrets
