# HealthOS — Data Model

> **Refs:** [ARCHITECTURE.md](./ARCHITECTURE.md) | [API_SPEC.md](./API_SPEC.md)

---

## 1. Multi-Tenancy Schema Structure

```
PostgreSQL Instance
├── public (shared schema)
│   ├── tenants_tenant          — Tenant registry
│   ├── tenants_domain          — Tenant domain mapping
│   ├── billing_plan            — Subscription plans
│   ├── billing_planmodule      — Modules in each plan
│   ├── billing_subscription    — Active subscriptions
│   ├── billing_invoice         — Invoices
│   ├── core_featureflag        — Global feature definitions
│   └── core_platformadmin      — Platform admin users
│
├── tenant_clinica_aurora (tenant schema - example)
│   ├── core_user               — Users within this tenant
│   ├── core_role / permission  — RBAC within tenant
│   ├── emr_patient             — Patients
│   ├── emr_encounter           — Encounters/Visits
│   ├── emr_prescription        — Prescriptions
│   ├── billing_tissguide       — TISS guides
│   ├── pharmacy_stockitem      — Inventory
│   ├── whatsapp_conversation   — Chat history
│   └── ...all tenant-specific tables
│
├── tenant_hospital_vida (another tenant)
│   └── ...same structure, completely isolated
```

---

## 2. Core Module Entities (public + tenant schemas)

### Public Schema

```
Entity: Tenant
  - id: UUID (PK)
  - name: VARCHAR(255) NOT NULL
  - slug: VARCHAR(100) UNIQUE NOT NULL  -- used for schema name
  - schema_name: VARCHAR(100) UNIQUE NOT NULL
  - cnpj: VARCHAR(18) UNIQUE
  - status: ENUM('trial','active','suspended','cancelled') DEFAULT 'trial'
  - trial_ends_at: TIMESTAMP
  - created_at: TIMESTAMP DEFAULT NOW()
  - updated_at: TIMESTAMP
  → has_one: Subscription
  → has_many: Domain

Entity: Plan
  - id: UUID (PK)
  - name: VARCHAR(100) NOT NULL  -- "Starter", "Professional", etc
  - base_price: DECIMAL(10,2) NOT NULL
  - is_active: BOOLEAN DEFAULT true
  - created_at: TIMESTAMP
  → has_many: PlanModule

Entity: PlanModule
  - id: UUID (PK)
  - plan_id: UUID (FK → Plan)
  - module_key: VARCHAR(50) NOT NULL  -- 'emr', 'billing', 'pharmacy', 'ai_tuss', 'whatsapp'
  - price: DECIMAL(10,2) NOT NULL  -- additional cost for this module
  - is_included: BOOLEAN DEFAULT false  -- included in base price?

Entity: Subscription
  - id: UUID (PK)
  - tenant_id: UUID (FK → Tenant) UNIQUE
  - plan_id: UUID (FK → Plan)
  - active_modules: JSONB NOT NULL  -- ['emr','billing','pharmacy','ai_tuss','whatsapp']
  - monthly_price: DECIMAL(10,2) NOT NULL
  - status: ENUM('active','past_due','cancelled')
  - current_period_start: DATE
  - current_period_end: DATE
  - created_at: TIMESTAMP
```

### Tenant Schema

