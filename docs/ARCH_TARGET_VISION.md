# Vitali — Arquitetura-alvo (documento de decisão)

> Cristalizado em 2026-06-13 a partir de um brainstorm que cruzou o teardown do LabX
> Enterprise (`uploads/00-05`, memória `labx-arch-for-next-project`) com a visão de
> produto do Romulo. É o norte arquitetural do Vitali. Vivo — revisar quando os
> gatilhos mudarem.

## 1. Visão de produto (o que estamos construindo)

Um ERP hospitalar que dá a **clínicas e hospitais pequenos/médios** a experiência e a
robustez de um SAP/Salesforce. **Cloud-native**, vendido como serviço gerenciado, com
**instância isolada por cliente** governada por uma **camada de administração (control
plane)**. Tiers atendem do consultório de 5 médicos ao hospital regulado.

Princípio-guia (do LabX, B3): **decompor por necessidade medida, não por dogma.** Não
viramos 35 microserviços. Destacamos poucos serviços, onde perfil/fronteira/segurança
justificam, e isolamos de verdade no nível da **instância**.

## 2. Modelo de implantação: frota de instâncias + control plane

A unidade de isolamento é a **instância**, não o microserviço. Cada cliente roda um
**monólito modular** (simples de operar, deployar, air-gap), e a inteligência de frota
vive no control plane.

### Tiers

| Tier | Cliente | Implantação | Tenancy | Custo |
|---|---|---|---|---|
| **Pool** | Clínica pequena (não exige isolamento) | Instância **compartilhada** | schema-per-tenant (django-tenants — já existe) | baixo |
| **Dedicado** | Hospital/regulado (exige isolamento/air-gap) | Instância **própria** | single-tenant (mesmo código, 1 schema) | maior |

O schema-per-tenant atual **não é desperdício** — é o motor do tier Pool. O perfil de
deploy é selecionado por `DEPLOYMENT_PROFILE` (`pool` | `dedicated` | `airgap`).

### Control plane (a peça que o LabX NÃO tinha — e por isso penou no A1)

Plano de gestão acima da frota. **v1 é scriptado, não um produto bonito** (registry de
instâncias em DB + provisão idempotente via IaC + dashboard simples). Vira produto depois.
Funções, em ordem de prioridade:

1. **Provisionar** instância nova — **idempotente e reentrante** (lição A1: identidade
   derivada no deploy, nunca semeada-uma-vez; nunca clonar estado).
2. **Atualizar a frota** — rollout de versão para N instâncias com migration + canary
   (a parte mais difícil; staged, reversível).
3. **Saúde/observabilidade agregada** — health de cada instância, alertas.
4. **Billing/licenciamento** — quais módulos cada cliente tem (feature-gating).
5. **Ambientes QA/Prod** por cliente, HA onde o tier exigir.

## 3. Critério de extração (quando destacar um serviço)

Extrair um serviço quando houver **pelo menos um**:
1. **Perfil de recurso divergente** (CPU/armazenamento/latência ≠ CRUD).
2. **Fronteira natural de protocolo/engine** (motor de prateleira já é processo à parte).
3. **Superfície externa / fronteira de confiança** a manter longe do núcleo de PHI.
4. **Custódia/inviolabilidade** exigida por regulação.

**NÃO** extrair quando o único argumento for "bounded context limpo" ou "segurança no
geral" — isso se resolve com fronteira de módulo + hardening de schema/role no banco, sem
o custo (hop de rede, fronteira de dados, deploy/versão, debugging distribuído).

Toda extração fala com o core por **contrato de API**, **nunca** por banco compartilhado.

### Candidatos (ranqueados)

| Serviço | Veredito | Critério | Tier |
|---|---|---|---|
| **BFP — Backend-For-Patient** | 🟢 **1º a destacar** | fronteira de confiança (3) | todos |
| **PACS / DICOM (Orthanc)** | 🟢 por gatilho | perfil (1) + engine (2) | opcional (imagem) |
| **IA-worker (inferência/LLM-explain)** | 🟢 por gatilho | perfil (1) + air-gap | opcional |
| **Reporting / BI** | 🟢 na escala | perfil (1) — protege OLTP | opcional |
| **Gateway de canais externos** | 🟡 quando volume | superfície (3) | conforme |
| **Audit trail** | 🟡 endurecer 1º | custódia (4) — `REVOKE` dá 80% | core |
| **Auth** | 🟡 **não extrair** | já edge-verified; entranhado no tenant; hop no hot-path → endurecer no lugar | core |
| **Celery (async)** | ✅ já separado | — | core |

No modelo de frota, cada serviço extraído é um **módulo opcional que o control plane
compõe por plano**: pool pequeno = `{core, BFP}`; hospital = `{core, BFP, PACS, IA, edge}`.
Footprint certo por bolso (espelha o `ra-licensing` do LabX).

## 4. O BFP — Backend-For-Patient (primeira extração)

A 4ª borda (LabX B5): o público **paciente** (não-confiável, internet, WhatsApp) separado
do núcleo clínico (staff, PHI, interno). **Presente em todos os tiers** — é a base e o
wedge de venda, não um opcional.

### Dono de (datastore próprio)
- Identidade do **paciente** (auth de baixa confiança, separada do staff).
- Contato WhatsApp + **consentimento LGPD** (opt-in com timestamp).
- **Motor de conversa em 2 modos**: IA + fluxos scriptados permanentes.
- Conversas, mensagens, estado de fluxo, lembretes/notificações.
- **Rascunhos** de agendamento (o pedido do paciente).

