# Vitali

> Plataforma Hospitalar SaaS — ERP + EMR + AI · **v1.0.0** + trabalho não versionado em `onda0`
> Django 5.2 · Next.js 15 · PostgreSQL 16 (schema-per-tenant) · Celery · Redis

A direção do projeto está em [`.maestro/INTENT.md`](.maestro/INTENT.md) (INTENT v6, 25/09). O trabalho
anda por **ordens** numeradas em [`.maestro/orders/`](.maestro/orders/), cada uma com prova
gravada. A integração é o branch `onda0-perimetro-multitenant`. `master` está atrás por
decisão, e a sincronia `onda0 → master` é ordem própria.

---

## Estado atual (25/09/2026)

As ordens 005 a 021 estão aceitas. O que elas deixaram de pé:

| Frente | Estado | Ordens |
|--------|--------|--------|
| **CI** | Testa antes do merge: backend (lint, mypy, pytest), frontend (lint, tipos e **vitest com portão**), E2E e validação de build Docker. Roda em PR contra `onda0` e em push para `order/**` | 005, 012 |
| **Cadeia de receita** | Guia TISS válida → guia **declarada pronta** → lote → **fechamento**, pelo caminho real (`services/batch_lifecycle`). Ciclo da guia `draft → pending → submitted`. Lote com rascunho não fecha (409 `batch_has_draft_guides`), e `submit` recusa rascunho (400 `guide_not_ready`) | 006, 008, 009, 010 |
| **Cunha de glosa** | Intercepta dado real de staging, e o override fica auditado. A flag `glosa_safety` continua **OFF** por padrão | 007 |
| **Recuperação** | Drill de restore **toda noite**. Recuperação parada fica vermelha, e a fase 2 do drill compara contra o inventário do dump. Offsite **adiado até a produção**, por decisão do Capitão | 003, 004, 011, 012 |
| **Catálogos** | LOINC 2.83 com 112.405 códigos em staging. CBHPM 2022 com 4.881 procedimentos: o `porte` é classe publicada, e `valor() = 0` até existir contrato ("importar o livro não produz preço; preço é contrato") | 013 |
| **Assinatura ICP-Brasil** | O truststore vive em volume e sobrevive ao deploy. Com o truststore vazio, a assinatura é **recusada** (400), e não gravada como não-ICP em silêncio | 014, 015 |
| **Trilha de leitura** | Toda rota `GET` que lê dado de paciente ou dado pessoal sensível deixa trilha, ou está isenta com motivo escrito. A cobertura se mede pelo roteador do Django (`apps/core/audit_coverage.py`): 321 rotas `GET`, **0 sem cobertura** | 016–019 |
| **Retenção da trilha** | `core_auditlog` particionada por mês e por tenant. Retenção de **20 anos** (240 meses), por decisão do Capitão ([ADR-0001](docs/adr/ADR-0001-retencao-auditoria-20-anos.md)). Expurgo **desligado de fábrica**, e nada se apaga sem recibo de exportação fria | 020, 021 |

**Em aberto:**

* **Criar clínica tinha portas demais — ordem 022 fecha em um só caminho.**
  `apps/core/services/provisioning.py` (`provision_tenant`) é agora a ÚNICA
  fonte: signup self-serve, `POST /api/v1/platform/tenants` e
  `manage.py provision_tenant` chamam a mesma função. `scripts/provision_tenant.sh`
  (que interpolava o nome da clínica dentro de um `manage.py shell -c`) foi
  removido; `make create-tenant` chama o comando novo. Pendente de aceite do
  diretor.
* **`POST /api/v1/platform/tenants` exige operador de plataforma** (`IsPlatformAdmin`), com
  throttle dedicado de 5/h por operador (ordem 023). Até então aceitava anônimo.
* Sorologia de doador de sangue fora do grafo de `Patient`, e por isso invisível à guarda
  da trilha.
* O destino frio S3 Glacier da trilha foi decidido, mas não está construído.
* Revogação ICP fail-closed desligada em staging. Precisa ser ligada para a produção.
* O sinal de backup prova que o backup é recente, não que terminou: o exit code do backup
  não chega a lugar nenhum.

---

## Stack

| Camada | Tecnologia |
|--------|-----------|
| Backend | Django 5.2 + DRF 3.16 + django-tenants |
| Frontend | Next.js 15 + React 18 + Tailwind + shadcn/ui |
| Database | PostgreSQL 16 (schema-per-tenant — LGPD) |
| Cache/Queue | Redis 7 + Celery 5 |
| AI | Claude API (primary) + OpenAI (fallback) |
| WhatsApp | Evolution API → Official API |
| CI/CD | GitHub Actions |
| Infra | Docker Compose na lab (Vulcan), exposto por Cloudflare Tunnel · AWS ECS é destino declarado, fora deste horizonte |

