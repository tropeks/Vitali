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

POST /api/v1/ai/glosa-predict/
  Request:
    {
      "tuss_code": "40302477",
      "insurer_ans_code": "123456",
      "insurer_name": "Unimed Nacional",
      "cid10_codes": ["J18.9"],
      "guide_type": "sadt"  (one of: sadt, sp_sadt, consulta, internacao, odonto)
    }
  Response 200:
    {
      "prediction_id": "uuid|null",
      "risk_level": "low|medium|high",
      "risk_reason": "Texto curto em PT-BR explicando o risco.",
      "risk_code": "",
      "degraded": false,
      "cached": false
    }
  Auth: Bearer + ai_tuss module + ai.use
  Note: Fail-open — returns risk_level=low + degraded=true when the global
        kill-switch (FEATURE_AI_GLOSA) or the per-tenant
        `ai_glosa_prediction_enabled` toggle is off.

GET /api/v1/fhir/metadata
  Response 200: <FHIR R4 CapabilityStatement>
  Auth: public — clients negotiate capabilities before authenticating.

GET /api/v1/fhir/Patient/{id}/
  Response 200: <FHIR R4 Patient resource>
  Auth: Bearer + fhir module + fhir.read
  Note: id is the Vitali Patient UUID. 404 returns a FHIR OperationOutcome-style body.

GET /api/v1/fhir/Patient/
  Query:
    identifier=<system>|<value>   — MRN system `urn:vitali:mrn` or CPF OID
                                     `urn:oid:2.16.840.1.113883.13.236`
    name=<substring>              — case-insensitive substring on full_name
    _count=<n>                    — page size, default 20, capped at 100
  Response 200:
    {
      "resourceType": "Bundle",
      "type": "searchset",
      "total": <int>,
      "entry": [{ "fullUrl": "…/fhir/Patient/<id>/", "resource": { … } }, …]
    }
  Auth: Bearer + fhir module + fhir.read

GET /api/v1/fhir/Encounter/{id}/
  Response 200: <FHIR R4 Encounter resource>
  Auth: Bearer + fhir module + fhir.read
  Note: Vitali encounter status maps to FHIR codes —
        `open` → `in-progress`, `signed` → `finished`,
        `cancelled` → `cancelled`. `class` is always ambulatory (AMB).
        `participant.individual` references the primary performer
        (`Practitioner/<uuid>`); `subject` references `Patient/<uuid>`.

GET /api/v1/fhir/Encounter/
  Query:
    subject=Patient/<uuid>        — filter by patient (also accepts bare uuid)
    patient=<uuid>                — alias of subject
    status=<fhir-code>            — `in-progress` | `finished` | `cancelled`
    _count=<n>                    — page size, default 20, capped at 100
  Response 200: <FHIR R4 searchset Bundle of Encounters>
  Auth: Bearer + fhir module + fhir.read

GET /api/v1/fhir/Practitioner/{id}/
  Response 200: <FHIR R4 Practitioner resource>
  Auth: Bearer + fhir module + fhir.read
  Note: Identifier system per council — `urn:vitali:council/crm`,
        `…/cro`, `…/coren`, `…/crf`, `…/crefito`, `…/crp`. CRM uses
        v2-0203 `MD` type code; other councils use `LN`. Qualification
        emitted both for the council itself and for CBO when present.

GET /api/v1/fhir/Practitioner/
  Query:
    identifier=<system>|<value>   — council token; bare value matches any council
    name=<substring>              — case-insensitive substring on linked user
    active=true|false             — FHIR boolean literal
    _count=<n>                    — page size, default 20, capped at 100
  Response 200: <FHIR R4 searchset Bundle of Practitioners>
  Auth: Bearer + fhir module + fhir.read

GET /api/v1/fhir/AllergyIntolerance/{id}/
  Response 200: <FHIR R4 AllergyIntolerance resource>
  Auth: Bearer + fhir module + fhir.read
  Note: criticality derived from Vitali severity — `mild` → `low`,
        `moderate` / `severe` / `life_threatening` → `high`.