```
Entity: User
  - id: UUID (PK)
  - email: VARCHAR(255) UNIQUE NOT NULL
  - password_hash: VARCHAR(255) NOT NULL
  - full_name: VARCHAR(255) NOT NULL
  - cpf: VARCHAR(14) UNIQUE  -- encrypted at rest
  - role_id: UUID (FK → Role)
  - professional_id: UUID (FK → Professional) NULLABLE
  - is_active: BOOLEAN DEFAULT true
  - last_login: TIMESTAMP
  - created_at: TIMESTAMP DEFAULT NOW()
  - updated_at: TIMESTAMP
  → belongs_to: Role
  → has_one: Professional (optional)
  → has_many: AuditLog

Entity: Role
  - id: UUID (PK)
  - name: VARCHAR(50) NOT NULL  -- 'admin','medico','enfermeiro','recepcionista','farmaceutico'
  - permissions: JSONB NOT NULL  -- ['emr.read','emr.write','billing.read','pharmacy.dispense']
  - is_system: BOOLEAN DEFAULT false  -- system roles can't be deleted
  - created_at: TIMESTAMP

Entity: AuditLog
  - id: BIGSERIAL (PK)
  - user_id: UUID (FK → User)
  - action: VARCHAR(50) NOT NULL  -- 'create','update','delete','login','view_record'
  - resource_type: VARCHAR(50) NOT NULL  -- 'patient','prescription','encounter'
  - resource_id: UUID
  - old_data: JSONB  -- before state (for updates)
  - new_data: JSONB  -- after state
  - ip_address: INET
  - user_agent: TEXT
  - created_at: TIMESTAMP DEFAULT NOW()
  INDEX: (resource_type, resource_id), (user_id, created_at), (created_at)
  NOTE: Append-only table. No UPDATE or DELETE allowed. Partition by month.
```

---

## 3. EMR Module Entities

