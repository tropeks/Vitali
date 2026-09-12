# Vitali — Plano de Execução em Ondas

**Data:** 2026-08-17 · **HEAD:** `f966d04` · **Companheiro de:** `VITALI_READINESS_REPORT.md` e
`VITALI_GAPS_AND_IMPROVEMENTS.md` · **Metodologia:** Maestro (roteamento por intenção, especialistas do
roster, gates humanos, evidência preservada)

---

## 0. Princípio ordenador

A sequência não é por dificuldade nem por valor isolado — é por **o que destrava o quê**:

> **Fechar o perímetro → provar a recuperação → ligar o que já existe → aprofundar → só então expandir.**

O Vitali não precisa de features novas para virar produto vivo. Precisa que o que já está construído seja
**seguro de operar** e **possível de recuperar**. Cinco dos seis bloqueadores da Onda 0 são de esforço baixo;
o valor está na sequência, não no volume.

**Regra de ouro do plano:** nenhuma onda posterior começa antes que a anterior tenha **evidência publicada** —
não "o agente disse que fez", mas saída de comando colada no PR.

---

## Onda 0 — PERÍMETRO `[P0 · bloqueia qualquer dado real]`

**Objetivo:** tornar impossível que a Clínica A leia o prontuário da Clínica B, e provar que MFA não é teatro.

| Item | O que fazer | Owner sugerido | Esforço |
|---|---|---|---|
| 0.1 | `proxy_set_header X-Forwarded-Host $host;` nas locations de API do `nginx.conf` e `ssl.conf` | `dev-pleno` | P |
| 0.2 | `ENFORCE_TENANT_MEMBERSHIP=True` nos composes de staging/prod, após `backfill_tenant_memberships` | `python-pro` | P |
| 0.3 | `manage.py check --deploy` como step **bloqueante** do CI | `dev-pleno` | P |
| 0.4 | `UserListCreateView.get_queryset()` filtrado por `memberships__tenant=connection.tenant`; `RoleListCreateView` e os dois `PrimaryKeyRelatedField` de `core/serializers.py` idem | `python-pro` | P |
| 0.5 | `Role` ganha FK nullable para `Tenant` (system roles com `tenant=None`) + migration + backfill | `postgres-pro` + `python-pro` | M |
| 0.6 | `MFARequiredMiddleware` recebe o `_resolve_user()` do `PasswordChangeRequiredMiddleware`; `mfa-complete` valida o token via `/api/v1/me` antes de gravar cookie | `python-pro` + `typescript-pro` | P |
| 0.7 | Fechar DICOMweb por estudo também para staff, reusando a resolução por UID do ramo do paciente | `python-pro` | P |

**Pré-requisito de investigação (antes de codar 0.6):** confirmar empiricamente a inoperância do
`MFARequiredMiddleware` com um `curl` autenticado. É achado `[H]`; 5 minutos decidem se o item existe.

**Critérios de aceite — todos por teste automatizado que TENTA o ataque:**
- Requisição com `X-Forwarded-Host` de outro tenant → **400/401**, nunca 200.
- JWT emitido no tenant A usado no domínio do tenant B → **401**.
- `GET /api/v1/users/` autenticado no tenant A → **zero** usuários do tenant B no corpo.
- `GET /api/v1/roles/` no tenant A → **zero** papéis criados pelo tenant B.
- Requisição Bearer de usuário com MFA obrigatória e não verificada → **403**, e o teste é HTTP
  ponta-a-ponta, não unitário sobre o helper.
- `POST /api/auth/mfa-complete` com token forjado → **rejeitado**.
- `GET /imagens-dicom/studies` (QIDO sem UID) por staff → **403**.
- CI falha se `ENFORCE_TENANT_MEMBERSHIP` estiver off com `DEPLOYMENT_PROFILE=pool`.

**Testes de regressão:** suíte completa de `core` + `emr` + `patient_portal`; gate tree-wide
(`ruff check .`, `ruff format --check .`, `mypy`, `lint-imports`).

