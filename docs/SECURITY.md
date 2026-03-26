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
- Logs are append-only (no UPDATE/DELETE on AuditLog table)
- Retention: minimum 20 years for clinical records (CFM requirement), 5 years for operational
- Format: structured JSON, shipped to centralized logging

### 3.7 HTTP Security Headers
```nginx
# nginx.conf
add_header X-Content-Type-Options "nosniff" always;
add_header X-Frame-Options "DENY" always;
add_header X-XSS-Protection "1; mode=block" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
add_header Permissions-Policy "camera=(), microphone=(), geolocation=()" always;
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self' https://api.anthropic.com https://api.openai.com;" always;
```

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
- [ ] Digital signature: ICP-Brasil certificate integration (Phase 2)
- [x] Availability: minimum 20 years retention
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

*Next: [EPICS.md](./EPICS.md) | [ROADMAP.md](./ROADMAP.md)*
