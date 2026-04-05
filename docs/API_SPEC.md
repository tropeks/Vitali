# Vitali — API Specification

> **Refs:** [ARCHITECTURE.md](./ARCHITECTURE.md) | [DATA_MODEL.md](./DATA_MODEL.md) |
> [SECURITY.md](./SECURITY.md)

---

## 1. API Design Principles

- **REST** with consistent resource naming (`/api/v1/{resource}`)
- **JSON** request/response bodies
- **UUID** for all public resource IDs (never expose auto-increment)
- **Pagination:** cursor-based for lists (`?cursor=xxx&limit=20`)
- **Filtering:** query params (`?status=active&date_from=2026-01-01`)
- **Versioning:** URL path (`/api/v1/`, `/api/v2/`)
- **Auth:** Bearer JWT in Authorization header (access token)
- **Tenant:** Resolved from subdomain (clinica-aurora.vitali.com.br) — no tenant_id in requests
- **Errors:** Consistent format (see below)
- **OpenAPI 3.1** docs auto-generated via drf-spectacular

### Error Response Format
```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "One or more fields are invalid.",
    "details": [
      {"field": "email", "message": "This email is already registered."}
    ]
  }
}
```

### Standard HTTP Status Codes
| Code | Usage |
|------|-------|
| 200 | Success (GET, PUT, PATCH) |
| 201 | Created (POST) |
| 204 | No Content (DELETE) |
| 400 | Validation error |
| 401 | Authentication required |
| 403 | Permission denied / Module not active |
| 404 | Resource not found |
| 409 | Conflict (double booking, duplicate) |
| 429 | Rate limit exceeded |
| 500 | Internal server error |

---

## 2. Auth Endpoints

```
POST /api/v1/auth/login
  Request:  { "email": "string", "password": "string" }
  Response 200:
    { "access": "jwt_token", "refresh": "jwt_token", "user": UserDTO }
  Response 401:
    { "error": { "code": "INVALID_CREDENTIALS" } }
  Rate limit: 5 req/min per IP
  Auth: none

POST /api/v1/auth/refresh
  Request:  { "refresh": "jwt_token" }
  Response 200:
    { "access": "new_jwt_token", "refresh": "new_refresh_token" }
  Auth: none

POST /api/v1/auth/logout
  Request:  { "refresh": "jwt_token" }
  Response 204
  Auth: Bearer (access token)

PUT /api/v1/auth/password
  Request:  { "current_password": "string", "new_password": "string" }
  Response 204
  Auth: Bearer
```

### UserDTO
```json
{
  "id": "uuid",
  "email": "string",
  "full_name": "string",
  "role": { "id": "uuid", "name": "string", "permissions": ["string"] },
  "professional": { "id": "uuid", "council": "CRM 12345/SP" } | null,
  "active_modules": ["emr", "billing", "pharmacy", "ai_tuss", "whatsapp"]
}
```

---

## 3. Patient Endpoints

```
GET /api/v1/patients
  Query: ?search=João&status=active&limit=20&cursor=xxx
  Response 200:
    { "results": [PatientListDTO], "next_cursor": "string" | null, "count": int }
  Auth: Bearer + emr.read
  Rate limit: 100/min

POST /api/v1/patients
  Request:  PatientCreateDTO
  Response 201: PatientDetailDTO
  Auth: Bearer + emr.write

GET /api/v1/patients/{id}
  Response 200: PatientDetailDTO
  Auth: Bearer + emr.read

PATCH /api/v1/patients/{id}
  Request:  Partial PatientCreateDTO
  Response 200: PatientDetailDTO
  Auth: Bearer + emr.write

GET /api/v1/patients/{id}/timeline
  Query: ?type=encounter,prescription&date_from=2026-01-01&limit=50
  Response 200: { "events": [TimelineEventDTO] }
  Auth: Bearer + emr.read

GET /api/v1/patients/{id}/allergies
  Response 200: [AllergyDTO]
  Auth: Bearer + emr.read

POST /api/v1/patients/{id}/allergies
  Request:  AllergyCreateDTO
  Response 201: AllergyDTO
  Auth: Bearer + emr.write
```

