# HealthOS — API Specification

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
- **Tenant:** Resolved from subdomain (clinica-aurora.healthos.com.br) — no tenant_id in requests
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
POST /api/v1/ai/tuss-suggest
  Request:
    { "procedure_description": "Consulta médica em consultório horário normal" }
  Response 200:
    {
      "suggestions": [
        { "code": "10101012", "term": "Consulta em consultório (no horário normal)", "confidence": 0.95 },
        { "code": "10101020", "term": "Consulta em consultório (fora do horário normal)", "confidence": 0.72 },
        { "code": "10102019", "term": "Consulta em domicílio", "confidence": 0.15 }
      ],
      "cached": false,
      "tokens_used": 245
    }
  Auth: Bearer + ai.tuss_coding (feature flag)
  Rate limit: 30/min per tenant

POST /api/v1/ai/tuss-suggest/{suggestion_id}/accept
  Request:  { "accepted_code": "10101012" }
  Response 204
  Auth: Bearer
  Note: Tracks acceptance for improving prompts
```

---

## 9. WhatsApp Endpoints (Internal)

```
POST /api/v1/whatsapp/webhook  (called by Evolution API)
  Request:  Evolution API webhook payload (message received)
  Response 200
  Auth: Webhook secret header validation
  Note: Triggers ConversationFlow state machine

GET /api/v1/whatsapp/conversations
  Query: ?patient_id=uuid&status=active
  Response 200: [ConversationDTO]
  Auth: Bearer + whatsapp.read

POST /api/v1/whatsapp/send
  Request:
    { "phone": "+5511999999999", "template": "appointment_reminder", "params": {...} }
  Response 200: { "message_id": "string", "status": "sent" }
  Auth: Bearer + whatsapp.write (internal use by Celery tasks)
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