---

## Quickstart

> **Na forge, não.** O quickstart abaixo sobe a stack inteira e serve para a **sua**
> máquina de desenvolvimento. A forge, máquina compartilhada da frota, **não roda compose do
> Vitali**: regra do Imediato desde 17/09/2026, depois de a stack de dev ficar exposta na
> LAN por 1h46. Na forge, teste roda no CI ou na lab (ver
> [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md)).

```bash
# 1. Copiar variáveis de ambiente
cp .env.example .env
# editar .env com suas credenciais

# 2. Subir todos os serviços
make up

# 3. Rodar migrations
make migrate

# 4. Criar superuser
make superuser

# 5. Criar primeiro tenant (ambiente novo inteiro: public + clínica + papéis + admin)
BOOTSTRAP_ADMIN_PASSWORD=... docker compose exec -e BOOTSTRAP_ADMIN_PASSWORD django \
  python manage.py bootstrap_beta --public-domain localhost \
  --clinic-slug demo --clinic-domain demo.localhost --admin-email admin@example.com

# 6. Pré-criar as partições da trilha de auditoria (mês corrente e seguinte; idempotente)
docker compose exec django python manage.py ensure_audit_partitions
```

`make create-tenant` ainda existe, mas cria só `Tenant` + `Domain`, sem admin nem papéis.
Ele será substituído pelo comando `provision_tenant` na ordem 022.

Acesse:
- **Frontend:** http://localhost:3000
- **API:** http://localhost:8000/api/v1/
- **API Docs:** http://localhost:8000/api/docs/
- **Admin:** http://localhost:8000/admin/

---

## Estrutura do Projeto

```
vitali/
├── backend/
│   ├── vitali/            # Django project (settings, urls, wsgi)
│   ├── apps/
│   │   ├── core/          # Multi-tenancy, users, roles, audit (trilha + partição), feature flags, catálogos
│   │   ├── emr/           # Prontuário eletrônico, laboratório, internação
│   │   ├── billing/       # Faturamento TISS/TUSS, lotes, glosa
│   │   ├── pharmacy/      # Farmácia & estoque, dose-safety
│   │   ├── pharmacy_ai/   # Previsão de demanda e ruptura
│   │   ├── ai/            # LLM Gateway, TUSS coding, escriba
│   │   ├── signatures/    # Assinatura digital ICP-Brasil
│   │   ├── hr/            # Recursos humanos
│   │   ├── triage/        # Triagem (Manchester)
│   │   ├── imaging/       # DICOM (rastreio de estudos)
│   │   ├── fhir/          # Interoperabilidade FHIR R4
│   │   ├── whatsapp/      # Engajamento do paciente
│   │   └── ...            # analytics, concession, governance, mobile, organization,
│   │                      # patient_portal, smart_scheduling, telemedicine
│   └── requirements/
├── frontend/              # Next.js 14 App Router
├── docker/
│   ├── nginx/             # Reverse proxy config
│   └── postgres/          # DB initialization (extensions)
├── .github/workflows/     # CI/CD pipeline
├── .maestro/              # Direção (INTENT) e ordens de trabalho
├── scripts/               # Backup, drill de restore, ETL de catálogos, deploy
├── docker-compose.yml
└── Makefile
```

---

## Variáveis de Ambiente — AI

Os módulos de IA vêm **desligados por padrão**. Cada um é controlado por um *feature flag* global `FEATURE_AI_*` (e o flag equivalente por-tenant) e, para processar dados de saúde, exige um **DPA assinado** (`AIDPAStatus`) — verificado em runtime por um gate único, `apps.ai.consent.requires_ai_consent`, que também confere se o provedor consta do DPA.

| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `ANTHROPIC_API_KEY` | `""` | Chave da API Anthropic (obrigatória para TUSS, Safety Net, CID-10) |
| `OPENAI_API_KEY` | `""` | Chave OpenAI do Whisper. **Sem efeito hoje:** o gate recusa a OpenAI (`provider_not_in_dpa`) até o DPA nomeá-la como suboperador (ordem 024) |
| `FEATURE_AI_TUSS` | `False` | Habilita codificação TUSS assistida |
| `FEATURE_AI_GLOSA` | `False` | Kill-switch global da previsão de risco de glosa |
| `FEATURE_AI_SCRIBE` | `False` | Habilita o escriba clínico (transcrição → SOAP) |
| `FEATURE_AI_CID10` | `False` | Sugestão de CID-10 por LLM, com scrub de PHI e `AIUsageLog` (ordem 025) |
| `FEATURE_AI_PRESCRIPTION_SAFETY` | `False` | Checagem de segurança de prescrição por LLM (ordem 025). Ligar só depois da ordem 026, que impede o alerta do LLM de sobrescrever o do motor |
| `FEATURE_WHISPER_FALLBACK` | `False` | Transcrição de áudio no servidor (Whisper/OpenAI) para navegador sem Web Speech API. Era `True` até a ordem 024; ligar não libera nada enquanto o DPA não nomear a OpenAI |
| `AI_RATE_LIMIT_PER_HOUR` | `100` | Limite de chamadas LLM por tenant por hora |
| `AI_SUGGEST_TIMEOUT_S` | `5` | Timeout em segundos para chamadas ao Claude |