---

## 4. Scheduling Endpoints

```
GET /api/v1/appointments
  Query: ?professional_id=uuid&date=2026-04-01&status=scheduled
  Response 200: { "results": [AppointmentDTO] }
  Auth: Bearer + emr.read

POST /api/v1/appointments
  Request:
    {
      "patient_id": "uuid",
      "professional_id": "uuid",
      "start_time": "ISO8601",
      "end_time": "ISO8601",
      "type": "first_visit|return|procedure|exam",
      "source": "web|whatsapp|phone|walk_in",
      "notes": "string?"
    }
  Response 201: AppointmentDTO
  Response 409: { "error": { "code": "TIME_SLOT_UNAVAILABLE" } }
  Auth: Bearer + scheduling.write

PATCH /api/v1/appointments/{id}/status
  Request:  { "status": "confirmed|waiting|in_progress|completed|no_show|cancelled" }
  Response 200: AppointmentDTO
  Auth: Bearer + scheduling.write

GET /api/v1/professionals/{id}/available-slots
  Query: ?date=2026-04-01&type=first_visit
  Response 200:
    {
      "slots": [
        { "start": "ISO8601", "end": "ISO8601", "available": true }
      ]
    }
  Auth: Bearer + scheduling.read
```

---

## 5. EMR Endpoints

```
POST /api/v1/encounters
  Request:
    {
      "patient_id": "uuid",
      "professional_id": "uuid",
      "appointment_id": "uuid?",
      "type": "outpatient|inpatient|emergency",
      "chief_complaint": "string?"
    }
  Response 201: EncounterDTO
  Auth: Bearer + emr.write

PATCH /api/v1/encounters/{id}
  Request:
    {
      "vitals": { "bp_systolic": 120, "bp_diastolic": 80, ... },
      "diagnosis": [{ "cid10_code": "J06.9", "description": "IVAS", "type": "primary" }],
      "status": "completed?"
    }
  Response 200: EncounterDTO
  Auth: Bearer + emr.write

POST /api/v1/encounters/{id}/notes
  Request:
    {
      "note_type": "evolution|anamnesis|physical_exam",
      "content": { "subjective": "...", "objective": "...", "assessment": "...", "plan": "..." }
    }
  Response 201: ClinicalNoteDTO
  Auth: Bearer + emr.write

POST /api/v1/encounters/{id}/notes/{note_id}/sign
  Response 200: ClinicalNoteDTO (with signed=true, signature_hash)
  Auth: Bearer + emr.sign (medical professionals only)

POST /api/v1/encounters/{id}/prescriptions
  Request:
    {
      "type": "medication|exam|procedure",
      "valid_until": "date?",
      "items": [
        {
          "drug_id": "uuid?",
          "description": "Amoxicilina 500mg",
          "dosage": "500mg",
          "route": "oral",
          "frequency": "8/8h",
          "duration": "7 dias",
          "quantity": 21,
          "unit": "cp"
        }
      ]
    }
  Response 201: PrescriptionDTO
  Auth: Bearer + emr.prescribe

GET /api/v1/cid10
  Query: ?search=diabetes&limit=10
  Response 200: [{ "code": "E11", "description": "Diabetes mellitus tipo 2" }]
  Auth: Bearer
```

---

## 6. Billing Endpoints

