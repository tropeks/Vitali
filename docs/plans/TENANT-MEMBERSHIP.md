# Tenant Membership & Enforcement — Plano (Modelo B)

> **Problema (revisão 2026-06-05):** `apps.core` é SHARED_APPS-only → `User`/`Role`
> vivem 1× no schema **public** (tabela global), `email unique` global, e **não há
> vínculo user↔tenant** nem checagem de membership. `TenantJWTAuthentication` só
> valida `is_active`. Roteamento de tenant é por Host; `auth/login` está no urlconf
> do tenant e faz `User.objects.get(email=…)` global. **Consequência:** um usuário de
> qualquer clínica pode logar/replayar JWT no domínio de outra e operar no schema dela
> → leitura cross-tenant de PII/prontuário (LGPD). HIGH (latente se single-tenant) →
> CRITICAL (se multi-tenant em prod).

## Decisão do dono: **Modelo B** — usuários globais + membership explícito + enforce
Mantém `User` global (suporta staff multi-clínica por design), adiciona um modelo de
membership e **rejeita 401** quando o usuário não é membro do tenant da request.

## Princípio
Fail-closed: sem membership ativa no `connection.tenant` → 401. Superuser/platform-admin
cruzam tenants (ops legítima). Public schema (urlconf público) não exige membership
(endpoints lá já exigem superuser). A mudança fecha o furo SEM reescrever toda a camada
de authz de uma vez (role-por-membership fica para a Fase 2).

## Modelo de dados — SHARED (apps.core, schema public, igual FeatureFlag)
`UserTenantMembership`:
- `user` FK → core.User (CASCADE)
- `tenant` FK → core.Tenant (CASCADE)
- `role` FK → core.Role (SET_NULL, null=True) — gravado para a Fase 2; **na Fase 1 a
  resolução de permissão continua via `user.role`** (blast radius mínimo)
- `is_active` bool (default True)
- `created_at`
- **unique_together (user, tenant)**

Vive em public porque liga dois modelos public (User+Tenant); pode ter FK tenant
exatamente como FeatureFlag (que é o padrão correto que falta no AuditLog).

## Enforcement (fail-closed, superuser bypass, public-schema skip)
1. **`TenantJWTAuthentication.get_user`** — depois de carregar o user (global) e checar
   `is_active`: se `connection.schema_name == public` → passa (sem tenant a checar);
   se `user.is_superuser` → passa; senão exige
   `UserTenantMembership.objects.filter(user=user, tenant=connection.tenant, is_active=True).exists()`
   → 401 `NO_TENANT_MEMBERSHIP` se ausente. `connection.tenant` está disponível pois
   `TenantMainMiddleware` é o 1º middleware (roda antes do dispatch/auth do DRF).
2. **`LoginView.post`** — após autenticar o user global, antes de emitir tokens, aplica
   a mesma checagem de membership no tenant da request (bypass superuser). Assim o login
   da clínica A no domínio da clínica B falha imediatamente (não só nas requests seguintes).
3. **Gate de rollout seguro:** setting `ENFORCE_TENANT_MEMBERSHIP` (default **True**).
   A MESMA release roda o backfill (migração + comando), então enforce e dados ficam
   consistentes. Permite desligar em emergência sem redeploy de código.

## Backfill — inferir membership dos usuários existentes (sem vínculo gravado hoje)
Não há binding gravado, mas os schemas de tenant **referenciam** usuários. Inferência
determinística por schema:
- **`emr.Professional`** (OneToOne→User) — sinal mais forte: profissional clínico do tenant.
- `created_by`/`signed_by`/`confirmed_by` (emr), `dispensed_by`/`performed_by` (pharmacy),
  e demais FKs→core.User em apps TENANT.
Para cada tenant, coletar `user_id` distintos referenciados → cria
`UserTenantMembership(user, tenant, role=user.role, is_active=True)`.
- **Comando `backfill_tenant_memberships`** (idempotente, `--dry-run`, relatório por tenant):
  itera `Tenant.objects.exclude(schema_name=public)` com `tenant_context`, faz UNION dos
  user_ids referenciados, cria memberships que faltam.
- **Usuários sem referência em nenhum schema** (ex.: admin recém-criado que nunca tocou
  dado): relatados explicitamente; **NÃO** recebem membership automática (não re-abrir o
  furo). Single-tenant: todos caem no único tenant trivialmente. O admin de cada tenant é
  criado no provisioning (`HealthOSTokenObtainPairView`/TenantRegistration) — ver Fase 1.5.
- A migração de schema só **cria a tabela**; o backfill é o comando (rodado no deploy,
  antes/junto de ligar o enforce). Migração de dados NÃO concede "todos→todos".

## Provisioning de tenant novo (fechar o caminho para frente)
Onde um tenant é criado e seu admin user nasce (`apps/core/views.py:452-546`,
`with schema_context(...)`): criar a `UserTenantMembership(admin_user, tenant, admin_role)`
explicitamente. Idem qualquer fluxo de convite (`Invitation`) que materializa user num tenant.

## Sequência de PRs
- **M1 — modelo + enforce + login-check + provisioning + comando backfill + testes.**
  Migração cria `UserTenantMembership`. Enforce gated por `ENFORCE_TENANT_MEMBERSHIP`.
  Testes: cross-tenant replay → 401; membro → 200; superuser cruza; public schema isento;
  login em tenant sem membership → 401; backfill idempotente infere de Professional+FKs.
- **M2 (follow-up) — role por membership.** Migrar resolução de permissão de `user.role`
  para `membership.role` no tenant corrente (`has_role_permission`, `HasPermission`),
  blast radius da camada de authz. Depreca `User.role` (mantém coluna até migração completa).