GET /api/v1/fhir/AllergyIntolerance/
  Query:
    patient=Patient/<uuid>        — filter by patient (also bare uuid)
    clinical-status=<code>        — `active` | `inactive` | `resolved`
    _count=<n>                    — page size, default 20, capped at 100
  Response 200: <FHIR R4 searchset Bundle of AllergyIntolerance>
  Auth: Bearer + fhir module + fhir.read

GET /api/v1/fhir/MedicationRequest/{id}/
  Response 200: <FHIR R4 MedicationRequest resource>
  Auth: Bearer + fhir module + fhir.read
  Note: id is the Vitali PrescriptionItem uuid. `groupIdentifier`
        (system `urn:vitali:prescription`) carries the parent Prescription
        uuid so clients can group items by prescription.

GET /api/v1/fhir/MedicationRequest/
  Query:
    patient=Patient/<uuid>        — filter by patient (also bare uuid)
    status=<fhir-code>            — `draft` | `active` | `completed` | `cancelled`
    _count=<n>                    — page size, default 20, capped at 100
  Response 200: <FHIR R4 searchset Bundle of MedicationRequest>
  Auth: Bearer + fhir module + fhir.read

GET /api/v1/fhir/Observation/<encounter-uuid>_<loinc-code>/
  Response 200: <FHIR R4 Observation resource>
  Auth: Bearer + fhir module + fhir.read
  Note: id is composed of the encounter uuid and the LOINC code joined by
        an underscore (`_`). Supported LOINC codes: 29463-7 (weight),
        8302-2 (height), 8480-6 (SBP), 8462-4 (DBP), 8867-4 (heart rate),
        8310-5 (body temp), 59408-5 (SpO₂), 39156-5 (BMI, computed).

GET /api/v1/fhir/Observation/
  Query:
    patient=<uuid>                — joins via encounter
    encounter=<uuid>              — Encounter scope
    code=<loinc>                  — LOINC code (returns the matching vital)
    _count=<n>                    — page size, default 50, capped at 100
  Response 200: <FHIR R4 searchset Bundle of Observations>
  Auth: Bearer + fhir module + fhir.read

GET /api/v1/fhir/Condition/{id}/
  Response 200: <FHIR R4 Condition resource>
  Auth: Bearer + fhir module + fhir.read
  Note: code.coding uses the ICD-10 system URI
        (`http://hl7.org/fhir/sid/icd-10`) when the Vitali row carries a
        CID-10 code. controlled status rolls into FHIR `active` with the
        original Vitali state preserved in `note`.

GET /api/v1/fhir/Condition/
  Query:
    patient=<uuid>                — filter by patient
    clinical-status=<code>        — `active` | `resolved`
    category=<code>               — `problem-list-item` | `encounter-diagnosis`
    _count=<n>                    — page size, default 20, capped at 100
  Response 200: <FHIR R4 searchset Bundle of Conditions>
  Auth: Bearer + fhir module + fhir.read

GET /api/v1/fhir/ServiceRequest/{id}/
  Response 200: <FHIR R4 ServiceRequest resource>
  Auth: Bearer + fhir module + fhir.read
  Note: id is the underlying ClinicalDocument uuid. Only ClinicalDocument
        rows with doc_type in {referral, exam_request} are exposed here;
        other document types return 404. status derives from signature
        (unsigned → draft, signed → active).

GET /api/v1/fhir/ServiceRequest/
  Query:
    patient=<uuid>                — joins via encounter
    status=<fhir-code>            — `draft` | `active`
    category=<code>               — `referral` | `exam_request`
    _count=<n>                    — page size, default 20, capped at 100
  Response 200: <FHIR R4 searchset Bundle of ServiceRequests>
  Auth: Bearer + fhir module + fhir.read
```

---

## 11. Imaging Endpoints (Phase 2 — E-012)

```
GET /api/v1/imaging/studies/
  Query:
    patient=<uuid>                — filter by patient
    modality=<code>               — CR | CT | DX | MG | MR | NM | OT | PT | RF | US | XA
    encounter=<uuid>              — filter by encounter
    _count=<n>                    — page size, default 50, capped at 200
  Response 200: [ <DicomStudy>, ... ]
  Auth: Bearer + imaging module + imaging.read

