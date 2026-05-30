# Vitali

> Plataforma Hospitalar SaaS — ERP + EMR + AI
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

Para habilitar o módulo de AI TUSS, configure as seguintes variáveis no `.env`:

| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `ANTHROPIC_API_KEY` | `""` | Chave da API Anthropic (obrigatória para AI TUSS) |
| `FEATURE_AI_TUSS` | `False` | Feature flag — habilita o endpoint de sugestão TUSS |
| `AI_RATE_LIMIT_PER_HOUR` | `100` | Limite de chamadas LLM por tenant por hora |
| `AI_SUGGEST_TIMEOUT_S` | `5` | Timeout em segundos para chamadas ao Claude |

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

| Sprint | Semanas | Épico |
|--------|---------|-------|
| Sprint 0 | 1-2 | Foundation & Infrastructure ✅ |
| Sprint 1 | 3-4 | Auth + Core completo |
| Sprint 2 | 5-6 | Cadastro de Pacientes |
| Sprint 3 | 7-8 | Agendamento |
| Sprint 4-5 | 9-13 | EMR (Prontuário) |
| Sprint 6 | 14-16 | Farmácia |
| Sprint 7-8 | 17-21 | Faturamento TISS/TUSS |
| Sprint 8 | 20-21 | AI TUSS Auto-Coding ✅ |
| Sprint 9 | 22-23 | AI Features (expansão) |
| Sprint 10 | 24-26 | Billing Intelligence Dashboard ✅ v0.5.0 |
| Sprint 11 | 27-28 | Commercialization — module gating, subscriptions, POs ✅ v0.6.0 |
| Sprint 12 | 29-31 | WhatsApp Patient Engagement ✅ v0.7.0 |

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
