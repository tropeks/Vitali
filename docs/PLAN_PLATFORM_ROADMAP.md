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
- **S29 Data Curation Tooling** — ✅ backend (branch feat/sprint-29-data-curation, testado;
  aguardando merge). Gating `validated=True` no DoseChecker (regra não-validada → advisory,
  nunca SAFE silencioso) + `import_formulary`/`import_allergen_classes`/`import_drug_interactions`
  + `import_tuss --dry-run`/erros por linha. Migrations 0017–0019 (DoseRule.validated +
  provenance + UniqueConstraint natural-key com bands age/weight). Guard multi-tenant nos
  importers. Regressão 558 verde; /security-review 0 high-conf. **Pendente: UI de validação +
  readiness dashboard (S29-05) = pass de frontend.**
- **S30 Wedges Wave 1** (no-show, stockout, NEWS2) — [EXISTE engines] ligar flags + soak.
- **S31 Wedges Wave 2** (dose, glosa, alergia, controlled) — depende de dados curados.
- **S32 Compliance Pack GA** (assinatura ICP no fluxo, LGPD frontend, DPA/DPO).
- **S33 Pilot Onboarding & GTM** → GA.

### SPRINT R1 — Recepção, filas e chamadas omnichannel [NOVO]

Extensão do S-072: transformar o check-in/sala de espera em uma operação completa de
recepção, sem expor dados clínicos em telas públicas.

- R1-01 [ADAPTAR] **Totem de auto check-in** (PWA/tablet): QR Code, código da consulta,
  CPF/CNS, confirmação de presença, acessibilidade e fallback para a recepção.
- R1-02 [NOVO] **Motor de filas**: filas por profissional, especialidade, coleta e imagem;
  chamar, repetir, transferir, pausar, ausência e prioridades assistenciais; operações
  idempotentes e auditadas.
- R1-03 [NOVO] **Painel público de chamadas**: tela protegida por token, senha/iniciais
  (nunca PHI), sala/consultório, atualização SSE/WebSocket, áudio opcional e modo offline.
- R1-04 [ADAPTAR] **Console da recepção** integrado à agenda e à waiting room, com
  `arrived_at`/`started_at`, previsão de espera e sinalização de atrasos.
- R1-05 [ADAPTAR] **WhatsApp de fila**: opt-in/opt-out, confirmação de chegada, posição
  aproximada, aviso de chamada e atraso; mensagens sem diagnóstico/resultado e com
  trilha LGPD. Evolution API primeiro; adaptador Meta Cloud API depois.
- R1-06 [NOVO] **Portal do paciente**: status da fila, estimativa, aviso próximo da vez,
  check-in remoto quando permitido e histórico de chamadas.
- R1-07 [NOVO] **Integrações físicas**: impressora térmica de senha, navegador dedicado
  para TV/HDMI e múltiplos painéis por unidade.
- R1-08 [NOVO] **Segurança e contingência**: tokens de curta duração, anti-duplicidade,
  retenção mínima, RBAC, auditoria e procedimento manual quando rede/totem falhar.

**Critérios de aceite:** testes de contrato para fila/chamada, anti-IDOR no painel e
portal, acessibilidade WCAG básica, consentimento WhatsApp auditável, reconexão SSE e
smoke end-to-end totem → recepção → painel → WhatsApp.

## MATURIDADE DO PRODUTO — pós-MVP por validação

O Vitali não deve tentar entregar todas as capacidades hospitalares antes de validar o
MVP em clínicas reais. Cada camada abaixo só começa após evidência de adoção, retenção,
segurança e operação da camada anterior.

### M0 — MVP comercial validado

Produto vendável para clínicas pequenas: agenda, pacientes, prontuário, prescrição,
assinatura, portal, exames, financeiro básico, TISS essencial, estoque básico, RBAC,
auditoria, recepção/fila e WhatsApp transacional.

**Gate:** pelo menos uma clínica pagante operando atendimentos reais, onboarding
repetível, suporte mensurável, backup/restauração testados e nenhum incidente crítico.

### M1 — Pós-MVP: eficiência clínica e financeira

- Revenue cycle completo: autorizações, lotes TISS, glosas, recursos e repasse médico.
- Financeiro: contas a pagar/receber, DRE, centros de custo, conciliação bancária,
  PIX/cartão, NF e integração contábil.
- Estoque avançado: múltiplos locais, inventário, consignado, validade, compras sugeridas
  e controlados com rastreabilidade legal.
- **Entrada fiscal automatizada de estoque:** upload manual de XML, captura por e-mail,
  API/webhook de fornecedor, SFTP e consulta de NF-e destinada ao CNPJ com certificado
  digital. Validar chave, emitente/destinatário, duplicidade, cancelamento, itens, NCM,
  lote, validade, custo e impostos; mapear produto fiscal ao catálogo interno e exigir
  conferência/aprovação antes de efetivar a entrada. Suportar recebimento parcial,
  devolução, carta de correção e trilha do XML original. Para controlados, exigir dupla
  conferência e auditoria específica.
- Experiência do paciente: consentimento digital, pagamentos, NPS/CSAT e pós-atendimento.
- Integrações externas iniciais: FHIR/HL7 e laboratórios parceiros.

**Gate:** redução comprovada de trabalho manual, fechamento financeiro confiável e
retenção de clientes após 90 dias.

### M2 — Pós-MVP: operação enterprise ambulatorial

- RH operacional: escalas, ponto, férias, afastamentos, credenciamento e documentos.
- Qualidade: incidentes, eventos adversos, CAPA, protocolos e indicadores.
- Operação multiunidade: filiais, rateios, catálogos e permissões hierárquicas.
- Interoperabilidade expandida: FHIR/IHE, RNDS, DICOM router e integrações de parceiros.
- SSO empresarial, MFA adaptativo, ciclo de vida de acesso e relatórios de auditoria.

**Gate:** cliente com múltiplas unidades ou requisitos formais de compliance e SSO.

### M3 — Pós-MVP: hospitalar

- Internação: leitos, transferências, alta, enfermagem, balanço hídrico e acompanhantes.
- Pronto atendimento: classificação de risco, protocolos, observação e regulação.
- Centro cirúrgico: agenda, salas, checklist, anestesia, OPME e recuperação.
- Controle de infecção, comissão de óbito e indicadores de segurança do paciente.
- Folha de pagamento e eSocial, quando houver operação trabalhista própria relevante.

**Gate:** contrato hospitalar âncora, equipe de implantação dedicada e validação clínica
formal para cada módulo de alto risco.

### M4 — Pós-MVP: dados e ecossistema

- Data warehouse, BI executivo, cohortes, indicadores regulatórios e linhagem de dados.
- SIEM/DLP, PAM, gestão avançada de chaves, legal hold e e-discovery.
- API pública, webhooks, SDK, marketplace e parceiros certificados.
- Apps móveis profissionais/paciente e modo offline controlado.

**Regra de priorização:** dentro de cada maturidade, atacar uma capacidade por vez,
medir adoção e margem, corrigir segurança/operabilidade e só então iniciar a próxima.

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
