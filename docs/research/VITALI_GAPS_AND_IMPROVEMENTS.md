# Vitali — Gaps e Melhorias

**Data:** 2026-08-17 · **HEAD:** `f966d04` · **Companheiro de:** `VITALI_READINESS_REPORT.md`

Classificação de severidade:

- **BLOQUEIA-RECEITA** — impede vender, faturar ou operar com dado clínico real sem risco inaceitável.
- **ALTO** — degrada o produto de forma visível ao cliente ou cria passivo relevante.
- **MÉDIO** — dívida que cobra juros; não impede o piloto.
- **BAIXO** — acabamento, ruído, higiene.

Cada gap traz **esforço** estimado (P=baixo, M=médio, G=alto) e o **domínio** de origem.

---

## 1. BLOQUEIA-RECEITA

### Grupo A — Isolamento multi-tenant (o mais urgente)

| # | Gap | Evidência | Esforço |
|---|---|---|---|
| A1 | `ENFORCE_TENANT_MEMBERSHIP` default `False` e ausente de todo compose de produção; o system-check `core.E002` que deveria barrar é `deploy=True` e **nenhum workflow roda `manage.py check --deploy`** | `base.py:458`; verificado em `docker-compose.prod.yml`/`.staging.yml` | **P** |
| A2 | nginx não remove `X-Forwarded-Host` do cliente nas locations de API, com `USE_X_FORWARDED_HOST=True` — o header do cliente escolhe o schema | `nginx.conf` (9 de 10 locations); `base.py:104-105` | **P** (1 linha + teste) |
| A3 | `UserListCreateView.get_queryset()` lista **todos os usuários de todos os tenants** (tabela pública, sem filtro, `GET` só `IsAuthenticated`) | `core/views.py:682` | **P** |
| A4 | `Role` é tabela global sem FK para `Tenant`; namespace de RBAC compartilhado entre concorrentes | `core/models.py:592`; `core/views.py:717`; `core/serializers.py:25,46` | **M** (precisa migration) |
| A5 | Celery não propaga schema de tenant — 10 tarefas por-ID quebram em produção e passam nos testes por `ALWAYS_EAGER`. **Derruba a segurança de prescrição e a cascata de no-show**, que são os wedges de valor | `vitali/celery.py`; `emr/signals.py:73`; `emr/tasks.py:36` | **M** |
| A6 | Isolamento físico schema↔schema essencialmente não testado — só 2 arquivos criam segundo tenant; o teste que parece cobrir isso nunca troca de schema | `core/tests/test_auditlog_tenant.py:29-36` | **M** |

> **Nota de composição:** A1 e A2 juntos produzem o cenário completo de leitura de prontuário alheio. A1
> sozinho já aceita JWT de outra clínica. Tratar como um bloco só.

### Grupo B — LGPD e dado clínico

| # | Gap | Evidência | Esforço |
|---|---|---|---|
| B1 | PHI cru (áudio da consulta → OpenAI; transcrição integral → Anthropic) sem de-identificação, sem base legal do titular, e o Whisper **sem `AIUsageLog`** — chamada externa com PHI sem trilha | `emr/services/whisper.py:53-59`; `ai/services_scribe.py:84` | **M** |
| B2 | `GlosaPredictor` envia CID-10 + operadora ao Anthropic **sem checar DPA**, e é o único caminho LLM com kill-switch default `True` | `ai/services.py:452-520`; `ai/views.py:187` | **P** |
| B3 | Auditoria de **leitura** em 2 de ~40 viewsets clínicos; `list` nunca auditado → varrer a base via `?search=` não deixa rastro. CFM 1.821 exige rastreabilidade de acesso | `core/mixins.py:10-41`; usado só em `emr/views.py:318,767` | **M** |
| B4 | Não existe endpoint de consulta da trilha para o cliente — um DPO de clínica não consegue responder "quem abriu o prontuário do paciente X" sem acesso ao banco | único consumidor é `core/views_telemetry.py:176` | **M** |
| B5 | `COMPLIANCE_CHECKLIST.md` com **13 de 13 itens desmarcados** e assinatura em branco; `DPA_TEMPLATE.md` sem cláusula de cifragem, retenção, subprocessador ou notificação de incidente | — | **M** (trabalho jurídico) |
| B6 | Direitos do titular parciais: anonimização **inexistente** (`SECURITY.md:170` afirma que existe), export truncado em 100 itens e não auditado, exclusão só grava AuditLog sem fila/SLA/DPO | `patient_portal/views.py:296-372` | **M** |