```
GET /api/v1/tuss/search
  Query: ?q=consulta+consultorio&table_type=procedures&limit=10
  Response 200:
    [{ "code": "10101012", "term": "Consulta em consultório...", "table_type": "procedures" }]
  Auth: Bearer + billing.read

POST /api/v1/tiss/guides
  Request:
    {
      "encounter_id": "uuid",
      "insurance_provider_id": "uuid",
      "guide_type": "consultation|sp_sadt|internment|fees",
      "items": [
        { "tuss_code": "10101012", "quantity": 1, "unit_price": 150.00 }
      ]
    }
  Response 201: TISSGuideDTO (with generated XML preview)
  Auth: Bearer + billing.write

GET /api/v1/tiss/guides/{id}/xml
  Response 200: application/xml (TISS-compliant XML)
  Auth: Bearer + billing.read

POST /api/v1/tiss/batches
  Request:  { "insurance_provider_id": "uuid", "guide_ids": ["uuid"] }
  Response 201: TISSBatchDTO (with xml_file_url for download)
  Auth: Bearer + billing.write

GET /api/v1/glosas
  Query: ?status=open&insurance_provider_id=uuid&date_from=2026-01-01
  Response 200: { "results": [GlosaDTO], "summary": { "total_amount": 5000.00, "count": 12 } }
  Auth: Bearer + billing.read
```

---

## 7. Pharmacy Endpoints

```
GET /api/v1/pharmacy/drugs
  Query: ?search=amoxicilina&is_controlled=false&limit=20
  Response 200: { "results": [DrugDTO] }
  Auth: Bearer + pharmacy.read

GET /api/v1/pharmacy/stock
  Query: ?drug_id=uuid&low_stock=true&expiring_in_days=30
  Response 200: { "results": [StockItemDTO] }
  Auth: Bearer + pharmacy.read

POST /api/v1/pharmacy/dispensations
  Request:
    {
      "prescription_id": "uuid",
      "items": [
        { "prescription_item_id": "uuid", "stock_item_id": "uuid", "quantity": 21 }
      ]
    }
  Response 201: DispensationDTO
  Response 400: { "error": { "code": "INSUFFICIENT_STOCK" } }
  Auth: Bearer + pharmacy.dispense
```

---

## 8. AI Endpoints

```
POST /api/v1/ai/tuss-suggest/
  Request:
    {
      "description": "Consulta médica em consultório horário normal",
      "guide_type": "consulta"  (optional — one of: sadt, sp_sadt, consulta, internacao, odonto, "")
    }
  Response 200:
    {
      "suggestions": [
        {
          "tuss_code": "10101012",
          "description": "Consulta em consultório (no horário normal)",
          "rank": 1,
          "tuss_code_id": "uuid",
          "suggestion_id": "uuid"
        },
        ...
      ],
      "cached": false,
      "degraded": false
    }
  Auth: Bearer + ai.use (requires FEATURE_AI_TUSS=True)
  Rate limit: AI_RATE_LIMIT_PER_HOUR per tenant (default 100/hour)
  Note: Returns 404 if FEATURE_AI_TUSS feature flag is disabled.

POST /api/v1/ai/tuss-suggest/feedback/
  Request:  { "suggestion_id": "uuid", "accepted": true|false }
  Response 200: { "status": "ok" }
  Auth: Bearer + ai.use
  Note: Records acceptance/rejection signal for prompt quality improvement.

GET /api/v1/ai/usage/
  Query: ?year=2026&month=3
  Response 200:
    {
      "year": 2026,
      "month": 3,
      "llm_calls": 142,
      "tokens_in": 58000,
      "tokens_out": 12000,
      "total_latency_ms": 71000,
      "suggestions_shown": 142,
      "suggestions_accepted": 98,
      "acceptance_rate": 0.690
    }
  Auth: Bearer + users.read (admin only)
```

---

## 9. Analytics Endpoints (Sprint 10)