```
Entity: Patient
  - id: UUID (PK)
  - medical_record_number: VARCHAR(20) UNIQUE NOT NULL  -- auto-generated
  - full_name: VARCHAR(255) NOT NULL
  - social_name: VARCHAR(255)  -- nome social (Brazilian law)
  - cpf: VARCHAR(14) UNIQUE  -- encrypted at rest
  - rg: VARCHAR(20)
  - birth_date: DATE NOT NULL
  - gender: ENUM('M','F','O','NI') NOT NULL
  - blood_type: VARCHAR(3)
  - mother_name: VARCHAR(255)
  - phone: VARCHAR(20)
  - whatsapp: VARCHAR(20)  -- may differ from phone
  - email: VARCHAR(255)
  - address: JSONB  -- {street, number, complement, neighborhood, city, state, zip}
  - insurance_data: JSONB  -- [{provider_id, card_number, plan_name, validity}]
  - emergency_contact: JSONB  -- {name, phone, relationship}
  - photo_url: VARCHAR(500)
  - is_active: BOOLEAN DEFAULT true
  - created_at: TIMESTAMP DEFAULT NOW()
  - updated_at: TIMESTAMP
  → has_many: Encounter, Allergy, MedicalHistory, Prescription, Appointment
  INDEX: (cpf), (full_name gin_trgm), (medical_record_number), (whatsapp)

Entity: Professional
  - id: UUID (PK)
  - user_id: UUID (FK → User) UNIQUE
  - full_name: VARCHAR(255) NOT NULL
  - council_type: ENUM('CRM','COREN','CRF','CRO','CREFITO','OTHER') NOT NULL
  - council_number: VARCHAR(20) NOT NULL
  - council_state: CHAR(2) NOT NULL
  - specialty: VARCHAR(100)
  - cbo_code: VARCHAR(10)  -- Classificação Brasileira de Ocupações
  - cnes_code: VARCHAR(20)  -- CNES do profissional
  - digital_signature_cert: TEXT  -- ICP-Brasil certificate reference
  - is_active: BOOLEAN DEFAULT true
  - created_at: TIMESTAMP
  → has_many: Encounter, Prescription, Schedule

Entity: Appointment
  - id: UUID (PK)
  - patient_id: UUID (FK → Patient) NOT NULL
  - professional_id: UUID (FK → Professional) NOT NULL
  - start_time: TIMESTAMP NOT NULL
  - end_time: TIMESTAMP NOT NULL
  - type: ENUM('first_visit','return','procedure','exam','emergency') NOT NULL
  - status: ENUM('scheduled','confirmed','waiting','in_progress','completed','no_show','cancelled')
  - source: ENUM('web','whatsapp','phone','walk_in') DEFAULT 'web'
  - notes: TEXT
  - whatsapp_reminder_sent: BOOLEAN DEFAULT false
  - whatsapp_confirmed: BOOLEAN DEFAULT false
  - created_at: TIMESTAMP
  - updated_at: TIMESTAMP
  → belongs_to: Patient, Professional
  → has_one: Encounter (optional)
  INDEX: (professional_id, start_time), (patient_id, start_time), (status)
  CONSTRAINT: no overlapping appointments per professional (exclusion constraint)

Entity: Encounter
  - id: UUID (PK)
  - patient_id: UUID (FK → Patient) NOT NULL
  - professional_id: UUID (FK → Professional) NOT NULL
  - appointment_id: UUID (FK → Appointment) NULLABLE
  - type: ENUM('outpatient','inpatient','emergency','day_hospital') NOT NULL
  - status: ENUM('open','in_progress','completed','cancelled') DEFAULT 'open'
  - start_time: TIMESTAMP NOT NULL
  - end_time: TIMESTAMP
  - chief_complaint: TEXT
  - clinical_notes: JSONB  -- structured SOAP or free-form
  - vitals: JSONB  -- {bp_systolic, bp_diastolic, hr, temp, spo2, weight, height}
  - diagnosis: JSONB  -- [{cid10_code, description, type: 'primary'|'secondary'}]
  - created_at: TIMESTAMP DEFAULT NOW()
  - updated_at: TIMESTAMP
  → belongs_to: Patient, Professional, Appointment
  → has_many: Prescription, Procedure, ClinicalNote, BillingItem

Entity: ClinicalNote
  - id: UUID (PK)
  - encounter_id: UUID (FK → Encounter) NOT NULL
  - author_id: UUID (FK → User) NOT NULL
  - note_type: ENUM('evolution','anamnesis','physical_exam','nursing','discharge') NOT NULL
  - content: JSONB NOT NULL  -- structured or SOAP format
  - signed: BOOLEAN DEFAULT false
  - signed_at: TIMESTAMP
  - signature_hash: VARCHAR(64)  -- SHA-256 of content at signing time
  - created_at: TIMESTAMP DEFAULT NOW()
  NOTE: Once signed, content becomes immutable. Amendments create new notes referencing original.

Entity: Prescription
  - id: UUID (PK)
  - encounter_id: UUID (FK → Encounter) NOT NULL
  - prescriber_id: UUID (FK → Professional) NOT NULL
  - patient_id: UUID (FK → Patient) NOT NULL
  - type: ENUM('medication','exam','procedure','diet','nursing') NOT NULL
  - status: ENUM('draft','active','dispensed','cancelled','expired') DEFAULT 'draft'
  - valid_until: DATE
  - notes: TEXT
  - signed: BOOLEAN DEFAULT false
  - signed_at: TIMESTAMP
  - created_at: TIMESTAMP DEFAULT NOW()
  → has_many: PrescriptionItem

Entity: PrescriptionItem
  - id: UUID (PK)
  - prescription_id: UUID (FK → Prescription) NOT NULL
  - drug_id: UUID (FK → pharmacy.Drug) NULLABLE
  - description: TEXT NOT NULL  -- free text or drug name
  - dosage: VARCHAR(100)  -- "500mg"
  - route: VARCHAR(50)  -- "oral", "IV", "IM"
  - frequency: VARCHAR(100)  -- "8/8h", "1x/dia"
  - duration: VARCHAR(50)  -- "7 dias"
  - quantity: DECIMAL(10,2)
  - unit: VARCHAR(20)
  - instructions: TEXT  -- "tomar em jejum"
  - tuss_code: VARCHAR(20) (FK → billing.TUSSCode) NULLABLE
  - tuss_ai_suggested: BOOLEAN DEFAULT false  -- was this code suggested by AI?
  - sort_order: INTEGER DEFAULT 0
  - created_at: TIMESTAMP

Entity: Allergy
  - id: UUID (PK)
  - patient_id: UUID (FK → Patient) NOT NULL
  - substance: VARCHAR(255) NOT NULL
  - reaction: TEXT
  - severity: ENUM('mild','moderate','severe','life_threatening') NOT NULL
  - status: ENUM('active','inactive','resolved') DEFAULT 'active'
  - reported_by: UUID (FK → User)
  - created_at: TIMESTAMP

Entity: MedicalHistory
  - id: UUID (PK)
  - patient_id: UUID (FK → Patient) NOT NULL
  - condition: VARCHAR(255) NOT NULL
  - cid10_code: VARCHAR(10)
  - type: ENUM('personal','family','surgical','obstetric','social')
  - status: ENUM('active','resolved','chronic')
  - onset_date: DATE
  - notes: TEXT
  - created_at: TIMESTAMP
```