### Grupo C — Segurança de acesso

| # | Gap | Evidência | Esforço |
|---|---|---|---|
| C1 | `MFARequiredMiddleware` lê `request.user` antes da autenticação lazy do DRF → no-op para todo Bearer. MFA vira UI `[H — confirmar com curl]` | `core/middleware.py:209-213` | **P** |
| C2 | `/api/auth/mfa-complete` grava `{access, refresh}` vindos do **corpo da requisição** nos cookies, sem validar assinatura nem chamar o Django | `frontend/app/api/auth/mfa-complete/route.ts:12-49` | **P** |
| C3 | `middleware.ts` protege 11 prefixos e deixa **13 grupos de rota clínica** de fora; e autentica pela mera presença de um cookie forjável | `frontend/middleware.ts:21-33,90-93` | **P** |
| C4 | Vazamento cross-tenant de imagens: `auth_request` devolve 204 para qualquer URI DICOMweb, com nginx injetando credencial admin, num Orthanc único compartilhado | `patient_portal/views_imaging.py:74-78`; `nginx.conf:140-155` | **P** (~20 linhas) |

### Grupo D — Operação e recuperação

| # | Gap | Evidência | Esforço |
|---|---|---|---|
| D1 | Restore de dado clínico **jamais validado**, e o drill que deveria validá-lo consulta `tenants_tenant`, tabela que não existe (é `core_tenant`) — falha por construção | `scripts/restore_test.sh:113`; `base.py:61` | **P** (fix) + **M** (drill real) |
| D2 | **Zero entrega de alerta**: 5 regras Prometheus sem bloco `alerting:` e sem Alertmanager em nenhum compose. Backup falhando, disco cheio, 5xx — nada chega a um humano | `docker/observability/alerts.yml`; `grep alertmanager` → vazio | **M** |
| D3 | Produção **nunca bootou**. `release-deploy.yml` com zero execuções; os "deploys" só publicam imagem; PR #173 documenta que o primeiro contato revelou bug fatal | `gh run list --workflow=release-deploy.yml` | **G** |
| D4 | Catálogos (TUSS, ANVISA, SIGTAP, CID-10) sem passo de carga em produção — nenhuma migration de dados, fixture ou step de CI. Deploy limpo sobe com tabelas vazias e **todo o trabalho B6–B9 fica inerte com saída silenciosa (log INFO)** | `scripts/catalogs/README.md`; grep em workflows/Dockerfiles | **M** |
| D5 | `vitest` fora do CI — 165 arquivos / ~700 testes de frontend podem quebrar sem bloquear merge | `.github/workflows/ci.yml` (5 jobs, nenhum roda vitest) | **P** |

### Grupo E — Receita e faturamento

| # | Gap | Evidência | Esforço |
|---|---|---|---|
| E1 | `record_inpatient_fee` (B6: taxas e gases medicinais) sem endpoint/serializer/UI — **verificado: zero callers fora de testes**. Receita pronta e trancada | `billing/services/inpatient_billing.py:178` | **P** |
| E2 | `TISSGuide` editável após submissão, sem trava de estado e **sem auditoria** — divergência guia↔remessa sem rastro | `billing/views.py:859-899` (ModelViewSet puro, sem `perform_update`) | **P** |
| E3 | XML TISS provavelmente não satisfaz o XSD: `batch_envelope.xml.j2:28` omite o wrapper `guiasTISS`, templates emitem `dadosConsulta` (0 ocorrências no XSD), validação **não-bloqueante**, e **0 testes chamam `validate_xml`** | `xml_engine.py:158`; `billing/views.py:1052` | **M** |
| E4 | Ingestão de imagem inerte: `ORTHANC_URL` ausente de todo compose e `.env*.example` → webhook responde `200 {"inert": true}` | `settings/base.py:405` | **P** |
| E5 | Nenhuma criação automática de `DicomStudy` a partir de pedido/MWL → todo estudo real vira órfão, é logado e **descartado com o cursor avançando**. Exame feito e perdido | `imaging/services/orthanc_sync.py:159,330-343` | **M** |