POST /api/v1/imaging/studies/
  Request:
    {
      "patient": "<uuid>",
      "encounter": "<uuid|null>",
      "study_instance_uid": "<DICOM UID, unique>",
      "accession_number": "<clinic order number>",
      "modality": "CT|MR|...",
      "body_part_examined": "...",
      "description": "...",
      "study_date": "2026-05-20T14:00:00Z",
      "number_of_series": 0,
      "number_of_instances": 0,
      "orthanc_study_id": ""
    }
  Response 201: <DicomStudy>
  Auth: Bearer + imaging module + imaging.write

GET /api/v1/imaging/studies/{id}/
  Response 200: <DicomStudy>
  Auth: Bearer + imaging module + imaging.read

PATCH /api/v1/imaging/studies/{id}/orthanc/
  Request:
    {
      "orthanc_study_id": "<Orthanc study UUID>",
      "number_of_series": 3,
      "number_of_instances": 240
    }
  Response 200: <DicomStudy>
  Auth: Bearer + imaging module + imaging.write
  Note: Called by the Orthanc/PACS integration once the study is ingested.
        Sets `has_pixel_data=true` so the OHIF viewer can resolve it.
```

---

## 12. Telemedicine Endpoints (Phase 3)

```
GET  /api/v1/telemedicine/sessions/
  Query:
    patient=<uuid>                — filter by patient
    professional=<uuid>           — filter by professional
    status=<code>                 — scheduled | in_progress | completed | cancelled
  Response 200: [ <TelemedicineSession>, ... ]
  Auth: Bearer + telemedicine module + telemedicine.read

POST /api/v1/telemedicine/sessions/
  Request:
    {
      "appointment": "<uuid|null>",
      "patient": "<uuid>",
      "professional": "<uuid>",
      "scheduled_for": "2026-05-20T15:00:00Z",
      "notes": "..."
    }
  Response 201: <TelemedicineSession>  (mints a fresh `room_uid`)
  Auth: Bearer + telemedicine module + telemedicine.host

GET   /api/v1/telemedicine/sessions/{id}/                  — read
POST  /api/v1/telemedicine/sessions/{id}/start/            — scheduled → in_progress
POST  /api/v1/telemedicine/sessions/{id}/complete/         — in_progress → completed (sets duration_seconds)
POST  /api/v1/telemedicine/sessions/{id}/cancel/           — terminal cancel
PATCH /api/v1/telemedicine/sessions/{id}/recording/        — set recording_url

  Auth: Bearer + telemedicine module + telemedicine.host (read uses telemedicine.read)
  409: returned on invalid state transitions (e.g. complete from scheduled,
       start from a terminal state).
  Note: state transitions are explicit POSTs so each lifecycle event writes
        its own audit log entry (CFM Res. 2.314/2022 §3).
```

---

## 13. Patient Portal Endpoints (Phase 3)

```
# Admin surface — clinic staff mint and manage portal invites
GET  /api/v1/portal/access/                       — list (filter ?status=)
POST /api/v1/portal/access/                       — mint invite
POST /api/v1/portal/access/activate/              — patient consumes invite
                                                    body: {invite_token}
GET  /api/v1/portal/access/{id}/                  — read
POST /api/v1/portal/access/{id}/revoke/           — revoke

  Auth: Bearer + patient_portal module + users.read (write paths use users.write)

# Self-data surface — portal users see only their own patient
GET  /api/v1/portal/me/                           — own Patient profile
GET  /api/v1/portal/me/appointments/              — own Appointments
GET  /api/v1/portal/me/encounters/                — own Encounters (signed only)
GET  /api/v1/portal/me/prescriptions/             — own Prescriptions (signed+)
GET  /api/v1/portal/me/allergies/                 — own Allergies

  Auth: Bearer + patient_portal module + portal.self_access permission
        AND an active `PatientPortalAccess` row.
  Note: every self-data request updates `last_seen_at` on the access record.
