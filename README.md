# Vitali

> Plataforma Hospitalar SaaS — ERP + EMR + AI · **v1.0.0**
> Django 5 · Next.js 14 · PostgreSQL 16 (schema-per-tenant) · Celery · Redis

---

## Stack

| Camada | Tecnologia |
|--------|-----------|
| Backend | Django 5.2 + DRF 3.16 + django-tenants |
| Frontend | Next.js 14 + React 18 + Tailwind + shadcn/ui |
| Database | PostgreSQL 16 (schema-per-tenant — LGPD) |
| Cache/Queue | Redis 7 + Celery 5 |
| AI | Claude API (primary) + OpenAI (fallback) |
| WhatsApp | Evolution API → Official API |
| CI/CD | GitHub Actions |
| Infra | Docker Compose → AWS ECS |

---

## Quickstart

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

# 5. Criar primeiro tenant
make create-tenant
```

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
│   │   ├── core/          # Multi-tenancy, users, roles, audit, feature flags
│   │   ├── emr/           # Prontuário eletrônico (Sprint 2+)
│   │   ├── billing/       # Faturamento TISS/TUSS (Sprint 7+)
│   │   ├── pharmacy/      # Farmácia & estoque (Sprint 6+)
│   │   ├── ai/            # LLM Gateway, TUSS coding (Sprint 8+)
│   │   └── whatsapp/      # Patient engagement (Sprint 10+)
│   └── requirements/
├── frontend/              # Next.js 14 App Router
├── docker/
│   ├── nginx/             # Reverse proxy config
│   └── postgres/          # DB initialization (extensions)
├── .github/workflows/     # CI/CD pipeline
├── docker-compose.yml
└── Makefile
```

---

## Variáveis de Ambiente — AI

Os módulos de IA vêm **desligados por padrão**. Cada um é controlado por um *feature flag* global `FEATURE_AI_*` (e o flag equivalente por-tenant) e, para processar dados de saúde, exige um **DPA assinado** (`AIDPAStatus`) — verificado em runtime (`_check_dpa_signed`).

| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `ANTHROPIC_API_KEY` | `""` | Chave da API Anthropic (obrigatória para TUSS, Safety Net, CID-10) |
| `OPENAI_API_KEY` | `""` | Chave OpenAI — necessária para o escriba (Whisper) quando `FEATURE_AI_SCRIBE=True` |
| `FEATURE_AI_TUSS` | `False` | Habilita codificação TUSS assistida |
| `FEATURE_AI_GLOSA` | `True` | Kill-switch global da previsão de risco de glosa |
| `FEATURE_AI_SCRIBE` | `False` | Habilita o escriba clínico (transcrição → SOAP) |
| `AI_RATE_LIMIT_PER_HOUR` | `100` | Limite de chamadas LLM por tenant por hora |
| `AI_SUGGEST_TIMEOUT_S` | `5` | Timeout em segundos para chamadas ao Claude |

Os módulos `ai_prescription_safety` e `ai_cid10_suggest` são habilitados por-tenant (via `FeatureFlag` / `TenantAIConfig`) e ativados em cascata quando o DPA é assinado. Veja `docs/USER_GUIDE.md` §10.

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

## Comandos úteis

```bash
make up              # Subir serviços
make down            # Parar serviços
make migrate         # Migrations no schema público
make migrate-tenant  # Migrations em todos os tenants
make test            # Rodar testes
make lint            # Ruff lint
make shell           # Django shell
make create-tenant   # Criar nova clínica
```

---

## Roadmap

Versão atual: **v1.0.0** (primeiro release production-grade). Estado conforme `CHANGELOG.md`.

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
  contato, endereço, diagnósticos via Fernet) + audit de acesso a prontuário
- **TISS/TUSS:** ANS RN 501/2022 — geração XML + codificação automática via AI
- **CFM:** Res. 1.821/2007 — audit log imutável (escrita + leitura) + assinatura digital
- **ANVISA:** Rastreabilidade de medicamentos controlados

---

## Documentação

Visão e arquitetura: [`docs/PROJECT_BRIEF.md`](docs/PROJECT_BRIEF.md) ·
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) ·
[`docs/DATA_MODEL.md`](docs/DATA_MODEL.md) ·
[`docs/API_SPEC.md`](docs/API_SPEC.md)

Operação e deploy: [`docs/DEPLOY.md`](docs/DEPLOY.md) ·
[`docs/RUNBOOK.md`](docs/RUNBOOK.md) ·
[`docs/TENANT_MIGRATIONS.md`](docs/TENANT_MIGRATIONS.md)

Segurança e compliance: [`docs/SECURITY.md`](docs/SECURITY.md) ·
[`docs/SECRETS.md`](docs/SECRETS.md) ·
[`docs/TLS.md`](docs/TLS.md) ·
[`docs/BACKUPS.md`](docs/BACKUPS.md) ·
[`docs/LGPD_PATIENT_PII_ENCRYPTION.md`](docs/LGPD_PATIENT_PII_ENCRYPTION.md)

---

*Vitali — Tornando sistemas hospitalares enterprise acessíveis para todos.*