Os módulos `ai_prescription_safety` e `ai_cid10` são habilitados por tenant pelo `FeatureFlag`, ligado em cascata quando o DPA é assinado. Assinar o DPA **não basta**: a chave global correspondente também precisa estar ligada. Veja `docs/USER_GUIDE.md` §10.

---

## Multi-tenancy

Cada clínica/hospital é um **tenant** com seu próprio schema PostgreSQL — garantindo isolamento total dos dados (LGPD).

```
public schema:     tenants, plans, subscriptions, feature_flags
tenant_clinica_a:  users, patients, encounters, prescriptions, ...
tenant_hospital_b: users, patients, encounters, prescriptions, ...
```

### Feature Flags

Módulos são habilitados por tenant via `FeatureFlag`:

```python
from apps.core.middleware import tenant_has_feature

if tenant_has_feature(request.tenant, 'module_pharmacy'):
    # Farmácia disponível para este tenant
    ...
```

---

## Camada de interceptação AI-native

O Vitali deixa de ser um sistema de *registro* e passa a **interceptar o erro antes
que ele alcance o paciente / o caixa / a prateleira**. Três *wedges* foram entregues
neste ciclo, todos seguindo o **mesmo padrão** — `Observe → Preveja → Intercepte →
Aprenda`:

> **motor determinístico puro** (autoritativo; o LLM só explica) + **orquestrador** +
> **alerta persistente** + **feature flag per-tenant (default OFF)** + **flywheel**
> (`AuditLog` de alerta/override/desfecho).

| Wedge | Flag (default **OFF**) | O que intercepta |
|-------|------------------------|------------------|
| **Dose-safety** | `dose_safety` | dose fora da faixa segura para o paciente, na prescrição e na dispensação (soft-stop) |
| **Glosa-interception** | `glosa_safety` | risco de glosa por guia, antes de fechar o lote TISS (soft-stop por-guia) |
| **Stockout-prediction** | `stockout_safety` | ruptura de estoque e validade encalhada, em painel proativo (advise — nunca bloqueia dispensa) |

**Construído ≠ no ar.** As três flags vêm **desligadas** e nenhuma processa nada até
que **dados validados por humano** sejam fornecidos — formulário de dose validado por
farmacêutico (pendente, decisão D-T1), atributos `TUSSCode`/contrato via import ANS, e
config de suprimentos por estabelecimento. **Nenhum número clínico/contratual/ANS é
inventado em código.** Índice consolidado e checklist "para ir ao ar":
[`docs/AI-NATIVE-WEDGES.md`](docs/AI-NATIVE-WEDGES.md).

---

## Comandos úteis

```bash
make up              # Subir serviços
make down            # Parar serviços
make migrate         # Migrations no schema público
make migrate-tenant  # Migrations em todos os tenants
make test            # Rodar testes (na sua máquina; na forge, CI ou lab)
make lint            # Ruff lint
make shell           # Django shell
make create-tenant   # Legado: só Tenant + Domain (ordem 022 substitui)
```

---

## Roadmap

Versão atual: **v1.0.0** (primeiro release production-grade). Depois do ciclo de sprints, o
trabalho passou a andar por ordens (ver §Estado atual). Estado conforme `CHANGELOG.md`.

### Entregue (shipped)

| Sprint | Épico | Versão |
|--------|-------|--------|
| Sprint 0 | Foundation & Infrastructure | — |
| Sprint 1 | Auth + Core | — |
| Sprint 2 | Cadastro de Pacientes | — |
| Sprint 3 | Agendamento | — |
| Sprint 4-5 | EMR (Prontuário) | — |
| Sprint 6 | Farmácia | — |
| Sprint 7-8 | Faturamento TISS/TUSS | — |
| Sprint 8 | AI TUSS Auto-Coding | — |
| Sprint 9 | AI Features (expansão) | — |
| Sprint 10 | Billing Intelligence Dashboard | v0.5.0 |
| Sprint 11 | Commercialization — module gating, subscriptions, POs | v0.6.0 |
| Sprint 12 | WhatsApp Patient Engagement | v0.7.0 |
| Sprint 13 | Pre-Production Hardening (settings, Redis, logging, Sentry, rate limit, CI/CD) | v0.8.0 |
| Sprint 14 | First Pilot Readiness (onboarding wizard, PIX/Asaas, e-mail, seed, índices, mobile) | v0.9.0 |
| Sprint 15 | Clinical AI Layer + MFA (TOTP) — Safety Net, sugestão CID-10, escriba SOAP, PDF de receita, fila de espera | v1.0.0 |
| Pós-1.0.0 | Endurecimento de segurança e infra (PII criptografada em repouso, audit de leitura, TLS, backups automáticos) | Unreleased |