```

---

## 14. i18n / Multi-country Endpoint (Phase 3)

> **Reality note (current state):** `preferred_language` is *stored* per
> user today and the endpoint below works, but the platform currently
> returns **pt-BR content regardless** of the selected language — the
> translation catalogs under `backend/locale/` are empty and source
> strings are not yet `gettext`-marked. Selecting another language has
> **no visible effect** until the Phase 3 i18n work lands. See
> `docs/I18N.md` for the phased plan.

```
GET  /api/v1/users/me/language/
  Response 200:
    {
      "preferred_language": "es" | "",
      "supported_languages": [{"code": "pt-br", "label": "Português (Brasil)"}, ...],
      "default": "pt-br"
    }
  Auth: Bearer

PATCH /api/v1/users/me/language/
  Request: { "preferred_language": "es" | "pt-pt" | "pt-br" | "en" | "" }
  Response 200: { "preferred_language": "<code>" }
  400: returned when the code is not in `LANGUAGES`; the response body
       carries the allowed set so clients can self-correct.
  Auth: Bearer
  Note: empty string clears the preference; subsequent requests fall back
        to the platform default (pt-BR) and `Accept-Language` negotiation.
```

---

## 15. Mobile backend (Phase 3)

```
# Self-surface (every authenticated user)
GET    /api/v1/mobile/devices/me/                — list own active devices
POST   /api/v1/mobile/devices/me/                — register / idempotent update
  Body: {platform, device_id, push_token, app_version?, os_version?}
DELETE /api/v1/mobile/devices/me/{device_pk}/    — soft-disable

# Admin surface (mobile.admin)
GET  /api/v1/mobile/devices/?user=…&platform=…&active=…  — admin list
POST /api/v1/mobile/push/                                 — fan-out push
  Body: {user, title, body?, data?}
GET  /api/v1/mobile/push/audit/?user=…&status=…           — recent deliveries

  Auth: Bearer + mobile module. Self endpoints need no extra perm;
        admin endpoints require `mobile.admin`.
  Note: until an FCM/APNS adapter is wired into MobilePushService,
        every dispatch records `status=no_provider` — the audit trail
        starts from day one regardless of provider status.
```

---

## 16. Triagem Inteligente (Phase 3)

```
GET  /api/v1/triage/questions/                     — return the question bank
GET  /api/v1/triage/sessions/?status=…&urgency=…   — list sessions
POST /api/v1/triage/sessions/                      — create session
GET  /api/v1/triage/sessions/{id}/                 — read session
PATCH /api/v1/triage/sessions/{id}/complaint/      — set chief complaint
POST /api/v1/triage/sessions/{id}/answer/          — body: {key, value}
POST /api/v1/triage/sessions/{id}/evaluate/        — run evaluator, may escalate
POST /api/v1/triage/sessions/{id}/complete/        — close out
POST /api/v1/triage/sessions/{id}/cancel/          — cancel session

  Auth: Bearer + triage module + triage.read (read paths) or triage.respond
        (write / transition paths).
  409: invalid state transition (answer after evaluation, complete before
       evaluation, double-evaluate, etc.).
  Urgency vocabulary: routine | urgent | emergency. `emergency` evaluation
  also flips session status to `escalated` and stamps `escalated_at` so
  CFM Res. 2.314/2022 §6 escalation audit is preserved on the record.
```

---

## 16. Smart Scheduling — slot ranker (Phase 3)

```
GET /api/v1/scheduling/suggest/
  Query:
    professional=<uuid>           — required
    patient=<uuid>                — optional; sharpens patient_history signal
    from=<YYYY-MM-DD>             — window start, defaults to today
    to=<YYYY-MM-DD>               — window end, defaults to from+13 days
    limit=<n>                     — page size, default 5, capped at 50
  Response 200:
    {
      "professional_id": "<uuid>",
      "patient_id": "<uuid|null>",
      "from": "2026-05-20",
      "to": "2026-06-02",
      "suggestions": [
        {
          "start": "...",
          "end": "...",
          "professional_id": "<uuid>",
          "score": 0.81,
          "components": {
            "clinical_time": 1.0,
            "gap_fill": 0.5,
            "patient_history": 0.5
          }
        },
        ...
      ]
    }
  400: missing professional / inverted window / window > 60 days / invalid limit.
  404: professional or patient not found.
  Auth: Bearer + smart_scheduling module + smart_scheduling.read