---

## 2. ALTO

| # | Gap | Evidência |
|---|---|---|
| 1 | IDOR cross-tenant por PK na tabela pública `User` — a **dupla checagem de transfusão** aceita como testemunha qualquer usuário da plataforma, comprometendo o valor legal do registro hemoterápico | `emr/views_transfusion_admin.py:111` |
| 2 | `MFADisableView` gated por `is_staff` inline: um `is_staff` de qualquer tenant apaga o TOTP de qualquer usuário da plataforma | `core/views_mfa.py:245` |
| 3 | Gate só de módulo em dado clínico/PII: `WhatsAppContactViewSet` e `MessageLogViewSet` expõem telefone do paciente e **conteúdo das mensagens** a qualquer usuário do tenant; 12 views de analytics expõem faturamento consolidado sem `billing.read` | `whatsapp/views.py:339,351`; `analytics/views.py:32,395,445…` |
| 4 | `verify=False` no download do truststore ICP-Brasil — MITM injeta CA forjada e passa a validar assinaturas do atacante | `signatures/management/commands/refresh_icp_truststore.py:109` |
| 5 | Assinatura ICP-Brasil é decorativa hoje: FeatureFlag OFF, truststore vazio ⇒ **fail-open**, revogação CRL/OCSP OFF por default, e `is_icp_brasil` auto-declarado no caminho do EMR | `base.py:448`; `ICP_BRASIL.md:155` |
| 6 | JWT espelhado em cookie **não-httpOnly** (`access_token_js`), lido por ~20 módulos, com CSP em report-only por default | `frontend/lib/auth.ts:58-65`; `lib/security/csp.ts:93-95` |
| 7 | `ai_prescription_safety` e `ai_cid10_suggest` **não existem** em `TenantAIConfig` → `getattr(..., False)` deixa duas features de IA clínica permanentemente mortas, e a de prescrição ainda enfileira uma task Celery por item prescrito | `prescription_safety.py:113`; `core/models.py:345-390` |
| 8 | Deploy 100% manual multi-passo, com `migrate_schemas` rodado à mão, sem janela, sem dry-run, sem backup pré-migration obrigatório; 18 migrations com `RemoveField`/`DeleteModel`/`AlterField` e nenhum padrão expand/contract | `docs/DEPLOY.md` passo 6; `TENANT_MIGRATIONS.md:128` |
| 9 | `ROLLBACK_PLAN.md` §4 e o rollback do `DEPLOY.md:218` são **inexecutáveis** (usam compose de dev / tag `:rollback` que nenhum workflow cria); o único caminho real (`IMAGE_TAG=sha-…`) está como nota de rodapé | — |
| 10 | **58% de verde em master** (35 success / 24 failure em 60 runs), com 9 falhas consecutivas em 30/07–01/08; CI de 41 min; `frontend-e2e` some silenciosamente quando `backend-test` falha | `gh run list --workflow=ci.yml` |
| 11 | Sem imagem semver identificável em produção: `release-deploy.yml` com 0 execuções, única tag `v1.2.0` de abril, `IMAGE_TAG` default `latest` (mutável) | — |
| 12 | 12 botões renderizam **sem estilo** por `neu-button-*` inexistente (as classes reais são `neu-btn-*`) — verificado. Atinge conciliação financeira, DRE, entradas NF-e, tesouraria e contas a pagar/receber | `globals.css:64,68` vs 12 usos em `administracao/` e `billing/` |
| 13 | `/imagens` não persiste nada: só `GET`, zero mutação, com 3 endpoints de imaging no backend sem consumidor | `components/imaging/ImagingPanel.tsx:58` |
| 14 | Laudo de imagem só vinculável na criação (sem PATCH), sem estrutura, e `apps/signatures` não conhece laudos — não fecha requisito CFM | `imaging/urls.py:26-45`; `signatures/models.py:32-41` |
| 15 | Sem retenção ou quota de storage PACS: `orthanc_data` cresce sem limite até encher o disco | — |
| 16 | Guia de honorários é fachada: choice sem gerador nem template; consulta ambulatorial não vira guia automaticamente; envio/retorno TISS é manual (o `submit` é flip de status) | `billing/views.py:1068`; `xml_engine.py:96-100` |
| 17 | WhatsApp sem verificação de posse do número (sem OTP; confia no `remoteJid`) e `MessageLog.content_preview` em texto plano | `whatsapp/views.py:259`; `models.py:151` |
| 18 | Drift de contrato de API: `API_SPEC.md` documenta `/api/v1/tiss/*` e rotas de `timeline`/`notes` que **não existem**; `openapi.yaml` (468 paths) está 3 semanas atrás do código | `billing/urls.py:42-43` |
| 19 | Sem camada de cache de servidor no frontend (sem react-query): refetch total a cada ação em telas de 1.164 e 1.487 linhas | `lib/api.ts` |
| 20 | Volume do host a **82%** com 2,5 GB de worktrees mortos (82 worktrees, 103 branches) | `du -sh`; `git worktree list` |

