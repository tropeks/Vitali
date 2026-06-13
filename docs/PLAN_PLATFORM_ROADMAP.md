# Vitali — Roadmap da Plataforma (sprints + tasks)

> Quebra executável da visão `ARCH_TARGET_VISION.md` em fases → sprints → tasks.
> Fonte para semear o Shrimp Task Manager. Cada task marcada:
> **[EXISTE]** já feito (reusar) · **[ADAPTAR]** existe mas muda · **[MUDAR]** troca de
> abordagem · **[NOVO]** do zero.
> Doutrina: superpowers/TDD por task; cada sprint fecha com `/cso` (auditoria de
> segurança) + correção do que achar. Sequência por **fundação**, não por calendário.

## Estado atual (baseline real, verificado 2026-06-13 no LXC Docker)

- v1.0.0, core monólito Django (17 apps) + Next.js. Multi-tenant schema-per-tenant.
- Suíte core+pharmacy **463 verde** no Docker.
- Sprints 27 (Ops) e 28 (Tenant Enforcement + MFA) **mergeados**; fixes de robustez A1 +
  consolidação MFA **mergeados e testados**.
- Já existe: `apps/patient_portal`, `apps/whatsapp`, `apps/signatures` (ICP), `apps/imaging`
  (Orthanc), `apps/ai`, `docker-compose.prod.yml`, settings em camadas, Sentry.

---

## FASE 0 — Fechar GA do core (já planejado em PLAN_SPRINT27–33)

Pré-requisito de tudo: o produto precisa estar sólido antes de virar plataforma.

- **S27 Ops Foundation** — ✅ mergeado. Pendente: verificação prod no Docker (compose
  config, smoke, restore drill, boot-checks). [ADAPTAR: fechar dívida de verificação]
- **S28 Tenant Enforcement + MFA** — ✅ mergeado e verificado (463 verde).
- **S29 Data Curation Tooling** — [ADAPTAR] `import_tuss` já existe; núcleo = gating
  `validated=True` no DoseChecker (repercute na suíte de dose) + importers de formulário/
  alergia + UI de validação. Agora fazível com pytest no Docker.
- **S30 Wedges Wave 1** (no-show, stockout, NEWS2) — [EXISTE engines] ligar flags + soak.
- **S31 Wedges Wave 2** (dose, glosa, alergia, controlled) — depende de dados curados.
- **S32 Compliance Pack GA** (assinatura ICP no fluxo, LGPD frontend, DPA/DPO).
- **S33 Pilot Onboarding & GTM** → GA.

## FASE 1 — Fundações da plataforma (P1–P6, baratas, destravam o resto)

Podem correr em paralelo à Fase 0; tornam a decomposição futura barata.

### SPRINT P1 — Costuras & guardas
- P1-01 [NOVO] **import-linter no CI**: proíbe import cruzado entre apps de domínio
  (emr↛billing etc.). Mapear fronteiras atuais, marcar violações existentes como baseline,
  travar novas. (P4)
- P1-02 [NOVO] **System-check de produção**: boot falha se `ENFORCE_TENANT_MEMBERSHIP=False`
  em `ENVIRONMENT=production`. (P6) — segue padrão de `apps/core/checks.py`.
- P1-03 [ADAPTAR] **Auditoria inviolável**: migration que faz `REVOKE UPDATE, DELETE` na(s)
  tabela(s) de AuditLog para o role da app (só INSERT/SELECT). Teste prova imutabilidade. (P2)
- P1-04 [NOVO] **Camada de serviço como única porta** de cada app de domínio (formalizar o
  que já existe em `services/`); documentar o contrato.
- **/cso** no fim.

### SPRINT P2 — Observabilidade (OTLP)
- P2-01 [ADAPTAR] **OpenTelemetry** no backend (Django + Celery + psycopg) exportando OTLP;
  Sentry permanece como um dos backends. (P5)
- P2-02 [NOVO] Trace-id correlacionado nos logs JSON estruturados (já há request_id).
- P2-03 [NOVO] Backend de tracing plugável (dev: console/Jaeger; prod: gerenciado), desligável.
- **/cso** no fim.

### SPRINT P3 — Perfil de implantação & cripto ✅ (branch feat/sprint-p3-profile-crypto, testado; aguardando merge)
- P3-01 [NOVO] ✅ `DEPLOYMENT_PROFILE` (`pool`|`dedicated`) + `IS_DEDICATED_INSTANCE`;
  validado no boot (`assert_deployment_profile`) + system-check prod `core.E003`. Air-gap fora.
- P3-02 [ADAPTAR] ✅ **Blast-radius da cripto**: `_secrets.py` `resolve_field_encryption_key`
  com precedência `FIELD_ENCRYPTION_KEY_FILE` (secret de runtime) > env > placeholder; falha
  loud se file ausente/vazio; é o seam único de KMS/envelope. Call sites intactos.
- P3-03 [ADAPTAR] ✅ Workers Celery least-privilege: `VITALI_ROLE` + `CELERY_DATABASE_URL`
  (DSN Postgres separado, preserva ENGINE django-tenants) + system-check prod `core.E004`.
  Workers ainda precisam de `FIELD_ENCRYPTION_KEY` (fronteira = credencial do banco).
- **/cso** ✅ (daily, diff): 0 findings ≥8/10. Auditoria Opus pegou e corrigiu bug crítico
  de clobber do ENGINE django-tenants no override de DSN do worker. Regressão 529 verde.

