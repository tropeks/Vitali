# Vitali — Security & Compliance Document

> **Refs:** [ARCHITECTURE.md](./ARCHITECTURE.md) | [DATA_MODEL.md](./DATA_MODEL.md)

---

## 1. Data Classification

| Level | Data Type | Examples | Protection |
|-------|-----------|----------|------------|
| **Critical** | Dados sensíveis (LGPD Art.5 II) | Prontuários, diagnósticos, prescrições, alergias | Encrypted at rest + in transit, audit all access |
| **High** | PII | CPF, nome, endereço, telefone, email | Encrypted at rest, access logged |
| **Medium** | Operational | Agendamentos, faturamento, estoque | Standard protection, audit writes |
| **Low** | System | Logs, métricas, config | Standard protection |

---

## 2. Threat Model

### 2.1 Authentication Bypass

| Asset | Threat | Mitigation |
|-------|--------|------------|
| User sessions | Credential stuffing | Rate limit login (5/min/IP), bcrypt cost 12+, account lockout (exponential backoff) |
| JWT tokens | Token theft | Short-lived access tokens (15min), refresh rotation, httpOnly cookies |
| Admin access | Privilege escalation | Separate admin routes, MFA required for admin roles |
| API keys | Key leakage | Secrets in vault (not env vars in prod), rotation policy |

### 2.2 Data Leakage (Cross-Tenant)

| Asset | Threat | Mitigation |
|-------|--------|------------|
| Patient records | Tenant data leak via query bugs | Schema-per-tenant isolation (django-tenants), PostgreSQL search_path enforcement |
| API responses | Tenant ID mismatch | Middleware validates tenant context on every request, never trust client-supplied tenant_id |
| Backups | Backup contains all tenants | Per-tenant backup capability, encrypted backups with separate keys |
| Logs | PII in log files | Structured logging with PII redaction middleware, no CPF/names in logs |

### 2.3 Injection & Input Attacks

| Asset | Threat | Mitigation |
|-------|--------|------------|
| Database | SQL injection | Django ORM (parameterized queries always), never raw SQL without params |
| API | Mass assignment | DRF serializers with explicit `fields` (allowlist, never `__all__` for writes) |
| Frontend | XSS | React auto-escapes, CSP headers, no `dangerouslySetInnerHTML` |
| File uploads | Malicious files | Magic byte validation, size limits (10MB), separate storage domain, antivirus scan |
| TISS XML | XML injection | Schema validation against official XSD before processing |

### 2.4 WhatsApp / AI Specific

| Asset | Threat | Mitigation |
|-------|--------|------------|
| Patient conversations | Unauthorized access to chat history | Conversations linked to patient record, same access control applies |
| AI prompts | Prompt injection via patient data | Sanitize all user input before including in LLM prompts, structured output format |
| AI responses | Hallucinated TUSS codes | AI suggestions always require human confirmation, validate codes against TUSS DB |
| WhatsApp opt-in | LGPD violation (sending without consent) | Explicit opt-in stored with timestamp, opt-out at any time |

---

## 3. Security Controls