As funcionalidades de IA da camada clínica (Sprint 15) vêm **desligadas por padrão**: dependem de *feature flags* `FEATURE_AI_*`/por-tenant e exigem um **DPA assinado** (LGPD Art. 11) antes de processar dados de saúde — veja `docs/USER_GUIDE.md` §10.

### Planejado (planned)

| Sprint | Épico | Alvo |
|--------|-------|------|
| Sprint 16 | Clinical UI Layer + Phase 2 AI | v1.1.0 |
| Sprint 17 | Pre-GA Compliance + Scribe Hardening | v1.2.0 |
| Sprints 23/25/26 | Quality gates — HR E2E + role contracts, Clinical Journey, Production Readiness | — |

Datas/escopo detalhados em `docs/EPICS_AND_ROADMAP.md` e nos planos `docs/PLAN_SPRINT*.md`.

---

## Compliance

- **LGPD:** Schema-per-tenant + criptografia de PII sensível em repouso (CPF, nome,
  contato, endereço, diagnósticos via Fernet) + trilha de leitura **por rota** sobre dado
  de paciente e dado pessoal sensível (art. 5º II, art. 37), com guarda que reprova rota
  nova sem cobertura (ordens 016–019)
- **TISS/TUSS:** ANS RN 501/2022 — geração XML + codificação automática via AI; cadeia
  guia → lote → fechamento provada pelo caminho real (ordens 006–010)
- **CFM:** Res. 1.821/2007 — audit log imutável (escrita + leitura), guardado por
  **20 anos** (art. 8; Lei 13.787/2018, art. 6), em tabela particionada por mês e por
  tenant, com expurgo desligado de fábrica e exportação fria obrigatória antes de qualquer
  `DROP` ([ADR-0001](docs/adr/ADR-0001-retencao-auditoria-20-anos.md)) + assinatura
  digital ICP-Brasil que recusa assinar com truststore vazio
- **ANVISA:** Rastreabilidade de medicamentos controlados

---

## Documentação

Visão e arquitetura: [`docs/VISION-AI-NATIVE.md`](docs/VISION-AI-NATIVE.md) (tese AI-native — cunha de segurança de dose) ·
[`docs/AI-NATIVE-WEDGES.md`](docs/AI-NATIVE-WEDGES.md) (camada de interceptação — 3 wedges, flag-gated OFF) ·
[`docs/PROJECT_BRIEF.md`](docs/PROJECT_BRIEF.md) ·
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) ·
[`docs/DATA_MODEL.md`](docs/DATA_MODEL.md) ·
[`docs/API_SPEC.md`](docs/API_SPEC.md)

Direção e decisões: [`.maestro/INTENT.md`](.maestro/INTENT.md) ·
[`.maestro/orders/`](.maestro/orders/) ·
[`docs/adr/`](docs/adr/) ·
[`docs/research/VITALI_CATALOGOS_ESTADO_REAL.md`](docs/research/VITALI_CATALOGOS_ESTADO_REAL.md)

Desenvolvimento: [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) (onde rodar testes, regra da forge)

Operação e deploy: [`docs/DEPLOY.md`](docs/DEPLOY.md) ·
[`docs/RUNBOOK.md`](docs/RUNBOOK.md) ·
[`docs/TENANT_MIGRATIONS.md`](docs/TENANT_MIGRATIONS.md)

Segurança e compliance: [`docs/SECURITY.md`](docs/SECURITY.md) ·
[`docs/SECRETS.md`](docs/SECRETS.md) ·
[`docs/TLS.md`](docs/TLS.md) ·
[`docs/ICP_BRASIL.md`](docs/ICP_BRASIL.md) ·
[`docs/COMPLIANCE_CHECKLIST.md`](docs/COMPLIANCE_CHECKLIST.md) ·
[`docs/BACKUPS.md`](docs/BACKUPS.md) ·
[`docs/LGPD_PATIENT_PII_ENCRYPTION.md`](docs/LGPD_PATIENT_PII_ENCRYPTION.md)

---

*Vitali — Tornando sistemas hospitalares enterprise acessíveis para todos.*