## FASE 2 — BFP (Backend-For-Patient): 1ª extração

A borda do paciente sai de cima do PHI. Em todos os tiers. Consome o core por API.

### SPRINT B1 — Contrato de API paciente-facing do core
- B1-01 [NOVO] Definir e versionar a **API que o core expõe ao paciente**: marcar consulta/
  exame (core valida), minhas consultas, meus resultados (lab + link PACS), minhas receitas,
  meu perfil. OpenAPI + testes de contrato.
- B1-02 [ADAPTAR] Tokens **escopados** para o BFP (não acesso total); o BFP nunca toca o DB
  clínico direto.
- B1-03 [NOVO] Auditar toda leitura paciente-facing (CFM).
- **/cso** no fim.

### SPRINT B2 — Carve do BFP (módulo com fronteira própria)
- B2-01 [ADAPTAR] Consolidar `apps/patient_portal` + `apps/whatsapp` num **módulo BFP** com
  datastore próprio (identidade do paciente, consentimento LGPD, conversas, lembretes,
  rascunhos de agendamento). Ainda no mesmo repo, mas falando com o core **só por API**.
- B2-02 [ADAPTAR] Identidade do **paciente** separada da do staff (já há auth isolada no
  portal) — endurecer a fronteira.
- B2-03 [NOVO] Deploy do BFP como serviço próprio (compose agora; manifesto k8s na Fase 3).
- **/cso** no fim.

### SPRINT B3 — Motor de conversa 2 modos (padrão do AgendaSmart, sem acoplar)
- B3-01 [NOVO] **Modo scriptado** (fluxos determinísticos permanentes) — reimplementa o
  padrão provado do Agenda_Studio (`*_by_client`), NÃO importa o código. Marcar consulta,
  confirmar, ver resultado.
- B3-02 [NOVO] **Modo IA** atrás de flag/plano (premium, fast-follow) — trilhos + rate-limit.
- B3-03 [NOVO] Feature-gating: scriptado incluído, IA premium.
- B3-04 [ADAPTAR] Comportamento por tier (pool: BFP multi-tenant isolado; dedicado: por
  instância).
- **/cso** no fim.

## FASE 3 — Substrato declarativo (k8s + GitOps + Tenant operator)

Só vale quando houver frota a justificar (>~5 clientes). Antes: provisão scriptada (v0).

### SPRINT K1 — Empacotar a instância
- K1-01 [MUDAR] **Helm chart da instância** (app core + BFP + DB + redis) — migra do
  docker-compose para artefato k8s reproduzível.
- K1-02 [NOVO] Imagens versionadas no GHCR (CI já publica; alinhar).
- **/cso** no fim.

### SPRINT K2 — Tenant CRD + Operator (coração do control plane)
- K2-01 [NOVO] CRD `Tenant{cliente, tier, módulos, plano}`.
- K2-02 [NOVO] **Operator** que reconcilia a instância (namespace, DB, secrets, DNS, certs,
  módulos) — **idempotente/reentrante** (anti-A1). Provisão e atualização declarativas.
- K2-03 [NOVO] `cert-manager` (uma âncora, rotação automática — anti-A4).
- **/cso** no fim.

### SPRINT K3 — Dados, HA e GitOps
- K3-01 [NOVO] **CloudNativePG** (Postgres operator): HA, backup, failover declarativos.
- K3-02 [NOVO] HA do dedicado: active-passive multi-AZ + LB com health check.
- K3-03 [NOVO] **GitOps** (Argo CD/Flux): cluster = espelho do Git; IA propõe PR, humano
  mergeia.
- K3-04 [NOVO] IaC (Terraform/OpenTofu) dos recursos de cloud.
- **/cso** no fim.

### SPRINT K4 — Control plane v1
- K4-01 [NOVO] Registry de instâncias (estado da frota).
- K4-02 [NOVO] Billing/feature-gating por cliente (espelha `ra-licensing` do LabX).
- K4-03 [NOVO] Health agregada da frota + alertas.
- K4-04 [NOVO] Rollout de frota com migration + canary (staged, reversível).
- **/cso** no fim.

## FASE 4 — Decomposição seletiva (por gatilho)

Cada um é módulo opcional composto pelo control plane por plano.

- **PACS/Orthanc** [ADAPTAR] (`apps/imaging` já fala com Orthanc) — extrair quando cliente
  com volume de imagem.
- **IA-worker** [ADAPTAR] (`apps/ai`) — extrair quando escala/latência justificar.
- **Reporting/BI** [NOVO] — read-replica + serviço próprio quando queries pesadas ameaçarem o OLTP.
- **Gateway de canais** [ADAPTAR] — isolar superfície externa quando volume justificar.

## Pós-produto (projetos à parte)
- Monitoramento de equipamentos de suporte à vida (dispositivo regulado ANVISA, edge agent,
  BFI gRPC). Edge/CDN para grandes nomes.

---

## Ordem de execução recomendada (loops Shrimp)
1. Fechar Fase 0 (S29 → S33) — produto a GA.
2. Fase 1 em paralelo (P1→P3) — fundações baratas.
3. Fase 2 (BFP) — 1ª extração, prova do padrão.
4. Fase 3 (substrato) quando a frota justificar.
5. Fase 4 por gatilho.

> Cada sprint: superpowers/TDD nas tasks → suíte verde no Docker → `/cso` → corrigir →
> commit → atualizar Shrimp + memória.
