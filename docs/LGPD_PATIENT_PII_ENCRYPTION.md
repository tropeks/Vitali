# LGPD — Patient PII & Clinical Free-Text Encryption at Rest

Until now only `cpf` (and the TOTP secret, insurance card number and AI scribe
transcription) were encrypted at rest. This change extends field-level
encryption to the most sensitive remaining patient PII and the clinical
narrative, using the **same** mechanism already in the codebase
(`django-encrypted-model-fields`, Fernet, keyed by `FIELD_ENCRYPTION_KEY`).

## Fields now encrypted

| Model | Fields | New type |
|-------|--------|----------|
| `emr.Patient` | `full_name`, `social_name`, `phone` | `EncryptedCharField` |
| `emr.Patient` | `email` | `EncryptedEmailField` |
| `emr.Patient` | `address` | `EncryptedJSONField` (new, `apps.core.fields`) |
| `emr.Patient` | `notes` | `EncryptedTextField` |
| `emr.MedicalHistory` | `notes` | `EncryptedTextField` |
| `emr.Encounter` | `chief_complaint` | `EncryptedTextField` |
| `emr.SOAPNote` | `subjective`, `objective`, `assessment`, `plan` | `EncryptedTextField` |
| `emr.ClinicalDocument` | `content` | `EncryptedTextField` |

`EncryptedJSONField` keeps `address` a native `dict` to every reader (serializers,
FHIR mapper) while storing an encrypted JSON blob in a `TEXT` column.

Migration: `emr/0016_encrypt_patient_pii.py` — changes the column types, drops the
`full_name`-based indexes, then re-saves existing rows so the plaintext is
re-written as ciphertext (same two-step pattern as `ai/0007`). Pre-existing
plaintext is read transparently (decrypt fails → value used as-is) until the data
step runs, so the migration is safe to apply to a populated database.

## Deliberately **not** encrypted (and why)

- **`Patient.whatsapp`** — the indexed routing/dedup key for the WhatsApp
  messaging subsystem (`has_whatsapp` filter, `WhatsAppContact` mapping,
  reminders). Encrypting it would break those equality/empty-string lookups.
  It is a phone number, so this is a conscious residual-risk decision; revisit
  if WA lookups move to a tokenised/blind-index column.
- **`Patient.insurance_data`** — has a GIN index and is queried by JSON path in
  billing/analytics; out of scope here.
- **`Patient.emergency_contact`**, **`Appointment.notes` / `cancellation_reason`**,
  **`Prescription.notes`**, **`PrescriptionItem` text** — out of scope for this
  pass; candidates for a follow-up.

## Breakage from encryption (and how it was handled)

Encrypted columns hold opaque, **non-deterministic** ciphertext, so they cannot
be indexed, ordered, or matched with SQL (`=`, `LIKE`/`icontains`, JSON path).
Every site that did so on a now-encrypted field:

| Site | Before | After |
|------|--------|-------|
| `emr/models.py` `Patient.Meta` | `ordering=["full_name"]`, indexes on `full_name` & `(is_active, full_name)`, `db_index` on `full_name` | ordering `["medical_record_number"]`; those indexes dropped; new `(is_active, medical_record_number)` index |
| `emr/filters.py` `PatientFilter.name` | `CharFilter(lookup_expr="icontains")` on `full_name` | method filter — decrypts and matches in Python |
| `emr/views.py` `PatientViewSet` | DRF `SearchFilter` with `search_fields=[full_name, social_name, …]`; `ordering_fields`/`ordering` include `full_name` | custom `PatientSearchFilter` (SQL for mrn/whatsapp + Python for names); `full_name` removed from ordering |
| `emr/admin.py` `PatientAdmin` | `search_fields` includes `full_name` | `full_name` removed (admin search is SQL-only) |

### Behavioural notes / accepted trade-offs

- **Name search still works** via `PatientSearchFilter` / `PatientFilter.name`,
  but it decrypts the active patient set in memory — `O(n)`. Fine at clinic
  scale; if the table grows large, add a deterministic blind-index column.
- **Alphabetical-by-name ordering at the DB layer is gone.** The default list
  order is now the sequential `medical_record_number`. Client-side/page-level
  alphabetical sorting can be layered on top if needed.
- **Django admin name search** no longer works (admin search is SQL-only);
  search by MRN or WhatsApp instead.
- No production queryset filters `Patient` by `full_name`/`email`/`phone`/
  `address` outside the sites above (`Patient.objects` is only used by
  `generate_mrn`, which filters on `medical_record_number`).
