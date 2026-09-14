# Vitali — Relatório de Readiness Real

**Data:** 2026-08-17 · **HEAD auditado:** `f966d04` (master) · **Método:** swarm de 10 agentes read-only + verificação direta do team manager

> **Como ler este documento.** Cada afirmação é marcada como **[E]** evidência (arquivo:linha lido),
> **[H]** hipótese (dedução plausível, não confirmada empiricamente) ou **[B]** bloqueio (não pôde ser
> verificado nesta sessão). Nenhuma promessa de documentação foi aceita sem conferência no código.
> Segredos não são transcritos; onde apareceriam, consta `[REDACTED]`.

---

## 1. Resumo executivo

O Vitali **não é uma fachada**. É um HIS/EMR multi-tenant genuinamente denso: 21 apps Django, 249 models,
~145k LOC de backend, 342 rotas de API, 99 páginas Next.js ligadas a 435 endpoints reais, 3.250 funções de
teste no backend, 219 migrations consistentes, e uma disciplina arquitetural rara — camada de serviço
*enforced* por `import-linter`, trilha de auditoria imutável por triggers Postgres, criptografia de PII em
repouso que passa em teste honesto de ciphertext. Sete dos oito fluxos clínicos ponta-a-ponta (PS/Manchester,
internação/ADT, prescrição→farmácia→BCMA, laboratório, centro cirúrgico, enfermagem/SAE, hemoterapia) são
navegáveis e persistem dados de verdade.

O problema do Vitali não é falta de construção. São **três descolamentos**:

1. **Descolamento produto↔documento.** O README e o CHANGELOG congelaram em junho/2026 e omitem ~250 commits
   e 6 épicos inteiros. O repositório *parece* um EMR ambulatorial v1.0.0 e *é* um HIS hospitalar. Ao mesmo
   tempo, os documentos de visão vendem um *data flywheel* que aprende toda semana — e **nada no código
   aprende**. O projeto se subestima no que entregou e se superestima no que promete.

2. **Descolamento código↔operação.** Quase toda a infraestrutura foi *escrita* e quase nada foi *executado*.
   `release-deploy.yml` nunca rodou uma única vez; os workflows chamados de "deploy" apenas publicam imagem;
   `settings.production` nunca bootou em host nenhum; o drill de restore consulta uma tabela que não existe,
   provando que backup de dado clínico jamais foi restaurado; 5 regras de alerta Prometheus existem sem
   Alertmanager para entregá-las.

3. **Descolamento controle↔ativação.** Os controles que separam "multi-tenant de saúde" de "vazamento de
   prontuário" existem, estão corretos, e estão **desligados**. `ENFORCE_TENANT_MEMBERSHIP` é `False` por
   padrão e não é setado em produção. O middleware de MFA é provavelmente inoperante por bug de camada. Os 7
   wedges de IA — a tese de valor do produto — estão todos atrás de flags OFF.

**Veredito de readiness:** o Vitali está pronto para **demonstração** e perto de pronto para **piloto
controlado com dado sintético**. Não está pronto para **produção com dado clínico real**, e está a **um
incidente de distância** de um problema de LGPD caso duas clínicas concorrentes sejam colocadas no mesmo
cluster hoje.

**A boa notícia é o custo do conserto.** Dos 5 bloqueadores de receita mais graves, quatro são de esforço
baixo: uma linha de nginx, uma variável de ambiente + gate de CI, um `_resolve_user()` copiado de um
middleware irmão, e uma correção de nome de tabela num script. O caro é o quinto — provar operacionalmente
que backup/restore funciona.

---

## 2. Readiness score por domínio

| # | Domínio | Score | Uma frase |
|---|---|---|---|
| 1 | Produto / roadmap / docs | **5/10** | Código à frente dos docs-primários, atrás dos docs-de-visão; 3 auto-auditorias honestas salvam a nota |
| 2 | Backend / API / multi-tenant | **7/10** | Denso e bem construído, com 4 furos críticos de isolamento — todos de conserto barato |
| 3 | Frontend / UX / fluxos clínicos | **8/10** | Zero mock, zero TODO, `tsc` limpo, 7/8 fluxos completos; falha em guarda de rota e acabamento |
| 4 | Imaging / DICOM / Orthanc | **6.5/10** | Identidade paciente↔estudo excelente; autorização de pixels vaza entre tenants e a ingestão está inerte |
| 5 | Segurança / LGPD / auditoria | **5/10** | Criptografia e trilha imutável acima da média; perímetro não fecha |
| 6 | Infra / deploy / CI / backup | **5/10** | Maquete de alta fidelidade: bem escrita, praticamente nunca executada |
| 7 | Testes / qualidade | **5/10** | Suíte grande e honesta no backend; 165 arquivos de teste do frontend nunca rodam no CI |
| 8 | Billing / TISS / SUS | **5/10** | Ponte clínico→financeiro é o melhor código do repo; catálogos vazios em produção anulam tudo |
| 9 | IA / wedges / integrações | **6/10** | Wedges determinísticos reais e honestos; PHI cru sai para provider externo sem de-identificação |
| 10 | Dívida de integração (git) | **7/10** | Integração saudável — 100% do trabalho está em master; a higiene é que está podre |