---

## 4. Billing Module Entities

```
Entity: InsuranceProvider
  - id: UUID (PK)
  - name: VARCHAR(255) NOT NULL
  - ans_code: VARCHAR(20) UNIQUE  -- código ANS da operadora
  - cnpj: VARCHAR(18)
  - tiss_version: VARCHAR(10) DEFAULT '4.01.00'
  - submission_url: VARCHAR(500)  -- endpoint for XML submission
  - is_active: BOOLEAN DEFAULT true
  - config: JSONB  -- provider-specific settings
  - created_at: TIMESTAMP

Entity: TUSSCode
  - id: UUID (PK)
  - code: VARCHAR(20) UNIQUE NOT NULL  -- ex: "10101012"
  - term: TEXT NOT NULL  -- ex: "Consulta em consultório (no horário normal)"
  - table_type: ENUM('procedures','materials','drugs','fees') NOT NULL
  - chapter: VARCHAR(100)
  - subchapter: VARCHAR(100)
  - is_active: BOOLEAN DEFAULT true
  - ans_version: VARCHAR(20)  -- version of the ANS table
  - updated_at: TIMESTAMP
  INDEX: (code), (term gin_trgm full-text), (table_type)
  NOTE: Imported from official ANS CSV. Updated periodically.

Entity: TISSGuide
  - id: UUID (PK)
  - encounter_id: UUID (FK → Encounter) NULLABLE
  - patient_id: UUID (FK → Patient) NOT NULL
  - insurance_provider_id: UUID (FK → InsuranceProvider) NOT NULL
  - guide_type: ENUM('sp_sadt','internment','consultation','fees','summary') NOT NULL
  - guide_number: VARCHAR(20) UNIQUE NOT NULL  -- sequencial por prestador
  - authorization_number: VARCHAR(20)
  - main_procedure_tuss: VARCHAR(20)
  - total_amount: DECIMAL(12,2)
  - status: ENUM('draft','pending','submitted','paid','partial','denied','appealed')
  - xml_content: TEXT  -- generated TISS XML
  - submission_date: TIMESTAMP
  - payment_date: TIMESTAMP
  - payment_amount: DECIMAL(12,2)
  - created_at: TIMESTAMP DEFAULT NOW()
  - updated_at: TIMESTAMP
  → has_many: TISSGuideItem, Glosa

Entity: TISSGuideItem
  - id: UUID (PK)
  - guide_id: UUID (FK → TISSGuide) NOT NULL
  - tuss_code: VARCHAR(20) NOT NULL
  - description: TEXT NOT NULL
  - quantity: DECIMAL(10,2) NOT NULL
  - unit_price: DECIMAL(10,2) NOT NULL
  - total_price: DECIMAL(12,2) NOT NULL
  - reduction_factor: DECIMAL(5,4) DEFAULT 1.0
  - professional_id: UUID (FK → Professional) NULLABLE
  - created_at: TIMESTAMP

Entity: Glosa
  - id: UUID (PK)
  - guide_id: UUID (FK → TISSGuide) NOT NULL
  - guide_item_id: UUID (FK → TISSGuideItem) NULLABLE
  - glosa_code: VARCHAR(10)  -- código de glosa ANS
  - reason: TEXT NOT NULL
  - amount: DECIMAL(12,2) NOT NULL
  - status: ENUM('open','appealed','accepted','reversed') DEFAULT 'open'
  - appeal_text: TEXT
  - appeal_date: TIMESTAMP
  - resolution_date: TIMESTAMP
  - created_at: TIMESTAMP

Entity: TISSBatch
  - id: UUID (PK)
  - insurance_provider_id: UUID (FK → InsuranceProvider) NOT NULL
  - batch_number: VARCHAR(20) UNIQUE NOT NULL
  - guide_count: INTEGER NOT NULL
  - total_amount: DECIMAL(14,2) NOT NULL
  - xml_file_url: VARCHAR(500)  -- S3/MinIO path
  - status: ENUM('generated','submitted','acknowledged','processed')
  - submitted_at: TIMESTAMP
  - created_at: TIMESTAMP
  → has_many: TISSGuide (via batch_id)
```