---

## 3. MÉDIO

- Management commands de apps tenant sem `--schema`/`schema_context` rodam no schema público, onde as
  tabelas não existem (`ai/…/seed_prompt_templates.py`, `import_cid10.py`, `pharmacy/…/ingest_nfe_email.py`).
- `XForwardedHostValidationMiddleware` só é inserido em `production.py:127` — staging/dev ficam sem o guarda.
- `AUTH_PASSWORD_VALIDATORS` definido e **nunca executado**; `SetPasswordView` aceita 8 caracteres enquanto o
  serializer exige 12, e `password123456` passa nos dois.
- Busca de paciente **decripta a base inteira** a cada `?search=` (`emr/filters.py:18-59`) — DoS autenticado.
- Todos os guardrails de IA são fail-open no Redis: Redis fora ⇒ rate limit, circuit breaker e teto de custo
  desativados **simultaneamente**.
- `GlosaPredictor` retorna `risk_level="low"` quando o provider cai — o fail-open **errado** para um preditor
  de risco financeiro.
- Busca FHIR de `Patient` faz scan full-table em Python porque `full_name`/`cpf` são criptografados.
- `apps/billing/migrations/` é código morto (`MIGRATION_MODULES` redireciona para `billing_migrations/`) —
  armadilha para quem rodar `makemigrations billing`.
- Sem versionamento DRF real: `/api/v1/` é prefixo hardcoded, sem caminho para v2.
- `seed_demo_data` planta CNES/UCUM fictícios com **códigos reais**, replantando duplicata se o catálogo real
  for importado depois.
- PITR opt-in e nunca ativado → RPO real de 24h, não de minutos; `BACKUP_ENCRYPTION_KEY` é **opcional** (sem
  ela o dump vai em claro).
- Guardas `:?` inconsistentes no `docker-compose.prod.yml`: `ORTHANC_*` protegido, `POSTGRES_PASSWORD`/
  `REDIS_PASSWORD`/`CELERY_DATABASE_URL` falham em silêncio.
- Reskin neumórfico não aplicado justo nas telas clínicas de maior tráfego (167/92/91 linhas de cor crua em
  `patients/[id]`, `encounters/[id]`, `appointments`; `PrescriptionBuilder` com 0 tokens).
- `docs/I18N.md` afirma que o frontend não tem biblioteca de i18n — falso desde o PR #137.
- E2E não cobre billing/SUS, farmácia, imaging, hemoterapia nem segurança de dose.
- `.coverage` da raiz inutilizável como evidência (7% global, `views.py` em 0% em todo app).
- PR #173 aberto há 27 dias sinalizando falsamente bug de produção não corrigido; PR #210 `CLEAN` e ignorado.
- Sem auto-delete de branch no merge — 100 branches mortas acumuladas em ~5 meses.
- ~60 call sites com `fetch` cru fora do `apiFetch` → sem refresh, 401 silencioso após 15 min.
- Upload sem validação de magic bytes e sem antivírus (prometido em `SECURITY.md:45`).
- Zero cache em analytics; `_fill_rate` faz query por `ScheduleConfig`.
- `apps/triage` tem API e backend em master (**confirmado**), mas **nenhuma UI** — nenhum arquivo de frontend
  chama `/triage/sessions/`.

---

## 4. BAIXO