**Score composto ponderado: ~5,9/10.** Para produto clínico o número que importa não é a média e sim o
**mínimo nos eixos de segurança do paciente e do dado** — hoje **5/10** em segurança e em infra. É esse par
que define a data de GA, não o backend nem o frontend.

---

## 3. Mapa doc-vs-realidade

As promessas mais caras, cada uma conferida contra o código.

| Promessa (fonte) | Evidência no código | Status |
|---|---|---|
| 7 wedges AI-native, flag por tenant default OFF (`AI-NATIVE-WEDGES.md`) | `core/models.py:186` `is_enabled` default False; `core/constants.py:29-89`; 7 engines com ~2.400 LOC | **REAL** [E] |
| Dose-safety intercepta nos **3 portões** (`VISION-AI-NATIVE.md` §2) | Gate 1 `emr/views.py:1487`; Gate 2 `pharmacy/views.py:1148`; **Gate 3 beira-leito: nenhum hook em `MedicationAdministration`** | **PARCIAL** [E] |
| "O sistema conhece a dose correta para aquele paciente" | `dose_checker.py:184` só lê `DoseRule(validated=True)`; único CSV do repo tem 3 linhas `FAKE-ImportDrugA/B/C`; `formulary_import.py:327` força `validated=False` | **FACHADA (inerte)** — o doc admite (D-T1) [E] |
| Moat = flywheel que "melhora toda semana" (`VISION` §4) | **Zero** código que ajusta threshold/peso. 2/7 wedges rotulam desfecho; `ENGINE_VERSION` são constantes; `deterioration.py:237` chama de "future flywheel" | **FACHADA** [E] |
| TISS/TUSS RN 501 com XML + XSD real (`README`) | XSDs ANS 4.01.00 reais e carregados (`xml_engine.py:158`), **mas** `batch_envelope.xml.j2:28` omite o wrapper `guiasTISS`; templates emitem `dadosConsulta` (0 ocorrências no XSD); validação **não-bloqueante** (`views.py:1052`); **0 testes chamam `validate_xml`** | **FACHADA** [E] |
| Guia de honorários (`billing/models.py:280`) | Sem template — `xml_engine.py:96-100` cai no default e **renderiza como guia de consulta** | **FACHADA** [E] |
| Taxas e gases medicinais na conta (commit B6, `6023818`) | `InpatientFee` + `record_inpatient_fee` (`inpatient_billing.py:178`) — **verificado por mim: zero callers fora de testes**, sem serializer/viewset/URL/admin/signal | **FACHADA** [E✓] |
| Catálogos importados (CID-10 14.233, TUSS 54.139, CNES 627.706…) | ETLs em `scripts/catalogs/` são puros transformadores; `README.md:10` "dados NÃO são versionados"; **nenhuma migration de dados, fixture ou passo de CI carrega catálogo** | **PARCIAL — só staging** [E] |
| CBHPM / Simpro / Brasíndice (`CANONICAL_FEATURE_MAP` §5) | `core/cbhpm_models.py:42` + importer que exige CSV que você fornece; sem ETL, sem dado. **Brasíndice: 0 hits no backend inteiro** | **NÃO ACHADO** [E] |
| ADT/leitos, Centro Cirúrgico, SAE, PS/Manchester, Banco de Sangue = "falta" (`CANONICAL_FEATURE_MAP`, 26/07) | `emr/adt_models.py:161`, `emr/surgery_models.py:121`, `emr/sae_models.py:67`, `emr/views_emergency.py`, `emr/transfusion_models.py` — **todos existem, com UI e testes** | **DOC DESATUALIZADO** [E] |
| Telemedicina "✅ tem" (`CANONICAL_FEATURE_MAP` §2) | 1 model, 147 LOC; `models.py:1-23` declara WebRTC como fora de escopo; **zero** Jitsi/Twilio/WebRTC; sem FK para `Encounter`; sem página no frontend | **FACHADA** [E] |
| i18n / 4 idiomas (`PROJECT_BRIEF` §6) | 4 `.po` × ~118 linhas = **25 msgids**; `next-intl` real mas **38 chaves** e usado em **4 de 284** `.tsx`; `nav.tsx:74` usa label literal — o menu nunca traduz | **FACHADA** [E] |
| "Staging com deploy automático via GitHub Actions" (`PLAN_GA_ROADMAP`) | `deploy-staging.yml` tem **1 job: build-and-push**; commit `9821342` removeu o step de SSH; `release-deploy.yml` com **zero execuções** | **FACHADA** [E] |
| MFA obrigatória para admin/médico (`SECURITY.md:288-303`) | `middleware.py:209` lê `request.user` **antes** da autenticação lazy do DRF; sem `SessionAuthentication` → bloco pulado para todo Bearer | **PROVAVELMENTE INOPERANTE** [E+H] |
| Isolamento de tenant ENFORÇADO (critério de GA) | **Verificado por mim:** `base.py:458` default `False`, e **ausente de `docker-compose.prod.yml` e `.staging.yml`** | **NÃO ATINGIDO** [E✓] |
| Direito de exclusão = "soft delete + anonymization pipeline" (`SECURITY.md:170`) | `grep anonymi\|erasure` em `apps/` → **zero** | **FALSO** [E] |
| Política de senha ≥12 (`SECURITY.md:62-68`) | `AUTH_PASSWORD_VALIDATORS` definido em `base.py:135-140` e **nunca chamado** (`grep validate_password` → zero); `views.py:197` aceita 8 | **FALSO** [E] |
| `docs/IMAGING.md:10,36-38` "order flow **pre-creates** a DicomStudy row" | Nenhum código cria `DicomStudy` a partir de pedido/MWL. Só POST manual. É a premissa de todo o documento | **FALSO** [E] |
| `docs/I18N.md` "Frontend has no i18n library" | `next-intl@^3.26.5` instalado e funcionando desde o PR #137 | **DOC MENTE SOBRE O PRÓPRIO CÓDIGO** [E] |
| `COMPLIANCE_CHECKLIST.md` (gate pré-produção) | **13 de 13 itens desmarcados**, assinatura em branco | **GATE NUNCA PASSADO** [E] |
| Concessão/comodato = "lacuna mais nítida do mercado" | Código **REAL**: 18 models, 5 módulos de view, 121 testes. A *claim de mercado* não é verificável no repo | **REAL / claim não verificável** [E+B] |