---

## 5. Pharmacy Module Entities

```
Entity: Drug
  - id: UUID (PK)
  - name: VARCHAR(255) NOT NULL  -- nome comercial
  - generic_name: VARCHAR(255)  -- princípio ativo
  - manufacturer: VARCHAR(255)
  - presentation: VARCHAR(255)  -- "comprimido 500mg", "frasco 100ml"
  - barcode: VARCHAR(50)
  - anvisa_code: VARCHAR(20)  -- registro ANVISA
  - is_controlled: BOOLEAN DEFAULT false  -- medicamento controlado (Portaria 344)
  - control_type: VARCHAR(10)  -- "C1", "A1", "B1" etc (lista ANVISA)
  - requires_prescription: BOOLEAN DEFAULT true
  - is_active: BOOLEAN DEFAULT true
  - created_at: TIMESTAMP
  INDEX: (name gin_trgm), (generic_name gin_trgm), (barcode)

Entity: Material
  - id: UUID (PK)
  - name: VARCHAR(255) NOT NULL
  - description: TEXT
  - category: VARCHAR(100)  -- "surgical", "disposable", "lab", "cleaning"
  - barcode: VARCHAR(50)
  - unit: VARCHAR(20) NOT NULL  -- "un", "cx", "pct", "ml", "kg"
  - tuss_code: VARCHAR(20)
  - is_active: BOOLEAN DEFAULT true
  - created_at: TIMESTAMP

Entity: StockItem
  - id: UUID (PK)
  - item_type: ENUM('drug','material') NOT NULL
  - drug_id: UUID (FK → Drug) NULLABLE
  - material_id: UUID (FK → Material) NULLABLE
  - lot_number: VARCHAR(50)
  - expiry_date: DATE
  - quantity: DECIMAL(12,3) NOT NULL
  - min_stock: DECIMAL(12,3) DEFAULT 0
  - max_stock: DECIMAL(12,3)
  - location: VARCHAR(100)  -- storage location
  - unit_cost: DECIMAL(10,4)
  - updated_at: TIMESTAMP
  CONSTRAINT: (drug_id IS NOT NULL) OR (material_id IS NOT NULL)
  INDEX: (drug_id), (material_id), (expiry_date), (lot_number)

Entity: StockMovement
  - id: UUID (PK)
  - stock_item_id: UUID (FK → StockItem) NOT NULL
  - type: ENUM('entry','exit','adjustment','return','loss','transfer') NOT NULL
  - quantity: DECIMAL(12,3) NOT NULL  -- positive for in, negative for out
  - reason: TEXT
  - reference_type: VARCHAR(50)  -- 'dispensation', 'purchase_order', 'manual'
  - reference_id: UUID  -- FK to dispensation, PO, etc
  - user_id: UUID (FK → User) NOT NULL
  - created_at: TIMESTAMP DEFAULT NOW()
  NOTE: Append-only. Quantity changes through movements, never direct update.

Entity: Dispensation
  - id: UUID (PK)
  - prescription_id: UUID (FK → Prescription) NOT NULL
  - prescription_item_id: UUID (FK → PrescriptionItem) NOT NULL
  - patient_id: UUID (FK → Patient) NOT NULL
  - dispensed_by: UUID (FK → User) NOT NULL
  - stock_item_id: UUID (FK → StockItem) NOT NULL
  - quantity: DECIMAL(10,2) NOT NULL
  - dispensed_at: TIMESTAMP DEFAULT NOW()
  - notes: TEXT
```

---

## 6. WhatsApp Module Entities