```

---

## 16. AI Farmácia — demand forecast (Phase 3)

```
GET /api/v1/pharmacy/forecast/
  Query:
    drug=<uuid>                   — required, Drug uuid
    window_days=<n>               — lookback, default 30, must be positive
    target_days=<n>               — target supply, default 60, must be positive
  Response 200:
    {
      "drug_id": "<uuid>",
      "drug_name": "Amoxicilina",
      "window_days": 30,
      "target_days": 60,
      "total_dispensed_in_window": 60.0,
      "avg_daily_consumption": 2.0,
      "current_stock": 40.0,
      "projected_days_of_supply": 20.0,
      "recommended_reorder_quantity": 80.0
    }
  400: missing/invalid params.
  404: drug not found.
  Auth: Bearer + pharmacy_ai module + pharmacy_ai.read
  Note: rule-based baseline (rolling-window arithmetic). A future iteration
        will swap in a seasonality-aware ML model behind the same shape.

POST /api/v1/signatures/sign/
  Request:
    {
      "document_type": "encounter|prescription|custom",
      "document_id": "<id of the signed document>",
      "document_b64": "<base64 of the bytes being signed>",
      "pkcs12_b64": "<base64 of the A1 PKCS#12 bundle>",
      "pkcs12_password": "<bundle password; \"\" if unencrypted>"
    }
  Response 201:
    {
      "id": "uuid",
      "document_type": "encounter",
      "document_id": "...",
      "signer": "uuid",
      "signer_name": "Dra Ana Silva",
      "signature_b64": "<base64 RSA-PKCS#1v15 + SHA-256 signature>",
      "signature_algorithm": "SHA256withRSA",
      "document_hash_hex": "<sha256 hex>",
      "cert_subject": "CN=...",
      "cert_issuer": "CN=...",
      "cert_serial_hex": "ABCD...",
      "cert_not_valid_before": "2025-…",
      "cert_not_valid_after": "2027-…",
      "is_icp_brasil": true,
      "signed_at": "2026-05-20T…"
    }
  Auth: Bearer + signatures module + signatures.sign
  Note: Stateless cryptographic primitive — does NOT validate the full
        ICP-Brasil chain of trust (DOC-ICP-04). PKCS#12 is consumed in-memory
        and not persisted.

GET /api/v1/signatures/
  Query: ?document_type=<type>&document_id=<id>
  Response 200: [ <DigitalSignature>, ... ] (capped at 200, newest first)
  Auth: Bearer + signatures module + signatures.read

POST /api/v1/ai/glosa-predict-batch/
  Request:
    {
      "insurer_ans_code": "123456",
      "insurer_name": "Unimed Nacional",
      "guide_type": "sadt",
      "items": [
        {"tuss_code": "40302477", "cid10_codes": ["J18.9"]},
        {"tuss_code": "40302485", "cid10_codes": ["J18.9", "B34.9"]}
      ]
    }
  Response 200:
    {
      "predictions": [
        {
          "tuss_code": "40302477",
          "prediction_id": "uuid|null",
          "risk_level": "low|medium|high",
          "risk_reason": "...",
          "risk_code": "",
          "degraded": false,
          "cached": false
        },
        ...
      ],
      "degraded_overall": false
    }
  Auth: Bearer + ai_tuss module + ai.use
  Limits: items capped at 50 per request; otherwise same as glosa-predict.
  Note: Wraps the per-row endpoint so a multi-item TISS guide is one
        round-trip instead of N parallel fires. `degraded_overall=true`
        when any item degrades or when the global / per-tenant gate is off.
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