```
GET /api/v1/analytics/billing/overview/
  Query: —
  Response 200: { denial_rate, total_billed, total_collected, total_denied, month }
  Auth: Bearer (IsAuthenticated)
  Note: KPI cards locked to current month

GET /api/v1/analytics/billing/monthly-revenue/
  Query: ?period=6m  (3m | 6m | 12m, default 6m)
  Response 200: [{ competency, billed, collected, denied }]
  Auth: Bearer (IsAuthenticated)
  Note: Groups by TISSGuide.competency CharField, not created_at

GET /api/v1/analytics/billing/denial-by-insurer/
  Query: ?period=6m
  Response 200: [{ provider_name, denied_value, denied_count }]  (sorted desc)
  Auth: Bearer (IsAuthenticated)
  Note: Floor: insurers with ≥10 guides only

GET /api/v1/analytics/billing/batch-throughput/
  Query: ?period=6m
  Response 200: [{ month, created, closed }]
  Auth: Bearer (IsAuthenticated)

GET /api/v1/analytics/billing/glosa-accuracy/
  Query: ?period=6m
  Response 200: [{ provider_name, precision, recall, total, predicted_high, denied_count, true_positives }]
  Auth: Bearer (IsAuthenticated)
  Note: precision=null when no high-risk predictions; excludes unresolved (was_denied=None) from denominators
```

---

## 10. WhatsApp Endpoints

```
POST /api/v1/whatsapp/webhook/
  Request:  Evolution API webhook payload (messages.upsert, connection.update)
  Response 200  (always 200 — Evolution API retries on non-2xx)
  Auth: HMAC-SHA256 signature via X-Hub-Signature-256 header (fail-closed)
  Note: Triggers ConversationFSM state machine; no JWT required (Evolution API posts directly)

GET /api/v1/whatsapp/health/
  Response 200: { "status": "ok", "evolution_api": { "state": "open|connecting|close", "phone": "...", "last_seen": "..." } }
  Response 503: { "status": "error", "detail": "..." }
  Auth: Bearer + module:whatsapp

POST /api/v1/whatsapp/setup-webhook/
  Response 200: { "status": "ok", "webhook_url": "https://..." }
  Auth: Bearer + module:whatsapp
  Note: Registers this server's webhook URL with Evolution API; URL derived server-side (not from request body)

GET /api/v1/whatsapp/contacts/
  Query: ?search=nome_ou_telefone&page=N&page_size=N
  Response 200: { "count": N, "results": [WhatsAppContactDTO] }
  Auth: Bearer + module:whatsapp

GET /api/v1/whatsapp/contacts/{id}/
  Response 200: WhatsAppContactDTO
  Auth: Bearer + module:whatsapp

GET /api/v1/whatsapp/message-logs/
  Query: ?contact=uuid&phone=+55...&page=N
  Response 200: { "count": N, "results": [MessageLogDTO] }
  Auth: Bearer + module:whatsapp

GET /api/v1/whatsapp/message-logs/{id}/
  Response 200: MessageLogDTO
  Auth: Bearer + module:whatsapp
```

**DTOs:**
```json
WhatsAppContactDTO: {
  "id": "uuid", "phone": "+55...", "patient_name": "string|null",
  "opt_in": true, "opt_in_at": "ISO8601|null", "opt_out_at": "ISO8601|null",
  "created_at": "ISO8601"
}
MessageLogDTO: {
  "id": "uuid", "contact": "uuid", "contact_phone": "+55...", "patient_name": "string|null",
  "direction": "inbound|outbound", "content_preview": "string (200 chars, CPF masked)",
  "message_type": "text|button_reply|template", "appointment": "uuid|null",
  "created_at": "ISO8601"
}
```

---

## 10. Platform Admin Endpoints (Public Schema)

```
GET    /api/v1/platform/tenants         — List all tenants
POST   /api/v1/platform/tenants         — Create tenant
PATCH  /api/v1/platform/tenants/{id}    — Update tenant status
GET    /api/v1/platform/subscriptions   — List subscriptions
PATCH  /api/v1/platform/subscriptions/{id} — Activate/deactivate modules
GET    /api/v1/platform/ai-usage        — AI usage across tenants (cost report)
Auth: Platform admin JWT (separate from tenant auth)
```

---

*All endpoints documented in OpenAPI 3.1 format via drf-spectacular, accessible at `/api/docs/`*

*Next: [SECURITY.md](./SECURITY.md) | [EPICS_AND_ROADMAP.md](./EPICS_AND_ROADMAP.md)*
