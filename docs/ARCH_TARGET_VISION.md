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

## 9. Substrato de orquestração (decidido 2026-06-13)

**Tudo roda na cloud do Romulo** (sem on-prem no cliente, sem air-gap real). Dedicado =
instância própria **na infra dele** (modelo Salesforce), no máximo CDN local. Princípio:
**o melhor, não o mais fácil** — time enxuto alavancado por IA + automação declarativa.

**Pilha-alvo (portável entre clouds — AWS/Oracle/MS no futuro):**
- **Kubernetes** (gerenciado; um cluster para começar). Não amarrar a PaaS de uma cloud —
  workloads k8s-native para escolher "o que roda onde" depois.
- **IaC** (Terraform/OpenTofu) para os recursos de cloud.
- **GitOps** (Argo CD ou Flux): cluster = espelho do Git. A IA propõe manifesto/PR, o
  Romulo revisa e mergeia, o cluster converge sozinho — fluxo perfeito para "dirigir IA
  como funcionários" com humano no portão.
- **Tenant como CRD + Operator próprio:** criar um objeto `Tenant{cliente, tier, módulos}`
  faz o operator **reconciliar a instância inteira** (namespace, DB, app, secrets, DNS,
  certs) de forma **idempotente e reentrante**. É a correção do anti-padrão A1 do LabX
  virada padrão de primeira classe (estado desejado no Git, convergência a cada boot,
  auto-cura). É o coração do control plane e o maior alavancador da frota.
- **Postgres como operator** (CloudNativePG): HA, backup e failover declarativos.
- **OTLP/OpenTelemetry** desde já (P5).

> Não montar k8s para a clínica #1. Caminho incremental: #1 = instância provisionada à mão;
> 2–5 = provisão scriptada (control plane v0 = registry + script idempotente); muitos = o
> operator/CRD vira produto. Substrato declarativo é o ALVO; o path é guiado por demanda.

## 10. HA por tier (calibrado)

- **Pool:** sem HA dedicada — multi-AZ + backups do Sprint 27 bastam.
- **Dedicado:** **active-passive** com réplica de Postgres (via operator) + **load balancer
  com health check** (ou DNS failover) apontando para o standby. Começar **multi-AZ numa
  cloud** (failover automático seguro); **cross-region active-passive** é tier premium.
- ⚠️ Evitar espelho síncrono cross-cloud no v1 — risco de split-brain. HA é declarativa via
  o Postgres operator, não scripts manuais (anti A4).

## 11. Unit economics (modelo)

- **Pool amortiza:** N clínicas dividem app+DB; custo marginal de +1 ≈ centavos → preço
  baixo, margem alta, máquina de volume.
- **Dedicado tem piso:** cada cliente carrega o custo cheio (app + Postgres ×2 com HA +
  redis + observabilidade) → piso mensal real (centenas de R$/mês conforme cloud).
- **Regra de preço:** dedicado ≥ (custo de infra × fator HA) + uso (LLM, storage PACS) +
  margem; tipicamente **3–5× o custo de infra**.
- **Alavancas:** right-sizing agressivo, scale-to-zero/hibernação de dedicados ociosos,
  custos de uso (IA/imagem) repassados ou por faixa. Pool = escala; dedicado = margem
  premium **se precificado certo**. (Planilha de custo por instância quando a cloud for
  escolhida.)

## 12. Canal e financiamento (TCX)

Sem pressa de prazo: o Vitali é projeto de longo prazo ("xodó"), **financiado pela receita
do TCX**. Consequências: (a) construir **certo, não rápido** — investir nas fundações
(operator, costuras, observabilidade), não em gambiarra; (b) cuidado com a armadilha do
"sem prazo" (gold-plating eterno) → **sequenciar por fundação arquitetural, não por
capricho de feature**; (c) **o TCX é o canal** — já atende clínicas, então as primeiras
clínicas-piloto do Vitali saem da base do TCX (sem cold-start). A clínica #1 virá pelo TCX,
no tempo certo.

## 13. Perguntas remanescentes (não-bloqueantes)

- **BFP v1:** começa só com agendamento + resultados + perfil em **modo scriptado**; IA é
  fast-follow pago (recomendação registrada — confirmar na hora de planejar o BFP).
- **Cloud específica e números de preço:** decidir quando for provisionar de verdade.
- **Engine de conversa:** reimplementar o padrão no BFP (desacoplado); virar lib só se
  surgir 3º consumidor.

> Perguntas 2 (online/offline) e custo-base do dedicado já resolvidas: control plane
> **online** (tudo na cloud do Romulo); dedicado por **tamanho/risco**, médios ficam no
> pool até justificar.