---

## 4. Implementado de verdade

Isto é o patrimônio do projeto e precisa ser dito com a mesma clareza dos defeitos.

**Clínico.** Sete fluxos ponta-a-ponta que persistem dados: PS com classificação de risco Manchester sobre
catálogo governado (`core/manchester_catalog_models.py` + `TriageClassifyModal.tsx`, 13 POSTs); internação/ADT
com bed board, transferência, alta planejada e housekeeping; CPOE com `PrescriptionBuilder` → farmácia FEFO →
checagem BCMA à beira do leito com os cinco certos; laboratório com microbiologia, antibiograma S/I/R e
anatomia patológica com CID-O governado por FK; centro cirúrgico com checklist, equipe, intraop, PACU e
turnover obrigatório; enfermagem/SAE em quatro etapas; hemoterapia com sorologia, reserva, crossmatch e
reações transfusionais.

**Arquitetural.** `import-linter` com contrato `domain-independence` sobre 16 apps, com 46 exceções
*grandfathered* congeladas e duplicado como teste pytest — a fronteira EMR↔billing é atravessada por sinal
com payload primitivo, não por import. RBAC com **zero** views caindo no default nu (auditoria AST: 129 via
`permission_classes`, 182 via `get_permissions`), e autorização por capability não-forjável, com o comentário
em `permissions.py:31-53` documentando o finding A01 que motivou não usar `role.name`.

**Segurança de dado.** `AuditLog` append-only com **três triggers Postgres** (`core/migrations/0019`) que
derrubam `UPDATE`, `DELETE` e `TRUNCATE`, inclusive por SQL cru — o controle mais forte do repositório.
Criptografia Fernet em ~15 campos de PII de paciente, com teste que lê a coluna crua via `cursor.execute` e
exige o prefixo `gAAAAA`. Lockout progressivo por IP+e-mail, Argon2id, resposta genérica que evita oráculo de
enumeração cross-tenant. Todos os 6 webhooks `AllowAny` validam segredo com `hmac.compare_digest` e falham
fechado. Zero injeção SQL, zero segredo em arquivo versionado, zero `# nosec`.