**Rollback:** todos os itens são reversíveis por revert de commit. O 0.2 é reversível por variável de
ambiente sem redeploy. O 0.5 é o único com migration — exige `backfill` idempotente e migration reversível
testada nos dois sentidos.

**Risco da onda:** ligar `ENFORCE_TENANT_MEMBERSHIP` **vai** derrubar usuários sem `UserTenantMembership`
materializada. O backfill precisa rodar e ser conferido **antes** do flip, em staging, com contagem
antes/depois publicada.

---

## Onda 1 — RECUPERAÇÃO E SINAL `[P0 · bloqueia dado clínico real]`

**Objetivo:** poder afirmar, com evidência, que um backup do Vitali já foi restaurado — e que uma falha
noturna chega a um humano.

| Item | O que fazer | Owner | Esforço |
|---|---|---|---|
| 1.1 | `restore_test.sh`: `tenants_tenant` → `core_tenant` | `dev-junior` | P |
| 1.2 | Rodar o drill **de verdade** contra um dump real; publicar a saída | `qa` | M |
| 1.3 | Agendar o drill semanalmente (systemd timer ou workflow agendado) | `dev-pleno` | P |
| 1.4 | Alertmanager no overlay + bloco `alerting:` no `prometheus.yml` + rota real (Telegram/e-mail) | `dev-pleno` | M |
| 1.5 | Alerta `VitaliBackupStale` (idade do último dump > 26h) + healthcheck no `db-backup` | `dev-pleno` | P |
| 1.6 | Tornar `BACKUP_ENCRYPTION_KEY` obrigatória em produção (hoje é opcional e o dump vai em claro) | `python-pro` | P |
| 1.7 | Propagar schema de tenant no Celery (base `Task` + `task_prerun`) | `python-pro` | M |
| 1.8 | Job `frontend-unit` no CI rodando `vitest`; garantir exit ≠ 0 em falha de worker | `typescript-pro` | P |

**Critérios de aceite:**
- Saída do `restore_test.sh` colada no PR, verde, com contagem de tenants e de pacientes restaurados.
- Um alerta de teste disparado de ponta a ponta e **recebido** — screenshot ou log do destinatário.
- Teste que executa uma tarefa Celery por-ID com `ALWAYS_EAGER=False` a partir do schema público e afirma
  que ela escreveu no schema correto.
- `check_prescription_safety` gera alerta em ambiente com worker real.
- CI vermelho se qualquer teste vitest falhar.

**Rollback:** 1.1–1.6 são aditivos ou de configuração. O 1.7 mexe no caminho de toda tarefa assíncrona —
merece feature flag (`CELERY_TENANT_PROPAGATION`) e um período de observação em staging antes de prod.

---

## Onda 2 — RECEITA DESTRANCADA `[P1]`

**Objetivo:** o que já está construído passa a gerar dinheiro em vez de ficar inerte.

| Item | O que fazer | Owner | Esforço |
|---|---|---|---|
| 2.1 | Endpoint + serializer + tela para `record_inpatient_fee` (taxas e gases medicinais, B6) | `python-pro` + `typescript-pro` | P |
| 2.2 | Idempotência em `record_inpatient_fee` antes de expô-lo | `python-pro` | P |
| 2.3 | Guard de imutabilidade + `_write_audit` em `TISSGuideViewSet.perform_update` para guias não-draft | `python-pro` | P |
| 2.4 | Teste de conformidade: `validate_xml(...).valid is True` para SADT, internação e lote; corrigir o wrapper `guiasTISS` e os elementos fora do XSD | `python-pro` | M |
| 2.5 | Idem para a remessa SUS (BPA/APAC/AIH), ou registro explícito da distância ao layout oficial | `python-pro` | M |
| 2.6 | Passo de carga de catálogos no deploy + health-check que **acuse** catálogo vazio | `dev-pleno` | M |
| 2.7 | Corrigir `seed_demo_data` para não colidir com códigos reais de CNES/UCUM | `dev-junior` | P |
| 2.8 | Fechar ou remover `guide_type="honorarios"` | `dev-pleno` | P |
| 2.9 | `ORTHANC_URL` nos composes e `.env*.example` + smoke test que falha se o webhook responder `inert` | `dev-pleno` | P |