```
Entity: WhatsAppContact
  - id: UUID (PK)
  - patient_id: UUID (FK → Patient) NULLABLE
  - phone_number: VARCHAR(20) UNIQUE NOT NULL  -- formato internacional
  - name: VARCHAR(255)
  - opted_in: BOOLEAN DEFAULT false  -- LGPD consent
  - opted_in_at: TIMESTAMP
  - last_message_at: TIMESTAMP
  - created_at: TIMESTAMP

Entity: Conversation
  - id: UUID (PK)
  - contact_id: UUID (FK → WhatsAppContact) NOT NULL
  - status: ENUM('active','waiting_input','completed','expired') DEFAULT 'active'
  - current_flow: VARCHAR(50)  -- 'scheduling', 'confirmation', 'general'
  - flow_state: JSONB  -- state machine data
  - started_at: TIMESTAMP DEFAULT NOW()
  - ended_at: TIMESTAMP

Entity: Message
  - id: UUID (PK)
  - conversation_id: UUID (FK → Conversation) NOT NULL
  - direction: ENUM('inbound','outbound') NOT NULL
  - content: TEXT NOT NULL
  - message_type: ENUM('text','image','document','audio','template') DEFAULT 'text'
  - whatsapp_message_id: VARCHAR(100)  -- ID from WhatsApp
  - status: ENUM('sent','delivered','read','failed') DEFAULT 'sent'
  - ai_processed: BOOLEAN DEFAULT false
  - created_at: TIMESTAMP DEFAULT NOW()
  INDEX: (conversation_id, created_at)

Entity: ScheduledReminder
  - id: UUID (PK)
  - appointment_id: UUID (FK → Appointment) NOT NULL
  - contact_id: UUID (FK → WhatsAppContact) NOT NULL
  - type: ENUM('24h_before','2h_before','post_visit') NOT NULL
  - scheduled_for: TIMESTAMP NOT NULL
  - sent: BOOLEAN DEFAULT false
  - sent_at: TIMESTAMP
  - response: ENUM('confirmed','rescheduled','cancelled','no_response') NULLABLE
  - created_at: TIMESTAMP
  INDEX: (scheduled_for, sent)
```

---

## 7. AI Module Entities

```
Entity: AIPromptTemplate
  - id: UUID (PK)
  - feature: VARCHAR(50) NOT NULL  -- 'tuss_coding', 'clinical_scribe', 'chatbot'
  - version: INTEGER NOT NULL
  - system_prompt: TEXT NOT NULL
  - user_prompt_template: TEXT NOT NULL  -- with {placeholders}
  - model: VARCHAR(50) DEFAULT 'claude-sonnet-4-20250514'
  - max_tokens: INTEGER DEFAULT 1000
  - temperature: DECIMAL(3,2) DEFAULT 0.1
  - is_active: BOOLEAN DEFAULT true
  - created_at: TIMESTAMP
  UNIQUE: (feature, version)

Entity: AIUsageLog
  - id: UUID (PK)
  - tenant_id: UUID NOT NULL  -- denormalized for cross-tenant reporting
  - user_id: UUID (FK → User) NOT NULL
  - feature: VARCHAR(50) NOT NULL
  - model: VARCHAR(50) NOT NULL
  - input_tokens: INTEGER NOT NULL
  - output_tokens: INTEGER NOT NULL
  - cost_usd: DECIMAL(8,6) NOT NULL
  - latency_ms: INTEGER
  - success: BOOLEAN DEFAULT true
  - error_message: TEXT
  - created_at: TIMESTAMP DEFAULT NOW()
  INDEX: (tenant_id, created_at), (feature, created_at)
  NOTE: Used for cost tracking and billing per tenant.

Entity: TUSSAISuggestion
  - id: UUID (PK)
  - input_text: TEXT NOT NULL  -- procedure description
  - suggestions: JSONB NOT NULL  -- [{code, term, confidence}]
  - accepted_code: VARCHAR(20)  -- which suggestion was accepted
  - user_id: UUID (FK → User) NOT NULL
  - created_at: TIMESTAMP
  NOTE: Used to improve suggestions over time and as cache.
  INDEX: (input_text hash for cache lookup)
```

---

## 8. Migration Strategy

- All migrations managed by Django's built-in migration system + django-tenants
- `python manage.py migrate_schemas` runs migrations across all tenant schemas
- New tenants get schema created with all current migrations applied
- Backward-compatible migrations only (no destructive changes without data migration)
- Migration naming convention: `XXXX_descriptive_name.py`
- All migrations tested in CI before deployment

---

*Next: [API_SPEC.md](./API_SPEC.md) | [SECURITY.md](./SECURITY.md)*