**Financeiro.** A ponte clínico→financeiro é o melhor código do repositório: diária de leito com evento
`admission_pre_bed_release` antes de soltar o leito mais varredura diária às 02:00 UTC; OPME cirúrgico com
glosa para material sem preço; medicamento dispensado virando linha de conta via `TUSSCode.anvisa_registro`.
Atomicidade e idempotência consistentes (`UniqueConstraint(admission, service_date)`,
`dispensation_source_id`, `surgical_material`).

**Interoperabilidade.** Servidor FHIR R4 read-only com 11 recursos × {search, read}, paginação RFC5988, e
SMART-on-FHIR **real** — PKCE verificado, código single-use queimado por UPDATE condicional, `client_secret`
em `compare_digest`, e enforcement de escopo com confinamento de compartimento de paciente fail-closed.

**Frontend.** Zero mock, zero TODO/FIXME, `npx tsc --noEmit` sai limpo, `nav.tsx` com correspondência 1:1 com
as rotas, refresh de token single-flight correto com tratamento de sessão expirada, CSP com nonce por request,
424 atributos ARIA.

**Imaging.** Verificação de identidade DICOM *fail-closed* com desambiguação cross-tenant: exige `PatientID`
não-vazio, igual, e mesmo issuer; UID ambíguo entre tenants não escreve em nenhum; o PATCH manual não confia
no browser e reexecuta a verificação server-side. 26 testes só nisso.

**Honestidade em código.** `sus_remessa.py:20` declara a própria não-conformidade byte-exata ao DATASUS;
`views_telemetry.py:66` se recusa a inventar métrica; `retorno_parser.py:191` se recusa a adivinhar glosa.
Isso é raro e vale registrar.

---

## 5. Fachadas, stubs e parciais

| Item | Natureza | Evidência |
|---|---|---|
| **O flywheel** | Fachada — é a tese central de defensabilidade e nada aprende | zero código de recalibração; `ENGINE_VERSION` hardcoded |
| **Portão 3 da dose** (beira-leito) + formulário de dose | Inerte por decisão; o pitch vende 3 portões, existem 2 | `dose_checker.py:184`; fixture com 3 linhas FAKE |
| **XML TISS** | Fachada de conformidade: XSD real que o gerador provavelmente não satisfaz, validação não-bloqueante, 0 testes de validação | `batch_envelope.xml.j2:28`, `views.py:1052` |
| **Guia de honorários** | Choice de model sem gerador nem template — geraria XML errado | `xml_engine.py:96-100` |
| **`InpatientFee` / taxas e gases (B6)** | Model + serviço + 357 linhas de teste, **zero** caminho de entrada | verificado: 1 única ocorrência, a própria `def` |
| **Catálogos em produção** | ETL real, carga 100% manual, nunca feita fora de staging; saída silenciosa (log INFO) quando vazio | sem `RunPython`/`loaddata`/step de CI |
| **Telemedicina** | Casca: sem vídeo, sem prontuário na sessão, sem assinatura, sem página | `telemedicine/models.py:1-23` |
| **`apps/mobile`** | `_NoProviderAdapter` retorna "no push provider configured" e é o adapter default | `mobile/services/push.py:52-76` |
| **`PrescriptionSafetyChecker` e `services_cid10`** | **Código morto**: `getattr(config, "ai_prescription_safety", False)` sobre campo que não existe em `TenantAIConfig` → sempre False. Ainda queima uma task Celery por item prescrito | `prescription_safety.py:113`, `core/models.py:345-390` |
| **MWL / C-ECHO / MPPS** | Tabelas e journal HTTP com nomes de protocolo DICOM que ninguém fala; **zero** `pynetdicom`/`pydicom`/`dcmtk` no backend | `imaging/services/workflow.py:9-19` |
| **Laudo de imagem** | Vínculo sem fluxo: só vinculável na criação, sem PATCH, sem estrutura, e `apps/signatures` não conhece laudos | `imaging/urls.py:26-45`, `signatures/models.py:32-41` |
| **Assinatura ICP-Brasil** | Mecanismo real, mas truststore vazio ⇒ **fail-open**, revogação CRL/OCSP OFF por default, e `is_icp_brasil` auto-declarado no caminho do EMR | `base.py:448`, `ICP_BRASIL.md:155` |
| **i18n** | 25 msgids no backend, 38 chaves no frontend, menu não traduz | `nav.tsx:74` |
| **`stockout_safety` e `no_show_prediction`** | Descritos como "interceptam"; só rodam por Celery Beat noturno + GET — não interceptam nada | sem hook de workflow |
| **`WaitingTimeView`** | Retorna `average_minutes=0` com comentário admitindo placeholder | `analytics/views.py:349-355` |
| **`NFeWebhookView`** | Lê `settings.NFE_WEBHOOK_SECRET`, que não existe em settings nenhum → sempre 401 | `pharmacy/views.py:257` |
| **`docs/WEDGE_ACTIVATION.md`** | Descreve flags `WEDGE_WAVE_1/2` e `FEATURE_AI_GLOBAL` que **não existem** | grep: zero ocorrências |