### 3.1 Authentication
- [x] Django + DRF with djangorestframework-simplejwt
- [x] Passwords: Argon2id (Django's recommended default)
- [x] JWT: Access token 15min, Refresh token 7 days, rotation enabled
- [x] Refresh token stored in httpOnly, Secure, SameSite=Lax cookie
- [x] Account lockout: 5 failed attempts → 5min lock, 10 → 30min, 15 → 1h
- [ ] MFA: TOTP via django-otp (Phase 2, required for admin/medical roles)
- [x] Password policy: min 12 chars, mixed case, number, special char

### 3.2 Authorization (RBAC)
Default roles and permissions:

| Role | EMR Read | EMR Write | Prescribe | Billing | Pharmacy | Admin |
|------|----------|-----------|-----------|---------|----------|-------|
| admin | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ |
| medico | ✅ | ✅ | ✅ | Read | ❌ | ❌ |
| enfermeiro | ✅ | Partial | ❌ | ❌ | Dispense | ❌ |
| recepcionista | Limited | ❌ | ❌ | ❌ | ❌ | ❌ |
| farmaceutico | Read | ❌ | ❌ | ❌ | ✅ | ❌ |
| faturista | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ |

- Custom roles supported (tenant admin can create)
- Permission check at API layer via DRF permissions classes
- Object-level permissions for sensitive records

### 3.3 Encryption
- **In transit:** TLS 1.3 (Nginx), HSTS header
- **At rest:** PostgreSQL with disk-level encryption (LUKS on VPS, RDS encryption on AWS)
- **Application-level:** CPF, RG encrypted with Fernet (symmetric, via `django-encrypted-model-fields`)
- **Key management:** VPS phase: Docker secrets. AWS phase: AWS KMS
- **Backups:** AES-256 encrypted before upload to external storage

### 3.4 Input Validation
- All API input validated by DRF serializers + Pydantic for complex objects
- File uploads: magic byte check, 10MB limit, stored in MinIO/S3 (not filesystem)
- TISS XML: validated against official ANS XSD schemas
- Content-Type enforced on all endpoints
- Request body size: 5MB default, 50MB for file upload endpoints

### 3.5 Rate Limiting
- django-ratelimit on all endpoints
- Login: 5 req/min/IP
- API (authenticated): 100 req/min/user
- WhatsApp webhook: 200 req/min (burst from Evolution API)
- AI features: 30 req/min/tenant (cost control)
- Public endpoints: 20 req/min/IP

### 3.6 Audit Logging
- All authentication events (login, logout, failed, password change)
- All CRUD operations on clinical data (who, what, when, before/after)
- All prescription actions (create, sign, cancel, dispense)
- All billing actions (guide created, submitted, payment recorded)
- All AI usage (feature, tokens, cost, result acceptance)
- Logs are append-only, enforced in the database: `BEFORE UPDATE/DELETE/TRUNCATE`
  triggers plus `REVOKE` on `core_auditlog` (migration `0019`, re-applied to the
  partitioned table by `0043` and to every new partition by `apps.core.partitioning`)
- Retention: **240 months (20 years) per tenant** for the whole `core_auditlog` trail,
  purge **off** by default — see §3.6.2 and
  [ADR-0001](./adr/ADR-0001-retencao-auditoria-20-anos.md). There is no separate
  shorter retention for "operational" rows.
- Format: structured JSON, shipped to centralized logging

#### 3.6.1 Read trail (orders 016–019)

Reading a patient record must leave a trace (Res. CFM 1.821/2007; LGPD art. 37).
`apps/core/mixins.py::AuditReadMixin` writes it:

- `retrieve` → `view_record`.
- `list` → `view_record_list` when one of `AUDIT_LIST_PARAMS` is in the querystring
  (default `("patient", "search")`), or **always** when the viewset sets
  `AUDIT_LIST_ALWAYS = True` (order 019, opt-in, default `False`).
- `@action` detail routes listed in `AUDIT_READ_ACTIONS` → `view_record` (order 019:
  e.g. `PatientViewSet.medical_history`, `.allergies`, `.timeline`, `.insurance`,
  `EncounterViewSet.procedures`, `SurgicalCaseViewSet.timeline`,
  `TISSBatchViewSet.download`).
- The mixin **must be the first base class**; otherwise DRF's `retrieve`/`list`
  win in the MRO and the trail silently disappears (orders 016/017).

**Which views need the trail is decided by code, not by review memory.**
`apps/core/audit_coverage.py` + `apps/core/audit_coverage_routes.py`, checked by
`apps/core/tests/test_auditoria_leitura_cobertura.py`:

- **Enumeration comes from the Django router, never from `grep`.** Regex counts
  gave 71, 75 and 41 depending on the match window (order 016).
- **Band 1 — patient data:** the view's model reaches `emr.Patient` through
  ForeignKey, OneToOne or ManyToMany (`TISSBatch` only reaches it via M2M), never
  crossing `ARESTAS_PROIBIDAS` (`core.User`, `core.Tenant`, `core.Role` — without
  this, 46 of 47 candidates were false positives via `created_by → core.User`,
  order 016). Depth limit `SALTOS_MAXIMOS = 6`; the result saturates at 4.
- **Band 2 — sensitive personal data outside the chart (order 017):** the model is
  in `MODELS_SENSIVEIS` — `hr.LeaveRequest`, `hr.OccupationalHealthExam`,
  `hr.Dependent` (LGPD art. 5º II / third-party data) and `hr.TimeEntry`
  (art. 37, Imediato's decision of 17/09). An explicit list, never a field-name
  heuristic (the keyword attempt flagged `CostCenter.name` and `Room.name`).
- **Every exemption carries a written reason**, tested at more than 40 characters:
  `ISENTAS` (whole class), `ACTIONS_ISENTAS` / `LIST_ALWAYS_ISENTAS` (single route),
  `MODELS_SEM_DADO_SENSIVEL` (HR work-organisation models), `VIEWS_SEM_MODEL`.
- **Guards against passing by vacuity:** enumeration floors (more than 100 views and
  more than 210 GET routes); every view resolves a model or is declared in
  `VIEWS_SEM_MODEL`; `AuditReadMixin` precedes `RetrieveModelMixin`/`ListModelMixin`
  in the MRO; and, since order 019, coverage is checked **per GET route**, not per
  class — a class that inherits the mixin is not proof that each route writes.
- **State at the close of order 019:** 154 registered views · 74 require the trail ·
  321 GET routes · 0 uncovered.
- **Order 018:** `?employee=` really filters `LeaveRequestViewSet`,
  `OccupationalHealthExamViewSet` and `DependentViewSet` (same pattern as
  `TimeEntryViewSet`), so `AUDIT_LIST_PARAMS = ("employee",)` records a criterion
  that matches the response. Order 019 then set `AUDIT_LIST_ALWAYS = True` on the
  four HR viewsets, so an unfiltered list is recorded too.

**Deliberately without a read trail (band 3):** catalogue and operational data —
`DrugInteraction`, `AllergenClass`, `ImagingModality`, `CostCenter`, pharmacy stock,
billing not linked to a guide — plus the self-refreshing collective panels
(`census`, `planned`, `today`, both `board`s, `dre`) and the option catalogues
(order 019). One row per repaint says the screen was open, not who looked up whom;
the reasons live in `audit_coverage*.py`.

**Known gap:** blood-donor serology (`emr.BloodDonor`, `emr.BloodBagSerology`) has
no path to `emr.Patient` and is not in `MODELS_SENSIVEIS`, so the guard does **not**
require a trail there. Both viewsets currently inherit `AuditReadMixin`, but nothing
fails if that is removed, and their `list` is not `AUDIT_LIST_ALWAYS`. Needs its own
order.

#### 3.6.2 Storage, retention and purge (orders 020–021, ADR-0001)

- `core_auditlog` lives in the `public` schema (`apps.core` is in `SHARED_APPS`): one
  table for every tenant. Since migration `0043` it is partitioned **RANGE monthly
  on `created_at`**, sub-partitioned **LIST on `schema_name`**, with a **DEFAULT
  partition at both levels** so no audit row is ever refused. The primary key is
  composite: `(id, created_at, schema_name)`.
- The pre-conversion table was renamed to **`core_auditlog_pre020`** and is kept
  as-is. It is **not dropped without the Imediato's explicit acceptance** (orders
  020/021).
- **Retention:** 20 years = **240 months**, the Capitão's decision of 22/09/2026
  (Res. CFM 1.821/2007 art. 8; Lei 13.787/2018 art. 6). Configured **per tenant** in
  `apps.core.models.TenantAuditRetention` (`retention_months`, default `240`;
  `purge_enabled`, default `False`). A tenant with no row gets these defaults and
  is never purged by omission. The global `AUDIT_LOG_RETENTION_DAYS` /
  `AUDIT_LOG_PURGE_ENABLED` settings from order 020 were retired by order 021.
- **Purge** (`manage.py purge_audit_logs`) is `--dry-run` by default (`--execute`
  to act), drops only a tenant's **dedicated** leaf partition older than its
  window, never a DEFAULT partition and never via `DELETE`.
- **No DROP without a verified cold copy:** `partitioning.drop_partition(name, *,
  cold_export_receipt)` refuses unless it receives a verified
  `ColdExportReceipt` for that exact partition. The export
  (`apps.core.cold_storage`) is JSONL — a stable format, never `pg_dump` binary —
  with a sha256 of the plaintext, gpg-encrypted with the same key as
  `scripts/backup.sh` (`BACKUP_ENCRYPTION_KEY`), a manifest, and a local
  decrypt-restore-compare against the live partition before storing.
- **Cold destination:** only `LocalDiskColdStorageBackend`
  (`AUDIT_LOG_COLD_STORAGE_DIR`) exists. The S3 Glacier (São Paulo, Object Lock
  compliance mode) target chosen by the Capitão in order 020 is **not implemented**
  (its own order; needs `boto3` and MinIO for the proof).
- **Partitions are created on the real path** (order 021):
  `manage.py ensure_audit_partitions` runs after `migrate_schemas`
  (`scripts/migrate_schemas.sh`, `docs/DEPLOY.md`) and daily via Celery Beat
  (`core.ensure_audit_partitions`, 00:15 `America/Sao_Paulo`, migration `0045`). It
  pre-creates the current and next month for each tenant.
- **A row in a DEFAULT leaf is an alarm** — it now means a missing partition. The
  command logs a `WARNING` and prints `ALERTA: … linha(s) em folha(s) DEFAULT`;
  the fix is `backfill_audit_partitions` (see [RUNBOOK.md](./RUNBOOK.md) §8).
- Storage estimate (worst case, polling screens audited): ~3.6 GB/year/tenant,
  summed across clinics (ADR-0001).

### 3.7 HTTP Security Headers

Enforced on both nginx server blocks — the plain-HTTP `:80` block
(`docker/nginx/nginx.conf`) and the operator-enabled HTTPS `:443` block
(`docker/nginx/ssl.conf`). `Strict-Transport-Security` is only served on the
HTTPS block.

```nginx
# served on both :80 (nginx.conf) and :443 (ssl.conf)
add_header X-Content-Type-Options "nosniff" always;
add_header X-Frame-Options "DENY" always;
add_header X-XSS-Protection "1; mode=block" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
add_header Permissions-Policy "camera=(self), microphone=(self), geolocation=()" always;

# HTTPS block only (ssl.conf)
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
```

Camera and microphone are restricted to same-origin (`self`) rather than fully
disabled, specifically so the AI Clinical Scribe (browser audio capture via
getUserMedia/Web Speech) and telemedicine keep working; cross-origin and
third-party access is still blocked. Geolocation is unused and is disabled.

**Content-Security-Policy is report-only (non-enforcing).** Both nginx server
blocks ship `Content-Security-Policy-Report-Only` with the identical policy
below; neither serves an enforcing `Content-Security-Policy` header. The
documented plan is to observe violations first, then promote to enforcing once
the policy is confirmed clean. Note that no report-collection endpoint
(`report-to`/`report-uri`) is wired up yet, so violations currently surface only
in the browser console.

```nginx
# report-only, served on both :80 (nginx.conf) and :443 (ssl.conf)
add_header Content-Security-Policy-Report-Only "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; font-src 'self' data:; connect-src 'self'; frame-ancestors 'none';" always;
```

See §9 for the shipped-control summary.

---

## 4. LGPD Compliance Checklist

### 4.1 Legal Basis (Art. 7 e 11)
- [x] Healthcare data processing under Art. 7 VIII (tutela da saúde) and Art. 11 II f
- [x] WhatsApp opt-in: explicit consent with clear purpose (Art. 8)
- [x] Marketing messages: separate consent from operational messages

### 4.2 Data Subject Rights (Art. 17-22)
- [ ] Right to access: Patient portal showing all their data (Phase 3)
- [x] Right to access: API endpoint for data export (JSON) — available to tenant admin
- [x] Right to correction: Edit patient data with audit trail
- [x] Right to deletion: Soft delete + anonymization pipeline (except legally required retention)
- [x] Right to portability: FHIR-compatible export format
- [ ] Right to information: Privacy policy and cookie consent on all patient-facing interfaces

### 4.3 Technical Measures
- [x] Encryption at rest and in transit
- [x] Access control with audit logging
- [x] Data minimization: only collect what's clinically/operationally necessary
- [x] Pseudonymization for analytics (no PII in BI dashboards)
- [x] Incident response plan: breach notification within 72h to ANPD

### 4.4 Organizational Measures
- [ ] DPO designation (required for tenant, Vitali provides tooling)
- [ ] Data Processing Agreement (DPA) template for tenants
- [ ] Privacy Impact Assessment (RIPD) for high-risk processing
- [ ] Employee training on data protection

---

## 5. TISS/TUSS Compliance

### 5.1 TISS (RN 501/2022)
- XML generation following TISS schema version 4.01.00
- All 5 TISS components addressed:
  - Organizational: versioning, contingency plan
  - Content/Structure: XML schemas per guide type
  - Terminology (TUSS): code database with version tracking
  - Security/Privacy: aligned with LGPD
  - Communication: XML submission to insurance providers

### 5.2 Guide Types Supported (MVP)
- Guia de Consulta
- Guia SP/SADT (Serviço Profissional / Serviço Auxiliar de Diagnóstico e Terapia)
- Guia de Internação (basic)
- Guia de Honorários

### 5.3 TUSS Database
- Imported from official ANS publication
- Automatic update detection (ANS publishes updates periodically)
- Full-text search with trigram index for fuzzy matching
- AI augmentation: LLM suggests codes from procedure description

---

## 6. CFM Compliance (Prontuário Eletrônico)

### Resolução CFM 1.821/2007 + 2.218/2018
- [x] Record integrity: signed clinical notes are immutable (append-only)
- [x] Traceability: all access and modifications logged with timestamp and user
- [~] Digital signature: ICP-Brasil certificate integration (Phase 2) — **primitive shipped 2026-05-20**, **chain-of-trust validation shipped 2026-05-31** (`apps.signatures`): A1 PKCS#12 load + SHA-256/RSA-PKCS#1v15 sign + verify + tenant-scoped `DigitalSignature` storage, gated by FeatureFlag `signatures` (default OFF). REST: `POST /api/v1/signatures/sign/`, `GET /api/v1/signatures/`. Real chain-of-trust validation (path to a configured ICP-Brasil anchor + validity window + CA/KeyUsage constraints + policy OIDs) now sets `is_icp_brasil`, enforced via `ICP_BRASIL_ENFORCE_CHAIN`. Since order 015 an **empty trust store refuses the signature** (HTTP 400, reason `trust store not populated`, no row written) whenever `ICP_BRASIL_ENFORCE_CHAIN=True` (default; `development.py` pins `False` for dev/CI). Since order 014 the trust store is a named volume (`icp_truststore`) in staging and production, so anchors survive a redeploy. The doctor's PKCS#12 is never stored server-side: `pkcs12_b64`/`pkcs12_password` are write-only request fields. Revocation (CRL/OCSP) is implemented but **off** (`ICP_BRASIL_CHECK_REVOCATION=False`); turning it on is a production prerequisite — see **[ICP_BRASIL.md](./ICP_BRASIL.md)**. Remaining: enabling revocation, A3 hardware-token (PKCS#11) support, and end-to-end integration into the encounter / prescription sign flows.
- [x] Availability: minimum 20 years retention — audit trail: 240 months per tenant, purge off by default (order 021, [ADR-0001](./adr/ADR-0001-retencao-auditoria-20-anos.md))
- [x] Backup: daily automated backups with tested restore
- [x] Access control: role-based, medical records accessible only by authorized professionals
- [ ] SBIS/CFM certification: formal certification process (future, requires audit)

---

## 7. Infrastructure Security

### VPS Phase
- SSH key-only authentication (no password)
- UFW firewall: only ports 80, 443, 22 (restricted IP)
- Docker containers run as non-root
- Automatic security updates (unattended-upgrades)
- Fail2ban for SSH brute force protection
- Daily encrypted backups to external storage

### AWS Phase
- VPC with private subnets for database/services
- Security groups: least privilege
- IAM roles for service access (no static credentials)
- AWS WAF in front of ALB
- GuardDuty for threat detection
- CloudTrail for API audit logging
- RDS encryption + automated backups with PITR

---

## 8. Dependency Security

- Dependabot enabled on GitHub repo
- `pip audit` in CI pipeline (Python vulnerabilities)
- `npm audit` in CI pipeline (Node.js vulnerabilities)
- Docker base images pinned to specific SHA digests
- Trivy container scanning before deployment
- Lock files committed: `poetry.lock` + `package-lock.json`

---

## 9. Implemented Hardening (2026-05-30)

This section records what is actually shipped and enforced on `master`, as opposed
to the intended controls above. Companion docs hold the operator details.

| Control | Status | Where |
|---------|--------|-------|
| PII encrypted at rest (CPF + name, contact, address, clinical notes/diagnoses) | ✅ Shipped | `apps/core/fields.py`, migration `0016`; see [LGPD_PATIENT_PII_ENCRYPTION.md](./LGPD_PATIENT_PII_ENCRYPTION.md) |
| Read-access audit (`view_record`) on patient/encounter | ✅ Shipped | `apps/core/mixins.py::AuditReadMixin` |
| Read-trail coverage guard per GET route (154 views · 74 require trail · 321 GET routes · 0 uncovered) | ✅ Shipped (orders 016–019) | `apps/core/audit_coverage.py`, `audit_coverage_routes.py`, `tests/test_auditoria_leitura_cobertura.py`; see §3.6.1 |
| `core_auditlog` partitioned (month × tenant, DEFAULT at both levels), purge gated by verified cold export | ✅ Shipped (order 020) | migration `0043`, `apps/core/partitioning.py`, `apps/core/cold_storage.py`; see §3.6.2 |
| Audit retention 240 months per tenant, purge off by default; partitions ensured on deploy + daily | ✅ Shipped (order 021) | `TenantAuditRetention`, `ensure_audit_partitions`, [ADR-0001](./adr/ADR-0001-retencao-auditoria-20-anos.md) |
| ICP-Brasil trust store on a volume; empty store refuses signing | ✅ Shipped (orders 014, 015) | `docker-compose.{staging,prod}.yml` (`icp_truststore`), `apps/signatures/services/icp_brasil.py`; see [ICP_BRASIL.md](./ICP_BRASIL.md) |
| Audit cold copy offsite (S3 Glacier) | ❌ Not built | only `LocalDiskColdStorageBackend` exists |
| ICP-Brasil revocation (CRL/OCSP) enforced | ❌ Off | `ICP_BRASIL_CHECK_REVOCATION=False` everywhere; production prerequisite |
| Fail-fast secret validation at prod startup | ✅ Shipped | `vitali/settings/_security_checks.py`; see [SECRETS.md](./SECRETS.md) |
| `X-Forwarded-Host` validated before tenant routing | ✅ Shipped | `apps/core/middleware.py::XForwardedHostValidationMiddleware` |
| Platform-admin via single `is_platform_admin()` (no blanket superuser bypass) | ✅ Shipped | `apps/core/permissions.py` |
| MFA enrolment grace 30→7 days | ✅ Shipped | `MFA_GRACE_PERIOD_DAYS` in `settings/base.py` |
| TUSS LLM-input sanitization | ✅ Shipped | `apps/ai/services.py` |
| Backend container runs non-root | ✅ Shipped | `backend/Dockerfile` (`USER appuser`) |
| TLS-ready nginx + report-only CSP | ✅ Shipped | `docker/nginx/ssl.conf`; see [TLS.md](./TLS.md) |
| Automated PostgreSQL backups | ✅ Shipped | `scripts/backup.sh` + staging `db-backup` profile; see [BACKUPS.md](./BACKUPS.md) |
| Service healthchecks + staging resource limits | ✅ Shipped | `docker-compose.yml`, `docker-compose.staging.yml` |

**Operational follow-ups (provisioning, not code):** provision a real TLS cert
(Let's Encrypt/Cloudflare), supply real secrets in the deploy environment (the
validators now require them), and configure an offsite (S3) backup target.

---

*Next: [EPICS_AND_ROADMAP.md](./EPICS_AND_ROADMAP.md)*

---

## MFA enrollment enforcement (S28-04)

MFA is mandatory for elevated/sensitive accounts:

- **Who:** `is_staff` / `is_superuser`, plus any user whose role is in
  `MFA_REQUIRED_ROLES` (default `admin`, `medico`, `dentista`).
- **Grace:** a covered user must enrol a TOTP device within
  `MFA_GRACE_PERIOD_DAYS` (default 7) of account creation. Inside the window
  they can work while setting MFA up; past it, requests return `403`
  `mfa_enrollment_required` (redirect `/auth/mfa/setup`) until they enrol.
- **Enrolled but unverified:** `403` `mfa_required` until they pass TOTP this session.
- Tunable via env: `MFA_REQUIRED_ROLES`, `MFA_GRACE_PERIOD_DAYS`. Set grace to `0`
  to require MFA immediately.

Enforced in `apps.core.middleware.MFARequiredMiddleware`; logic in `apps.core.mfa`
(`mfa_required_for`, `mfa_enrollment_grace_expired`).

## CSP violation reporting (S28-05)

CSP ships **report-only** with `report-uri /api/v1/security/csp-report`. The sink
(`vitali/urls_public.py::csp_report`, unauthenticated, CSRF-exempt, logs to
`vitali.security.csp`) collects violations so the policy can be promoted to enforcing
data-driven. **Promotion to enforcing is gated** on: a clean violation log AND a
browser QA pass — Next.js inline hydration scripts need nonce support before
`'unsafe-inline'`/inline scripts can be dropped from `script-src`.