## ✅ LOCKED (eng-review adversarial — 3 BLOCKERs vinculantes incorporados)
- **B1 — refresh + token claim (CRÍTICO):** `TokenRefreshView` (views.py:356) é o SimpleJWT
  cru: **não carrega user, não checa membership**, e o `token_blacklist` é per-schema
  (rotação não vale cross-tenant). Sozinho, `get_user`+`LoginView` NÃO cobrem refresh →
  replay de refresh-token da clínica A no domínio B cunha access token válido.
  **Fix:** (1) **carimbar `token["schema"] = connection.schema_name`** nos 3 mint sites —
  `LoginView` (views.py:298), `MFALoginView` (views_mfa.py:43), `SetPasswordView`
  (views.py:207) — via helper `issue_tokens_for(user)`; (2) subclassar
  `TokenRefreshView`/serializer p/ **rejeitar 401 se `token["schema"] != connection.schema_name`**
  e re-checar membership; (3) `TenantJWTAuthentication.get_user` também valida o claim
  `schema` contra `connection.schema_name` (defense-in-depth — fecha mesmo se algum path
  futuro esquecer a query de membership).
- **B2 — public-schema skip restrito:** NÃO liberar todo autenticado no schema public
  (`tuss-sync-status` está montado no public urlconf, `vitali/urls_public.py:23`). Regra:
  no schema public, **exigir `is_superuser`** exceto allowlist anônima explícita (health,
  registro de tenant `AllowAny`). Se `connection.schema_name` vazio/None → **fail-closed**
  (não tratar "não-public" como "tem tenant").
- **B3 — rollout sem lockout:** `ENFORCE_TENANT_MEMBERSHIP` default **False**. Release em
  2 passos: **R1** = model+migração+comando backfill+código de enforce (OFF) → migrate →
  rodar backfill → **verificar relatório por tenant**; **R2** = ligar `ENFORCE_TENANT_MEMBERSHIP=True`
  via env (sem deploy de código). Default True na release da migração trancaria todos os
  não-superuser na janela migrate→backfill.
- **SHOULD-FIX dobrados:** (a) **login sem oráculo de enumeração** — no-membership retorna
  `INVALID_CREDENTIALS` genérico (mesmo shape/timing), não revela "senha certa, clínica
  errada"; (b) **mfa-login** (`views_mfa.py:43`) re-checa membership (é mint site);
  (c) **backfill antes do enforce** + comando `grant_tenant_membership --user --tenant`
  p/ os usuários sem footprint de dados (relatados, não auto-concedidos) + runbook ops;
  (d) **precedência is_active** (invariante testado): `User.is_active=False` → 401 em todo
  lugar; `membership.is_active=False` → 401 só naquele tenant (desativar numa clínica NÃO
  exige flipar o flag global); (e) **índice composto** `(user, tenant, is_active)` (lookup
  em toda request autenticada); (f) deploy-check (`apps/core/checks.py`) que nenhum
  `is_superuser=True` tenha role/Professional de tenant (detecta violação da política
  is_platform_admin==is_superuser que habilita o bypass).
- **Limitação conhecida (M1, documentar no release):** Fase 1 resolve permissão via
  `user.role` global → staff multi-clínica carrega o MESMO role nas duas (M2 = role por
  membership). M1 fecha ISOLAMENTO (não entra no tenant errado); não diferencia role por
  tenant ainda. Aceitável dado o gate de membership.
- **Sem novos entry points:** sem Channels/websocket auth; `SessionAuthentication` NÃO está
  em `DEFAULT_AUTHENTICATION_CLASSES` (só `TenantJWTAuthentication`); admin Django roda só
  no schema public, superuser-gated.

## Fora de escopo (v1/M1)
Reescrita de authz para role-por-membership (M2); UI de gestão de membership; convite
multi-clínica. M1 fecha o furo de isolamento; M2 refina o modelo de permissão.

## ✅ SHIPPED (M1 — branch feat/tenant-membership-m1, flag ENFORCE_TENANT_MEMBERSHIP OFF)
- `core.UserTenantMembership` model (public schema, FK user+tenant+role, unique(user,tenant),
  index (user,tenant,is_active)) + migração `core/0016_usertenantmembership`.
- `apps/core/tenant_auth.py`: `tokens_for_user` (carimba claim `schema`), `login_allowed`,
  `enforce_request_membership` (get_user), `enforce_refresh_membership` (refresh). Gated por
  `ENFORCE_TENANT_MEMBERSHIP` (default False).
- Enforcement wired: `TenantJWTAuthentication.get_user`, `LoginView` (401 genérico, sem
  oráculo), `TokenRefreshView` (schema-claim + membership), mint sites (login/mfa-login/
  invitation set-password) carimbam o schema. Provisioning de tenant cria a membership do admin.
- Comandos `backfill_tenant_memberships` (infere de FKs→User por schema, idempotente, --dry-run,
  reporta órfãos) e `grant_tenant_membership --user --tenant [--role]`.
- Docstrings corrigidos (models header + User + Role): apps.core é público/global.
- 17 testes novos (get_user/login/refresh/superuser/public/is_active precedence/schema-claim/
  backfill). Suite apps/core: 201 passed. ruff + mypy limpos.
- **Rollout:** R1 deploy (flag OFF) → migrate → `backfill_tenant_memberships` → revisar órfãos +
  `grant_tenant_membership` p/ quem falta → R2 `ENFORCE_TENANT_MEMBERSHIP=true` via env.
- **M2 (follow-up):** resolução de permissão por `membership.role` (hoje via `user.role` global).