**Critério de aceite central:** um XML TISS gerado pelo sistema passa em `validate_xml` contra o XSD da ANS,
com o teste no CI. Sem isso, "gera guia" e "recebe dinheiro" continuam sendo coisas diferentes.

**Bloqueio externo:** 2.4 depende da decisão sobre a **versão TISS mandatória pela ANS em 2026**. Se for
4.02+, o escopo muda inteiro. Perguntar antes de começar.

---

## Onda 3 — CONFORMIDADE E TRILHA `[P1]`

| Item | O que fazer | Owner | Esforço |
|---|---|---|---|
| 3.1 | `phi_scrubber` antes de Whisper, Scribe e Glosa; `AIUsageLog` obrigatório em toda chamada externa, com `input_text` criptografado | `python-pro` | M |
| 3.2 | Decorator `@requires_ai_consent(feature)` unificando flag global + flag de tenant + DPA + teto; `FEATURE_AI_GLOSA` para default `False` | `python-pro` | P |
| 3.3 | `AuditReadMixin` em todo viewset que serve PHI + teste de contrato que falha se faltar `audit_resource_type` | `python-pro` | M |
| 3.4 | Endpoint de consulta da trilha de auditoria para o DPO do tenant | `python-pro` + `typescript-pro` | M |
| 3.5 | `AUTH_PASSWORD_VALIDATORS` efetivamente chamado nos 3 caminhos de senha | `dev-junior` | P |
| 3.6 | Remover `verify=False` do `refresh_icp_truststore` | `dev-junior` | P |
| 3.7 | Popular o truststore ICP e ligar revogação CRL/OCSP, ou marcar a assinatura como não-ICP na UI | `python-pro` | M |
| 3.8 | Eliminar `access_token_js`: mover `Authorization` para o proxy `app/api/[...path]` e ligar `CSP_ENFORCE=true` | `typescript-pro` | M |
| 3.9 | Preencher `COMPLIANCE_CHECKLIST.md` e o DPA com cláusulas reais de cifragem, retenção, subprocessador e notificação de incidente | **humano** (jurídico) | M |
| 3.10 | Fechar o gate de módulo-sem-papel nas 12 views de analytics e 2 de WhatsApp; trocar `is_staff` por `HasPermission` em `views_waitlist` e `views_mfa` | `python-pro` | M |

---

## Onda 4 — OPERAÇÃO REAL `[P2]`

| Item | O que fazer | Owner | Esforço |
|---|---|---|---|
| 4.1 | `deploy.sh` idempotente: pina `IMAGE_TAG=sha-<sha>`, backup pré-migration, `migrate_schemas`, smoke test, rollback automático para a tag anterior em falha | `engenheiro` (plano) + `dev-pleno` | M |
| 4.2 | Reescrever `ROLLBACK_PLAN.md` §4 e `DEPLOY.md:218` para o único caminho executável | `dev-pleno` | P |
| 4.3 | Exercitar produção ponta a ponta **uma vez** num host descartável, a partir de `gen_secrets.sh` + `docker-compose.prod.yml` puros | `qa` | G |
| 4.4 | Guarda `:?` em toda variável cujo valor vazio produz insegurança silenciosa; adicionar `CELERY_DATABASE_URL`, `GHCR_REPO`, `NEXT_PUBLIC_API_URL` ao `gen_secrets.sh` | `dev-pleno` | P |
| 4.5 | Cortar o CI de 41 min para < 15 (pytest `-n auto`; `docker-validate` só quando arquivos de infra mudam) | `dev-pleno` | M |
| 4.6 | Fazer `release-deploy.yml` rodar ao menos uma vez; produzir imagem semver | `dev-pleno` | M |
| 4.7 | Retenção/quota de storage do Orthanc | `dev-pleno` | M |
| 4.8 | Higiene de git: arquivar 103 branches como tags, remover 82 worktrees, `--delete-branch-on-merge`, fechar PR #173, decidir PR #210 | `dev-junior` | P |