Sem `freeze_time` em nenhum teste de data (87 arquivos usam `timezone.now()` cru) · `offline_access` SMART
anunciado sem `refresh_token` · sem `_include`/ETag/`_history` no FHIR · `evolution-api` com
`AUTHENTICATION_API_KEY` default `change-me` · cache de `TenantAIConfig` com lag de 5 min (desligar IA pelo
painel demora até 5 min) · logout não limpa `sessionStorage`/`localStorage` · `dark:` em 0 arquivos apesar de
`darkMode: ["class"]` · 4 páginas monolíticas acima de 700 linhas · páginas de `administracao/` escritas em
linha única de 400+ colunas (ilegíveis em review) · `ViewerAuthorizationView` órfão · `test.sh` commitado com
path pessoal hardcoded · `PERFORMANCE.md` referencia serviço `db` (é `postgres`) · `ci.yml:5,7` dispara em
`main`/`develop`, que não existem · ~30 `PLAN_SPRINT*.md` misturados com docs operacionais · dois `TODOS.md`
· `DESIGN.md` superseded ainda na raiz · `SECURITY.md` com 8 contradições internas · `WEDGE_ACTIVATION.md` e
`AI-NATIVE-WEDGES.md` usando "wedge" com significados incompatíveis.

---

## 5. Melhorias de maior alavancagem

Ordenadas por **retorno ÷ esforço**. As cinco primeiras são o núcleo da Onda 0.

### 5.1 — Fechar o perímetro multi-tenant `[retorno máximo, esforço P]`

Quatro mudanças pequenas que juntas eliminam a classe inteira de vazamento entre clínicas:

1. `proxy_set_header X-Forwarded-Host $host;` nas locations de API do nginx.
2. `ENFORCE_TENANT_MEMBERSHIP=True` nos composes, após `backfill_tenant_memberships`.
3. `manage.py check --deploy` como step **bloqueante** do CI — sem isso, o item 2 regride em silêncio e o
   `core.E002` continua decorativo.
4. `UserListCreateView.get_queryset()` filtrando por `memberships__tenant=connection.tenant`.

Cada uma acompanhada de um teste de integração que **tenta o ataque** e espera 400/401/lista vazia. Adotar o
padrão que `AuditLog.for_current_tenant()` já estabeleceu no repositório.

### 5.2 — Propagar schema de tenant no Celery `[retorno máximo, esforço M]`

Um único ponto — `tenant-schemas-celery` ou uma base `Task` que carimba `connection.schema_name` no header em
`apply_async` e reentra via `schema_context` no `task_prerun` — conserta **dez tarefas quebradas**, incluindo
a segurança de prescrição, que é o wedge de valor nº 1 do produto. Teste de regressão obrigatório: uma tarefa
por-ID executada com `ALWAYS_EAGER=False` a partir do schema público.

### 5.3 — Provar recuperação de dado clínico `[retorno máximo, esforço P+M]`

Corrigir `tenants_tenant` → `core_tenant` (uma linha), rodar o drill **de verdade** contra um dump real hoje,
publicar o resultado, e agendá-lo semanalmente. Em paralelo, subir Alertmanager com uma rota real e o alerta
`VitaliBackupStale` (idade do último dump > 26h). Sem isto, "temos backup" é uma afirmação sem evidência — e
para EMR essa é a afirmação que não se pode errar.

### 5.4 — De-identificar PHI antes de sair `[retorno alto, esforço M]`

Um `phi_scrubber` entre o EMR e qualquer gateway externo (nome, CPF, RG, CNS, telefone, datas → tokens),
aplicado a Whisper, Scribe e Glosa; `AIUsageLog` obrigatório em **toda** chamada externa, com `input_text`
criptografado; e um decorator único `@requires_ai_consent(feature)` que verifique flag global, flag por
tenant, DPA assinado e teto de custo — hoje cada caminho verifica um subconjunto diferente, e a glosa não
verifica nada. Mudar `FEATURE_AI_GLOSA` para default `False`.

### 5.5 — Alinhar o que o repositório diz ao que ele é `[retorno alto, esforço P]`

Um dia de trabalho de documentação recupera a maior discrepância do projeto entre valor construído e valor
demonstrável: reescrever o README e cobrir os ~250 commits ausentes do CHANGELOG; escolher **um** roadmap e
arquivar os outros (hoje há `PLAN_GA_ROADMAP` + `PLAN_PLATFORM_ROADMAP` + 3 `ENRICHMENT` + 6 `DEEPENING`
simultâneos e divergentes); registrar por escrito a virada estratégica de jul/ago (profundidade enterprise
sobre GA de piloto), que aconteceu de fato e nunca foi documentada — e portanto nunca pôde ser contestada.