---

## 6. Dívida de integração — tese refutada

**A hipótese inicial estava errada e é importante registrar isso.** A leitura superficial do repositório
(21 branches `looper/*`, ~80 worktrees, 2 PRs abertos) sugeria trabalho valioso preso fora de master. A
investigação refutou:

- **92 das 103** branches locais não-master têm `git rev-list --count master..<branch>` = **0**.
- Das 11 restantes, **8** têm `git cherry master <b>` = 0 (patch equivalente já em master, hash diferente por
  squash).
- Sobram **3**, e as três já estão em master por outro caminho (`git ls-tree` confirma os arquivos-chave).
- **186 PRs: 179 merged (96,2%), 5 fechados sem merge, 2 abertos.** Dos 5 fechados, 4 são rollups do
  Dependabot superseded e 1 (#12) teve o conteúdo landado via PR #20.
- As branches `looper/*` correspondem a **PRs #135–#155, todos MERGED**.

**Trabalho valioso não integrado: zero.** O padrão do repositório é agente cria worktree → PR → merge por
squash → ninguém apaga nada. O acúmulo é de **ponteiros**, não de trabalho.

**Contradição resolvida.** O agente de IA/integrações afirmou que a triagem só existia em `looper/122`. **Eu
verifiquei diretamente e é falso**: o merge `938ed2a` (PR #152) está em master, `backend/apps/whatsapp/fsm.py`
e `backend/apps/triage/services/notifications.py` existem em master, e há 7 arquivos de `apps/whatsapp`
referenciando triagem. A afirmação de que a triagem "não está conectada" está **refutada**.

**O que de fato está podre:**

| Item | Número | Impacto |
|---|---|---|
| Branches locais mortas | 103 (100 já em master, 3 superseded) | Ruído de triagem |
| Worktrees vivos | 82 (81 apontando para commits já em master; 34 "sujos", todo conteúdo já em master; 1 locked) | **2,5 GB** |
| Uso do volume | 86 G de 110 G — **82%** | Risco operacional no host PVE |
| PR #173 (`fix/production-tenant-engine`) | Aberto há 27 dias, `CONFLICTING` | **Fix já está em master via PR #177, no mesmo dia, ~3h30 depois.** É PR zumbi sinalizando falsamente bug de produção não corrigido → **fechar** |
| PR #210 (dependabot) | `MERGEABLE`/`CLEAN`, ignorado | Padrão histórico: rollups de actions viram stale e são fechados |
| Colisões de migration | **Zero pendentes.** As duplicatas (`emr/0034` ×4, `pharmacy/0025` ×2) já estão resolvidas em master por `0036_merge` e `0026_merge` | Não é bloqueio |
| `ci.yml:5,7` | Dispara em `main` e `develop`, que não existem em `origin` | Ruído inofensivo |

---

## 7. Riscos clínicos, de LGPD e de segurança

Ordenados por gravidade. Cada um com o cenário concreto.

### 7.1 — Vazamento de prontuário entre clínicas concorrentes `[CRÍTICO]`

Três furos que se **compõem**:

1. `ENFORCE_TENANT_MEMBERSHIP` é `False` por padrão (`base.py:458`) e **não é setado em nenhum compose de
   produção** — verificado por mim. Com a flag off, `enforce_request_membership` (`tenant_auth.py:89-90`) é
   no-op: **um JWT emitido no domínio da Clínica A é aceito no domínio da Clínica B** (mesmo `SECRET_KEY`,
   mesma tabela `User` pública).
2. O nginx **não remove `X-Forwarded-Host` do cliente** nas locations de API — verificado: 9 das 10 locations
   setam `Host $host` mas só uma seta `X-Forwarded-Host`. Com `USE_X_FORWARDED_HOST=True` (`base.py:104`), o
   header do cliente escolhe o schema. `[E]` para a config; `[H]` para a exploração, que depende do
   `ALLOWED_HOSTS` real de produção.
3. Existe um system-check (`core.E002`) que falharia se a flag estivesse off em produção — mas é
   `deploy=True` e **nenhum workflow roda `manage.py check --deploy`**. O gate é decorativo.

**Cenário:** usuário autenticado da Clínica A envia `X-Forwarded-Host: clinicab.vitali.app` →
`TenantMainMiddleware` troca o schema → lê prontuários da Clínica B com o próprio token.

### 7.2 — Listagem global de usuários e papéis `[CRÍTICO]`

Verificado por mim em `core/views.py:682`: `UserListCreateView.get_queryset()` retorna
`User.objects.select_related("role").filter(is_active=True)` — **sem qualquer filtro por tenant**, sobre uma
tabela do schema público, com `GET` gated apenas por `IsAuthenticated`. O comentário no código mostra que a
abertura da listagem foi deliberada ("Listing stays available to any authenticated tenant user") mas o
escopo por tenant foi esquecido.

**Cenário:** recepcionista da Clínica A chama `GET /api/v1/users/` e recebe nome completo, e-mail e papel de
**todos os usuários de todas as clínicas da plataforma**.

O mesmo vale para `Role`, que não tem FK para `Tenant` (`core/models.py:592`): o namespace de RBAC é
compartilhado entre concorrentes.

### 7.3 — Celery sem propagação de schema quebra a segurança de prescrição `[CRÍTICO]`

Não existe `tenant_schemas_celery`, `task_prerun` nem base task custom. Dez tarefas recebem **só o ID** do
objeto: `check_prescription_safety(item_id)`, `generate_soap_task`, `cascade_no_show`,
`notify_next_waitlist_entry`, entre outras.

**Cenário:** médico prescreve → `emr/signals.py:73` enfileira `check_prescription_safety.delay(id)` → o
worker está no schema `public`, onde `emr_prescriptionitem` não existe → `ProgrammingError` a cada retry, e
**nenhum alerta de segurança de prescrição é gerado**. Pior caso `[H]`: conexão reaproveitada após um
`schema_context` que falhou em restaurar → a query roda **no schema errado**.

O bug é invisível na suíte porque os testes usam `CELERY_TASK_ALWAYS_EAGER=True`, que executa no schema do
request. Merece 15 minutos de reprodução com worker real antes de virar incidente.

### 7.4 — PHI cru para provider externo sem de-identificação `[CRÍTICO — LGPD]`

- **Áudio bruto da consulta → OpenAI** (`emr/services/whisper.py:53-59`, até 25 MB). Contém nome do paciente,
  queixa, diagnóstico e **voz** — biometria, dado sensível pelo art. 5º II da LGPD. Zero anonimização, e
  **sem `AIUsageLog`** — chamada externa com PHI sem trilha de auditoria.
- **Transcrição clínica integral → Anthropic** (`ai/services_scribe.py:84`, até 10.000 caracteres), sem
  remoção de nome/CPF/data de nascimento.
- **CID-10 + código ANS da operadora → Anthropic** no `GlosaPredictor` (`ai/services.py:544`), que **não
  checa DPA nenhum** e cujo kill-switch `FEATURE_AI_GLOSA` é o único default **`True`** de todo o conjunto.
- `AIUsageLog.input_text` grava 500 caracteres em **texto plano** (`ai/models.py:59`).
- O DPA é contrato clínica↔Vitali; **não há base legal registrada do titular**.

### 7.5 — Vazamento cross-tenant de imagens médicas `[CRÍTICO]`

`docker/nginx/nginx.conf:140-155` proxia `/imagens-dicom/` injetando a **credencial admin** do Orthanc,
gated apenas por `auth_request` → `MeImagingViewerAuthorizationView`, que em
`patient_portal/views_imaging.py:74-78` devolve `204` para **qualquer URI** se o usuário tiver
`imaging.read`. O Orthanc é **um só, compartilhado por todos os tenants**, sem Labels, sem AET por tenant,
sem filtro no proxy.

**Cenário:** técnico da Clínica A faz `GET /imagens-dicom/studies` (QIDO sem filtro) → 204 → nginx assina com
admin → recebe StudyInstanceUIDs, nomes e PatientIDs de **todas as clínicas**; em seguida busca os pixels.
Não é bug, é o comportamento programado. Ironicamente, o **paciente** no portal é muito melhor protegido
(validação por UID, recusa de QIDO multi-UID, 403 uniforme anti-enumeração).

### 7.6 — MFA provavelmente é teatro `[CRÍTICO]`

`MFARequiredMiddleware` (`core/middleware.py:209-213`) lê `request.user` e `request.auth` **antes** da
autenticação lazy do DRF, e não há `SessionAuthentication` configurada. Para todo request Bearer,
`request.user` é `AnonymousUser` → o bloco inteiro é pulado.

**Prova por contraste:** o `PasswordChangeRequiredMiddleware`, escrito depois, tem um `_resolve_user()` que
autentica o JWT explicitamente no middleware, com comentário dizendo exatamente por quê. O MFA nunca recebeu
esse fix, e nenhum teste HTTP cobre o middleware.

Agrava: `frontend/app/api/auth/mfa-complete/route.ts:12-49` aceita `{access, refresh}` **do corpo da
requisição** e grava nos cookies sem validar assinatura nem chamar o Django.

**Este achado é `[E+H]` e merece 5 minutos de `curl` autenticado antes de ser tratado como fato.**

### 7.7 — Recuperação de dado clínico nunca provada `[CRÍTICO — operacional]`

`scripts/restore_test.sh:113` consulta `SELECT count(*) FROM tenants_tenant`. Verificado por mim: o
`TENANT_MODEL` é `core.Tenant` (`base.py:61`), a model não define `db_table`, logo a tabela é `core_tenant`,
e `grep` por qualquer das duas strings no `backend/` retorna **zero**. O drill **falha por construção** —
prova positiva de que jamais rodou verde contra um backup real.

Somado a: nenhum agendador roda o drill; `db-backup` não tem healthcheck; e **não existe Alertmanager**
(`grep alertmanager` → vazio), então as 5 regras Prometheus avaliam e morrem no UI. **Um backup que pare de
rodar não gera sinal nenhum.**

### 7.8 — Riscos altos adicionais

- **Estudo DICOM órfão é descartado silenciosamente.** Não há criação automática de `DicomStudy` a partir de
  pedido/MWL, então o caso *comum* é o órfão: modalidade envia, Django não acha a linha, loga e descarta com
  o cursor avançando. **Exame feito e perdido**, sem fila de reconciliação nem alerta.
- **`ORTHANC_URL` ausente de todo compose e `.env*.example`** → no stack entregue o webhook responde
  `200 {"inert": true}` e nenhuma imagem chega à UI.
- **`TISSGuide` editável após submissão**, sem trava de estado e **sem auditoria**: alguém muda
  `provider`/`competency` de guia já enviada e a remessa deixa de bater com o que a operadora recebeu, sem
  rastro de quem mudou.
- **Auditoria de leitura em 2 de ~40 viewsets clínicos.** Prescrição, laboratório, imagem, SOAP e evolução de
  enfermagem não registram quem leu — e `list` nunca é auditado, então varrer a base via `?search=` não deixa
  rastro. CFM 1.821 exige rastreabilidade de acesso.
- **JWT espelhado em cookie legível por JS** (`access_token_js`), com CSP em report-only por default.
- **`verify=False`** no download do truststore ICP-Brasil (`refresh_icp_truststore.py:109`): MITM injeta CA
  forjada e passa a assinar prescrições como válidas.
- **13 grupos de rota clínica fora do `middleware.ts`** — verificado: `PROTECTED_PATH_PREFIXES` tem 11
  entradas e não inclui `/internacao`, `/pronto-socorro`, `/centro-cirurgico`, `/laboratorio`,
  `/banco-de-sangue`, `/enfermagem`, `/imagens`, `/administracao`, `/concessao`, `/painel-setor`,
  `/deterioracao`, `/faltas`, `/wedges`. O dado não vaza (backend responde 401), mas a UX quebra e o `next=`
  se perde.
- **Busca de paciente decripta a base inteira por request** (`emr/filters.py:18-59`) — DoS autenticado em
  escala hospitalar.
- **Vitest fora do CI** — verificado: `ci.yml` tem 5 jobs (`backend-lint`, `backend-test`, `frontend-lint`,
  `frontend-e2e`, `docker-validate`) e **nenhuma ocorrência de `vitest`/`npm run test`**. 165 arquivos de
  teste de frontend podem quebrar sem bloquear merge.

---

## 8. Qualidade da suíte de testes

O backend tem **3.250 funções de teste** em 310 arquivos, rodando contra Postgres real em schema de tenant
(`TenantTestCase`, 445 usos), sem os anti-padrões clássicos: **zero** `assert True`, zero teste vazio, um
único `skipif` (condicional e documentado), zero `xfail`, e mocks que substituem apenas a fronteira externa
(o LLM), nunca a lógica sob teste. Isso é uma suíte honesta.

Os problemas são estruturais, não de qualidade individual:

- **165 arquivos de teste de frontend nunca rodam no CI.**
- **Isolamento físico cross-tenant é essencialmente não testado.** Apenas 2 arquivos criam um segundo tenant
  de verdade. O teste que mais se aproxima disso (`test_auditlog_tenant.py:29-36`) nunca troca de schema —
  só seta o campo `schema_name` manualmente e verifica o filtro Python. É válido para o design do
  `AuditLog`, mas **não prova isolamento de schema Postgres**. Dado que 4 dos furos críticos são
  precisamente de isolamento, essa é a lacuna de teste mais cara.
- **O `.coverage` da raiz não é evidência utilizável.** Datado de 22/07, mostra 7% global, com `views.py` e
  `serializers.py` de *todo* app em exatamente 0% enquanto `models.py` marca 40-48% — assinatura de captura
  em tempo de import, não de execução. Contradiz centenas de testes que comprovadamente usam `APIClient`.
  Snapshot quebrado; a cobertura real está no Codecov do CI, fora do nosso alcance nesta sessão.
- **E2E cobre 5 fluxos** (auth, jornada clínica, upload de formulário, onboarding RH, convite). Billing, SUS,
  farmácia, imaging, hemoterapia e segurança de dose têm **zero** cobertura E2E.
- `[E]` Rodando `vitest` de verdade no host, **15 de 165 arquivos falharam por timeout de worker e o processo
  saiu com código 0** — se isso se reproduzir sob carga em CI, é um jeito de a suíte "passar verde" com
  arquivos inteiros nunca executados.

---

## 9. O que não foi verificado

Registro explícito dos limites desta auditoria. Nada aqui deve ser lido como "está tudo bem".

**Bloqueios de ambiente `[B]`:**
- **A suíte de backend não foi executada.** O usuário `rcosta00` não pertence ao grupo `docker` e `sudo` é
  bloqueado pelo guard do Maestro; os testes rodam dentro do container `django`. Toda avaliação de backend é
  estática. *(Um compose local quebrado — `security_opt` duplicado entre `docker-compose.yml:7` e o
  workaround AppArmor host-local — foi corrigido com `!override` no arquivo fora do repo; o working tree não
  foi tocado.)*
- Playwright, `next build` e migrations não foram executados.
- Estado do host de staging `vitali-demo.qtec.me` não inspecionado. Se o beta subiu, parte dos gaps de
  configuração pode estar resolvida **naquele host** — mas não está no repositório e portanto não é
  reproduzível.
- `gh api /users/tropeks/packages` retornou 403 (token sem `read:packages`): as conclusões sobre tags no GHCR
  vêm apenas da leitura dos workflows.
- Conteúdo de `.env` e `.env.staging` não transcrito, por política de segredos.

**Achados que são hipótese e precisam de confirmação empírica `[H]`:**
- Inoperância do `MFARequiredMiddleware` — 5 minutos de `curl` autenticado resolvem.
- Schema efetivo da conexão do worker Celery — 15 minutos de reprodução com worker real.
- Exploração do `X-Forwarded-Host` — depende do `ALLOWED_HOSTS` real de produção.
- QIDO cross-tenant sem filtro no Orthanc, e possível path traversal por `%2e%2e` no `proxy_pass` sem URI.
- Se os templates Jinja2 do TISS satisfazem o XSD campo a campo (confirmado apenas que `validate_xml` roda
  contra o XSD real, e que 0 testes o chamam).
- Se a remessa BPA/APAC/AIH seria aceita pelo DATASUS — o próprio código afirma que **não**.

**Fatos externos ao repositório:**
- Versão TISS mandatória pela ANS em 2026. O repo tem XSD 4.01.00 e o próprio `TODOS.md` menciona 4.02.00+.
  **Se o mandato vigente for 4.02+, o módulo inteiro é infaturável** — esta é a incerteza de maior impacto
  comercial de toda a auditoria e não é resolvível a partir do código.
- Política de retenção e treinamento da Anthropic e da OpenAI para estas contas.
- Contagens reais de catálogo em staging.
- Configuração de alertas dentro do SaaS Sentry.

---

## 10. Documentos irmãos

- **`VITALI_GAPS_AND_IMPROVEMENTS.md`** — gaps classificados por severidade e melhorias por alavancagem.
- **`VITALI_EXECUTION_WAVES.md`** — plano de execução em ondas P0–P3, estratégia de swarm e gates.