### Consome do core (API estreita, auditada, token escopado — nunca DB direto)
- "marcar consulta/exame" → o **core valida e confirma** (agenda, conflito, convênio).
- "minhas consultas / meus resultados (lab + link PACS) / minhas receitas / meu perfil".

### Por que primeiro
- Maior superfície de ataque (público) → tirá-la de cima do PHI é o maior ganho de
  blast-radius. Comprometer o BFP expõe só o que aquele paciente já veria de si.
- Está em todos os tiers (valor universal + wedge WhatsApp).
- Parcialmente construído (`apps/patient_portal`, `apps/whatsapp`, `app/portal`).
- Força a definir o **contrato de API paciente-facing do core** — a disciplina que toda
  extração futura vai herdar. É a prova do padrão no pedaço mais valioso.
- Monetiza de cara: modo scriptado (incluído) vs modo IA (premium).

### Referência: AgendaSmart (Agenda_Studio) — usar o que funciona, NÃO acoplar
O Agenda_Studio já provou em produção o motor de conversa em 2 modos (IA por provedor via
`platform_settings.ai_models` + fluxos scriptados via funções SQL `*_by_client`,
rate-limit, planos). **Reusar os padrões e aprendizados** (e, no máximo, o engine como
biblioteca versionada). **Não** acoplar os dois produtos: release, banco e deploy do
Vitali permanecem independentes do Agenda_Studio.

### Comportamento por tier
- Pool: **um** BFP multi-tenant serve várias clínicas — com o mesmo rigor de isolamento do
  core (`ENFORCE_TENANT_MEMBERSHIP` vale aqui; paciente do A nunca vê o B).
- Dedicado: BFP por instância.

## 5. Princípios a adotar JÁ (baratos, destravam o resto)

Independem de quebrar em serviços; tornam a decomposição futura barata e o produto mais
defensável já no piloto:

- **P1 — Perfil air-gap.** Os 7 wedges são engines determinísticos (LLM só explica). Logo
  o core de segurança clínica já é air-gap-capable. Formalizar `DEPLOYMENT_PROFILE=airgap`
  que desliga egress; boot falha se houver chamada externa configurada.
- **P2 — Auditoria inviolável.** `REVOKE UPDATE, DELETE` na tabela de auditoria para o role
  da app (só INSERT/SELECT). Tamper-evidence ~custo zero.
- **P3 — Blast-radius na cripto.** `FIELD_ENCRYPTION_KEY` via secret de runtime / KMS
  (envelope), workers Celery com menos privilégio que o web.
- **P4 — Costuras explícitas.** Zero import cruzado entre apps de domínio (import-linter no
  CI); contratos de evento/serviço como única porta de entrada de cada domínio. É o que
  torna extrair barato.
- **P5 — OTLP desde já** (B8): OpenTelemetry como contrato único, backend plugável
  (Sentry hoje, Jaeger/Tempo depois). Pré-requisito de operar frota e debugar distribuído.
- **P6 — System-check de produção.** Boot falha se `ENFORCE_TENANT_MEMBERSHIP=False` em
  produção (defesa em profundidade).

## 6. Borda / "CDN" e monitoramento de equipamentos (futuro, por gatilho)

- **Edge / "CDN":** entra quando o mercado amadurecer e grandes nomes chegarem. Para a
  maioria, região cloud basta.
- **Monitoramento de suporte à vida:** **pós-produto, projeto em si.** Outra classe de
  risco (dispositivo médico regulado — ANVISA), real-time que não tolera perda de link →
  exige **edge agent on-site** (store-and-forward) + pipeline isolado e hardened. É o BFI
  (gateway de instrumentos, gRPC) do LabX. Não bolar agora; desenhar quando for a vez.

## 7. Sequência (alto nível, por gatilho — não por calendário)

1. **Agora:** fechar GA do core (roadmap sprints 27–33) + adotar P1–P6.
2. **1ª extração:** BFP (consome core por API; prova o padrão; em todos os tiers).
3. **Control plane v1 scriptado:** provisão idempotente + registry + health básico.
4. **Por gatilho:** PACS (cliente com imagem), IA-worker (air-gap/escala), reporting (escala).
5. **Maturidade:** edge/CDN (grandes nomes), monitoramento de equipamentos (projeto à parte).

## 8. Tabela de postura (resumo)

| Vetor | Agora (core monólito) | Decomposto |
|---|---|---|
| Isolamento de dados | schema-per-tenant + ENFORCE_TENANT_MEMBERSHIP | DB-per-service nos extraídos + isolamento por instância |
| Superfície do paciente | dentro do core | **BFP (DMZ) consome core por API** |
| Auditoria | append-only + REVOKE (P2) | serviço write-only se exigirem custódia |
| Air-gap | perfil `airgap` (P1) | IA-worker local |
| Crypto / blast-radius | secret runtime / KMS (P3) | compartimentação por serviço/instância |
| Observabilidade | OTLP (P5) | tracing distribuído entre serviços |
| Frota | — | control plane (provisão/upgrade/health/billing) |

## 9. Perguntas em aberto

1. **BFP v1:** só agendamento + resultados (útil imediato) ou já com o motor de conversa
   2-modos (diferencial, mais trabalho)?
2. **Control plane online vs offline-first:** air-gap verdadeiro corta o control plane →
   upgrade vira bundle assinado aplicado pelo TI do hospital. Aceitável, ou "air-gap" na
   real é "rede deles com túnel de gestão controlado"?
3. **Custo do dedicado:** instância dedicada barata o suficiente para hospital médio, ou só
   para grandes (e médios ficam no pool)?
4. **Engine de conversa:** biblioteca compartilhada com o Agenda_Studio ou reimplementar o
   padrão no BFP (desacoplamento total)?