### Alavancagens seguintes

6. **Ligar `record_inpatient_fee` a um endpoint e tela** — a maior receita pronta e trancada do repositório.
7. **Inverter `middleware.ts` para deny-by-default** com allowlist: elimina os 13 buracos e o modo de falha
   "esqueci de adicionar a rota nova". ~15 linhas.
8. **Adicionar job `frontend-unit` ao CI** rodando `vitest`, e garantir que falha de worker saia com código
   ≠ 0. Destranca 165 arquivos de teste que hoje não protegem nada.
9. **Fechar o DICOMweb por estudo também para staff**, reaproveitando a resolução por UID que o ramo do
   paciente já implementa corretamente. ~20 linhas eliminam o vazamento de imagens.
10. **Um teste que asserta `validate_xml(...).valid is True`** para TISS e o equivalente para a remessa SUS.
    É a diferença literal entre "gera guia" e "recebe dinheiro".
11. **Estender `AuditReadMixin` a todo viewset que serve PHI**, com um teste de contrato que falhe se um
    viewset de app clínico não declarar `audit_resource_type` — converte a trilha de parcialmente conforme
    em conforme, com esforço linear.
12. **Passo de carga de catálogos no deploy** (o command já é idempotente/upsert) + health-check que
    **acuse** catálogo vazio em vez de falhar em silêncio.
13. **Guard de imutabilidade + `_write_audit` em `TISSGuideViewSet.perform_update`**, no mesmo padrão já
    usado e testado em `CashFlowEntry`.
14. **Consertar ou apagar os dois campos fantasma de `TenantAIConfig`**, trocando `getattr(config, …)` por
    acesso direto ao atributo para que a próxima ausência **quebre** em vez de silenciar.
15. **Corrigir as 14 classes CSS inexistentes** e adicionar lint que falhe em classe `neu-*` não declarada —
    o `tsc` nunca vai pegar isso, foi exatamente por isso que passou.
16. **Adotar react-query** envolvendo `apiFetch`: resolve cache, dedupe, invalidação pós-mutação e
    loading/error de uma vez, e apaga a maior parte do `useState/useEffect` manual das 91 páginas.
17. **Higiene de git**: arquivar as 103 branches como tags, remover os 82 worktrees, ligar
    `--delete-branch-on-merge`, fechar o PR #173. Recupera 2,5 GB e ~12% do volume.

---

## 6. Decisões que precisam de humano

Não são gaps técnicos; são escolhas de produto que travam sequências inteiras.

| # | Decisão | Por que trava |
|---|---|---|
| 1 | **Qual versão TISS a ANS exige em 2026?** | O repo tem XSD 4.01.00 e o próprio `TODOS.md` menciona 4.02.00+. Se o mandato for 4.02+, o módulo de faturamento é infaturável e todo o trabalho de conformidade muda de escopo. É a maior incerteza comercial da auditoria e não é resolvível a partir do código. |
| 2 | **Telemedicina: matar ou construir?** | Hoje é dívida de credibilidade — está no `CANONICAL_FEATURE_MAP` como "tem" e é uma casca sem vídeo, sem prontuário e sem assinatura. |
| 3 | **O flywheel entra no pitch ou sai?** | É a claim que o `VISION-AI-NATIVE.md` chama de "o fosso que compõe juros" e é estruturalmente impossível de defender hoje. Ou constrói a versão mínima (recalibrar um threshold a partir de `outcome` já rotulado em stockout/no-show) ou tira do material comercial. |
| 4 | **Formulário de dose: quem valida?** | A decisão D-T1 (`docs/formulary-package/`) exige um farmacêutico assinar as regras. Sem isso, o wedge de dose — a cunha de entrada declarada — permanece inerte por decisão, não por falta de código. |
| 5 | **Catálogos licenciados** (NANDA/NIC/NOC, Simpro, Brasíndice, CBHPM) e **LOINC** | Bloqueio comercial/contratual, não técnico. LOINC precisa apenas de uma conta gratuita. |
| 6 | **Acesso ao Docker nesta máquina** | `rcosta00` fora do grupo `docker`; a suíte de backend não pôde ser executada. Toda validação de onda vai precisar disso. |