**Nota sobre 4.8:** o plano de limpeza detalhado, com rede de segurança por tags, está em
`VITALI_READINESS_REPORT.md` §6. **Nada deve ser removido sem as tags de arquivo criadas e empurradas
primeiro.** Recupera ~2,5 GB num volume a 82%.

---

## Onda 5 — PRODUTO `[P2/P3]`

| Item | O que fazer | Owner |
|---|---|---|
| 5.1 | Inverter `middleware.ts` para deny-by-default com allowlist | `typescript-pro` |
| 5.2 | Corrigir as 14 classes CSS inexistentes + lint de classe `neu-*` não declarada | `typescript-pro` |
| 5.3 | Criar `DicomStudy` no ato do pedido + fila de estudos órfãos com tela de reconciliação | `python-pro` + `typescript-pro` |
| 5.4 | Fechar o loop de `/imagens` (worklist, laudo, status) ou rotular a tela honestamente como visualizador | `typescript-pro` |
| 5.5 | Ligar laudo de imagem ao `apps/signatures` (`DOCUMENT_TYPE_REPORT` + PATCH + ICP sobre o hash) | `python-pro` |
| 5.6 | Consertar ou apagar `ai_prescription_safety` e `ai_cid10_suggest` | `python-pro` |
| 5.7 | Adotar react-query envolvendo `apiFetch` | `typescript-pro` |
| 5.8 | Terminar o reskin nas 5 telas clínicas de maior tráfego | `typescript-pro` |
| 5.9 | Regerar `openapi.yaml` no CI e falhar o build no diff; aposentar seções divergentes do `API_SPEC.md` | `dev-pleno` |
| 5.10 | UI para `apps/triage`, ou removê-lo do `INSTALLED_APPS` | `typescript-pro` |
| 5.11 | E2E para billing/SUS e para segurança de dose/alergia | `qa` |
| 5.12 | Teste de isolamento **físico** de tenant (segundo schema real) por área sensível | `qa` + `postgres-pro` |

---

## Onda 6 — NARRATIVA `[P1 — pode correr em paralelo desde já]`

Independente das outras, sem risco técnico, e com o maior retorno por hora investida.

| Item | O que fazer | Owner |
|---|---|---|
| 6.1 | Reescrever o README (hoje descreve um produto menor do que existe) | `dev-pleno` |
| 6.2 | Cobrir os ~250 commits ausentes do CHANGELOG | `dev-pleno` |
| 6.3 | Escolher **um** roadmap; arquivar `PLAN_*` divergentes em `docs/archive/` | **humano** + `dev-pleno` |
| 6.4 | Registrar por escrito a virada estratégica de jul/ago e o porquê | **humano** |
| 6.5 | Corrigir `docs/IMAGING.md` (5 pontos), `docs/I18N.md`, `SECURITY.md` (8 contradições), `WEDGE_ACTIVATION.md` (flags inexistentes) | `dev-junior` |
| 6.6 | Aplicar ao `CANONICAL_FEATURE_MAP` a régua de maturidade por camada que ele mesmo propôs | `engenheiro` |

---

## 7. Estratégia de swarm

### 7.1 — O que funcionou nesta sondagem

Dez agentes read-only, um por domínio, com **contrato de saída idêntico**: veredito com score, evidência
separada de hipótese, tabela doc-vs-realidade, gaps classificados, top-5 de alavancagem, e uma seção
obrigatória **"não verificado"**. Essa última seção foi o que tornou o resultado confiável — cada agente
declarou os próprios limites em vez de preencher lacunas com plausibilidade.

Dois aprendizados que mudam o desenho das próximas ondas:

1. **Agentes discordam, e isso é informação.** O agente de integração refutou a hipótese de trabalho preso em
   branches — que era a *minha* leitura inicial. O agente de IA afirmou que a triagem não estava em master; a
   verificação direta mostrou que **está** (merge `938ed2a`, PR #152). Contradição entre agentes é sinal de
   onde o team manager precisa verificar pessoalmente, não ruído a ser mediado.
2. **Análise estática tem teto.** Os três achados de maior gravidade (`MFARequiredMiddleware` no-op, Celery
   sem schema, QIDO cross-tenant) são deduções de leitura. Cada um vale 5–15 minutos de confirmação
   empírica, e **nenhum deve virar incidente ou item de plano sem essa confirmação**.

### 7.2 — Contrato para agentes de execução

Diferente do de auditoria. Todo agente de implementação recebe:

- **Escopo fechado**: arquivos que pode tocar, e a proibição explícita de tocar em qualquer outro.
- **Teste primeiro**: o critério de aceite vem como teste que **falha antes** da mudança. Para os itens de
  perímetro, o teste é literalmente a tentativa de ataque.
- **Gate tree-wide**: `ruff check .`, `ruff format --check .`, `mypy apps/ vitali/`, `lint-imports` sobre a
  árvore inteira — não só o módulo tocado. *(Regra do projeto: verde local no módulo não garante CI verde.)*
- **Evidência colada**: saída real dos comandos no PR. "Rodei e passou" não é aceito.
- **Proibição de worktree isolation** — mandato registrado do projeto: o worktree pode partir de base
  desatualizada e introduzir erro de formato de endpoint. Agentes trabalham na árvore principal ou em branch
  criada a partir do HEAD atual.

### 7.3 — Paralelismo por onda

- **Onda 0**: os itens 0.1–0.4 e 0.7 são independentes → paralelizáveis. O 0.5 (migration em `Role`)
  **serializa** contra 0.4 — mesmo arquivo, mesma área.
- **Onda 1**: 1.1–1.6 (infra) e 1.7–1.8 (código) são frentes independentes → `mode: multi`.
- **Onda 2**: 2.4 e 2.5 (conformidade XML) são o caminho crítico; o resto paraleliza.
- **Onda 6**: totalmente paralela a tudo, sem risco de conflito.

Regra de conflito: **um agente por app do backend por vez**. `emr`, `billing` e `core` são os pontos quentes
— duas frentes simultâneas em `core` produzem conflito de migration com certeza.

### 7.4 — Consolidação

O team manager consolida, não repassa. Toda entrega de agente passa por: (a) o achado bate com o código que
eu li? (b) o teste realmente falha antes e passa depois? (c) contradiz algum outro agente? Contradição vai
para verificação direta, como foi feito com a triagem.

### 7.5 — Quando pedir aprovação

Gate humano **obrigatório**, sem exceção, antes de:

- Qualquer flip de flag que afete autenticação ou autorização em ambiente com dado real (0.2).
- Qualquer migration destrutiva ou que exija backfill (0.5).
- Qualquer alteração no caminho de deploy ou rollback (Onda 4).
- Remoção de branches ou worktrees (4.8) — mesmo com as tags de arquivo criadas.
- Qualquer decisão da tabela §6 de `VITALI_GAPS_AND_IMPROVEMENTS.md`.

Fora disso, o team manager decide e reporta.

---

## 8. Próximo passo imediato recomendado

**Onda 0, itens 0.1 a 0.4 e 0.7** — cinco mudanças pequenas, alto retorno, baixo risco, todas com teste que
tenta o ataque.

Antes de tocar em código, dois desbloqueios que dependem do Romulo:

1. **Acesso ao Docker.** `rcosta00` não está no grupo `docker` e `sudo` é bloqueado pelo guard. Sem isso a
   suíte de backend não roda e nenhuma onda pode ser validada localmente. *(O compose local já foi
   corrigido — o workaround AppArmor duplicava `security_opt` do postgres, que foi committado em
   `docker-compose.yml:7`; resolvido com `!override` no arquivo host-local, working tree intacto.)*
2. **Confirmação empírica dos três achados `[H]`** — 20 minutos somados, e definem se 0.6 e 1.7 são itens
   reais ou falsos positivos de leitura estática.

**Estado atual:** working tree preservado. As únicas mudanças são os três documentos em `docs/research/`.
Nenhum código de produto foi tocado, nenhuma branch criada, nenhum worktree removido, nenhum deploy feito.
