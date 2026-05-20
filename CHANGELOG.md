# Changelog

All notable changes to Vitali Health are documented here.

## [Unreleased]

### Added

- **Phase 3 — Mobile backend primitive (`apps.mobile`, 2026-05-20):**
  the part of the documented "Mobile app (React Native)" item that is
  shippable as a complete backend primitive — device registration + push
  dispatch + audit trail. The React-Native client and the FCM/APNS
  adapter wiring are deploy-time follow-ups; this layer is the swap-in
  point.
  - `apps/mobile/models.py:MobileDevice` — one row per `(user, device_id)`
    install. Carries platform (ios / android / web), `push_token`,
    `app_version`, `os_version`, `enrolled_at`, `last_seen_at`,
    `is_active`. Unique constraint on `(user, device_id)` means re-register
    from the same client is idempotent.
  - `apps/mobile/models.py:PushDelivery` — append-only audit log of every
    push attempt. Records device + user + title/body/data + status
    (`sent` / `failed` / `no_provider`) + provider message id / error.
    Even when no FCM/APNS adapter is wired, the row is still written
    with `status=no_provider` so ops has full visibility.
  - `apps/mobile/services/push.py:MobilePushService` — module-level
    singleton dispatcher with a `PushAdapter` `Protocol` plugin point.
    Default is `_NoProviderAdapter` (logs only). At app startup an
    integrator calls `MobilePushService.set_adapter(FirebaseAdapter())`
    and the REST surface starts delivering real pushes — no code change
    in the views or tests.
  - Self surface (authenticated, module-gated, no extra perm):
    - `GET / POST /api/v1/mobile/devices/me/` — list / idempotent register.
    - `DELETE /api/v1/mobile/devices/me/{id}/` — soft-disable (sets
      `is_active=False`).
    Cross-user device access on these endpoints returns 404.
  - Admin surface (gated by `mobile.admin` permission):
    - `GET /api/v1/mobile/devices/?user=…&platform=…&active=…`
    - `POST /api/v1/mobile/push/` — fan a push out to every active
      device a user has registered.
    - `GET /api/v1/mobile/push/audit/?user=…&status=…` — recent
      `PushDelivery` rows.
  - Module key `mobile` added to `ALLOWED_MODULE_KEYS` (default OFF).
    `mobile.admin` permission seeded into `ADMIN_PERMISSIONS`.
  - 18 tests: 9 self-surface (register / idempotent / list isolation /
    delete soft-disable / cross-user 404 / module gate / auth /
    invalid platform 400) + 9 admin + push (admin list / filters / perm
    gate / no-provider / success adapter / failing adapter / inactive
    skipped / unknown user 404 / audit / admin-only).
  - Verified: 848/848 backend tests pass · mypy clean · ruff clean ·
    format clean.
- **Phase 3 — Triagem Inteligente FSM primitive (`apps.triage`,
  2026-05-20):** backend half of the documented "Triagem Inteligente
  (WhatsApp)" item. Ships the FSM + clinical rules + audit trail; the
  WhatsApp message-routing integration plugs into this primitive's
  `answer()` calls at deploy time, same pattern as DICOM/Orthanc and
  WebRTC above `TelemedicineSession`.
  - `apps/triage/services/question_bank.py` — 6-question Manchester /
    START-inspired red-flag bank (chest pain, breathing difficulty,
    severe bleeding, altered consciousness, severe pain, recent trauma)
    + chief-complaint keyword sets for emergency (infarto / AVC /
    convulsão / etc.) and urgent (febre alta / vômito / dor abdominal /
    etc.). The bank lives in code: clinical questions need versioning
    and review, not a free-form admin UI.
  - `apps/triage/services/evaluator.py:evaluate` — deterministic
    `routine | urgent | emergency` classifier with explicit precedence:
    emergency keywords → emergency; ≥2 red flags or critical single
    (sangramento intenso / consciência alterada) → emergency; urgent
    keyword or single red flag → urgent; otherwise routine. Returns a
    `TriageDecision` carrying rationale + matched_keywords + counts so
    every classification is auditable.
  - `apps/triage/models.py:TriageSession` — state machine
    `started → answering → evaluated → completed | escalated | cancelled`;
    `evaluate_now()` auto-escalates emergencies (records `escalated_at`
    so CFM Res. 2.314/2022 §6 escalation requirement is preserved).
    Re-evaluation / answers from terminal states return 409.
  - REST: 8 endpoints under `/api/v1/triage/` — `GET /questions/`
    (bank), `GET/POST /sessions/`, `GET /sessions/{id}/`, `PATCH /
    sessions/{id}/complaint/`, `POST /sessions/{id}/{answer,evaluate,
    complete,cancel}/`.
  - Module key `triage` (default OFF). Permissions `triage.read` +
    `triage.respond` seeded into admin / médico-dentista / enfermeiro
    (read only) / recepção default roles.
  - 25 tests: 8 evaluator unit + 17 FSM/endpoint integration
    (question bank / create / complaint PATCH / answer / unknown-key
    400 / evaluate-before-all 409 / routine path / emergency
    auto-escalation / double-evaluate 409 / complete-after-eval /
    cancel-from-started / complete-before 409 / list filter by urgency
    / role + module + auth gates / terminal-state-rejects-answer).
  - Verified: 830/830 backend tests pass · mypy clean · ruff clean ·
    format clean.
- **Phase 3 — Smart Scheduling rule-based slot ranker
  (`apps.smart_scheduling`, 2026-05-20):** explainable baseline before an
  ML model. Closes the Phase 3 "Smart Scheduling (AI-optimized)" item at
  the *primitive* layer — a future iteration can swap the scoring
  function behind the same REST shape with a learned model when piloto
  data is available.
  - `apps/smart_scheduling/services/ranker.py:suggest_slots` enumerates
    a professional's open slots in the [from_date, to_date] window from
    `ScheduleConfig`, excludes slots already taken in `Appointment`, and
    scores each candidate against three explicit signals:
    - `clinical_time`: hour-of-day score (10am peak, lunch dip, 15-16
      secondary peak) anchored on common Brazilian primary-care
      attendance curves.
    - `gap_fill`: rewards slots adjacent to an existing appointment on
      the same day so the schedule clusters instead of fragmenting.
    - `patient_history`: when a Patient is supplied, boosts hours-of-day
      the patient has previously attended (computed in the platform's
      local timezone — DB stores UTC, so an explicit `.astimezone()` is
      required before reading `.hour`).
    All three signals normalised to [0, 1] and combined via weighted sum
    (`DEFAULT_WEIGHTS` tunable). Determinism is the invariant — same
    `(patient, professional, slot)` → same score, no randomness.
  - REST:
    `GET /api/v1/scheduling/suggest/?professional=…&patient=…&from=…&to=…&limit=…`.
    Window capped at 60 days so response time is predictable. Each
    suggestion carries the raw score *and* per-signal components so the
    UI can explain why a slot ranks where it does.
  - Module key `smart_scheduling` (default OFF). Permission
    `smart_scheduling.read` seeded into admin / médico/dentista /
    enfermeiro / recepção default roles — receptionists are the primary
    user of the suggestion flow.
  - 16 tests: 7 service unit (zero-config / 16-slot enumeration / lunch
    skip / 10am peak win / taken-slot excluded / patient-history boost /
    invalid window + limit) + 9 endpoint integration (sorted ranking /
    missing-prof 400 / unknown-prof 404 / inverted window 400 /
    too-wide 400 / unknown-patient 404 / module + permission + auth
    gates).
  - Verified: 805/805 backend tests pass · mypy clean · ruff clean ·
    format clean.
- **Phase 3 — AI Farmácia demand-forecast primitive (`apps.pharmacy_ai`,
  2026-05-20):** baseline rolling-window forecast over the existing
  `StockMovement` ledger. No ML model yet (clinics need to accumulate
  dispensation history first); the arithmetic baseline ships now so a
  smarter implementation can swap in without breaking the REST contract.
  - `apps/pharmacy_ai/services/forecast.py:forecast_for_drug` — for a
    given Drug, sums `dispense`-type StockMovements over a configurable
    window (`window_days`, default 30), computes `avg_daily_consumption`,
    pulls `current_stock` from `StockItem`, and emits
    `projected_days_of_supply` + `recommended_reorder_quantity`
    (`max(0, target_days × avg_daily − current_stock)`).
  - REST: `GET /api/v1/pharmacy/forecast/?drug=<id>&window_days=30&target_days=60`
    returns a `DemandForecast` payload. 400 on missing / non-integer /
    non-positive params; 404 on unknown drug.
  - Module key `pharmacy_ai` added to `ALLOWED_MODULE_KEYS` (default OFF).
    Permission `pharmacy_ai.read` seeded into `ADMIN_PERMISSIONS`,
    `CLINICAL_PRESCRIBER_PERMISSIONS`, and `PHARMACY_PERMISSIONS`.
  - 14 tests: 5 service unit (no-history zero / uniform consumption /
    out-of-window ignored / over-target zero-reorder / invalid params)
    + 9 endpoint integration (payload shape / custom window+target /
    missing-drug 400 / non-integer 400 / non-positive 400 / unknown-drug
    404 / module gate / permission gate / auth gate).
  - Scope: rule-based baseline. A future iteration with seasonality-aware
    ML model can swap the implementation behind the same REST shape
    without breaking callers.
  - Verified: 789/789 backend tests pass · mypy clean · ruff clean · format
    clean.
- **Phase 3 — Multi-country i18n infrastructure (2026-05-20):** Django
  i18n turned on with a 4-language vocabulary (pt-BR / pt-PT / es / en),
  per-user language preference, and an explicit `PreferredLanguageMiddleware`
  that activates the user's choice on every authenticated request — the
  groundwork for the documented multi-country compliance (start with
  Portugal / Angola).
  - `vitali/settings/base.py` — `LANGUAGES` advertises the 4 supported
    locales, `LOCALE_PATHS = [BASE_DIR / "locale"]` points at the four
    `locale/<code>/LC_MESSAGES/` stub directories (translations land here
    iteratively).
  - `django.middleware.locale.LocaleMiddleware` added to `MIDDLEWARE`
    immediately after `AuthenticationMiddleware`, so URL prefix /
    `Accept-Language` resolution happens before our custom layer.
  - New `apps.core.middleware.PreferredLanguageMiddleware` —
    authenticated requests get the user's saved `preferred_language`
    activated for the duration of the request, then deactivated on
    response (no global leak across requests).
  - New `preferred_language` field on `core.User` (migration
    `core/0014_user_preferred_language.py`). Empty string means "fall
    back to platform default + `Accept-Language`".
  - REST: `GET / PATCH /api/v1/users/me/language/` — returns the user's
    current pick plus the platform's supported list / default. PATCH
    validates against `LANGUAGES`; unknown codes return 400 with the
    allowed set surfaced for clients.
  - 11 tests: settings shape (3) + endpoint round-trip + 400 on unknown
    code + empty-string resets + auth gate (5) + middleware unit tests
    (activate / no-pref passthrough / anonymous passthrough — 3).
  - Verified: 775/775 backend tests pass · mypy clean · ruff clean · format
    clean.
- **Phase 3 — Patient Portal backend primitive (`apps.patient_portal`,
  2026-05-20):** the backend half of Portal do Paciente. The patient-facing
  Next.js app is a separate parallel project; this layer is sufficient for
  integrators building their own patient app today.
  - `apps/patient_portal/models.py:PatientPortalAccess` — OneToOne link
    between a `core.User` account and an EMR `Patient`. State machine
    `invited → active | revoked`. `secrets.token_urlsafe(32)` invite
    token, 7-day default expiry, `activate()` / `revoke()` / `touch()`
    methods. Audit timestamps: `invited_at`, `activated_at`, `revoked_at`,
    `last_seen_at`.
  - **Admin surface** (gated by `users.read` / `users.write`):
    - `GET/POST /api/v1/portal/access/` — mint + list invites.
    - `POST /api/v1/portal/access/activate/` — patient consumes their
      token (verifies the token belongs to the requesting user, refuses
      cross-account use, refuses expired tokens).
    - `GET /api/v1/portal/access/{id}/`
    - `POST /api/v1/portal/access/{id}/revoke/`
  - **Self-data surface** (`/api/v1/portal/me/...`, gated by the new
    `IsPortalSelfAccess` permission — requires `portal.self_access`
    permission AND an `active` PatientPortalAccess row):
    - `GET /portal/me/`             — own Patient profile
    - `GET /portal/me/appointments/` — own Appointments
    - `GET /portal/me/encounters/`  — own Encounters (signed only)
    - `GET /portal/me/prescriptions/` — own Prescriptions (signed +
      partially_dispensed + dispensed)
    - `GET /portal/me/allergies/`   — own Allergies
    Every self-data request calls `access.touch()` so `last_seen_at`
    stays current.
  - Module key `patient_portal` (default OFF) in `ALLOWED_MODULE_KEYS`.
  - 18 integration tests: admin create / list-filter / revoke / perm gate;
    activate consume / cross-user 403 / expired 409 / invalid token 400;
    self-data /me + /me/appointments (cross-tenant isolation) +
    /me/encounters (only signed) + /me/allergies (cross-tenant isolation);
    self-access blocked for invited / revoked / no-permission users;
    module + auth gates.
  - Verified: 764/764 backend tests pass · mypy clean · ruff clean ·
    format clean.
- **Phase 3 — Telemedicine session tracking primitive (`apps.telemedicine`,
  2026-05-20):** the *session lifecycle* layer of the telemedicina epic.
  WebRTC infra, video recording, and per-tenant SFU are deploy-time
  concerns; the tracking primitive shipped here closes the CFM Res.
  2.314/2022 §3 audit requirement (start / end of every telemedicine
  session must be logged) and gives the eventual WebRTC layer a stable
  `room_uid` to route by.
  - `apps/telemedicine/models.py:TelemedicineSession` — state machine
    `scheduled → in_progress → completed | cancelled` enforced by
    `ALLOWED_TRANSITIONS` + `start() / complete() / cancel()` methods
    (which compute `duration_seconds` automatically and refuse
    transitions out of terminal states). Carries optional Appointment
    FK, Patient + Professional FKs, an auto-minted unique `room_uid`,
    `scheduled_for`/`started_at`/`ended_at`, `recording_url`, and notes.
  - REST: `GET/POST /telemedicine/sessions/`,
    `GET /telemedicine/sessions/{id}/`,
    `POST /telemedicine/sessions/{id}/start/`,
    `POST /telemedicine/sessions/{id}/complete/`,
    `POST /telemedicine/sessions/{id}/cancel/`,
    `PATCH /telemedicine/sessions/{id}/recording/`. State transitions
    are explicit POSTs (not PATCH on status) so each lifecycle event
    writes its own audit-attributable request.
  - Module key `telemedicine` (default OFF). Permissions
    `telemedicine.read` + `telemedicine.host` seeded into
    `ADMIN_PERMISSIONS` and `CLINICAL_PRESCRIBER_PERMISSIONS`.
  - 16 integration tests covering create / list-with-filters / detail
    404 / start-from-scheduled / complete-with-duration / cancel from
    scheduled or in-progress / terminal-state-rejection-409 /
    recording-URL patch + invalid-URL 400 / host-permission gate /
    reader-can-list / module + auth gates.
  - Verified: 746/746 backend tests pass · mypy clean · ruff clean ·
    format clean.
- **Phase 2 — DICOM Study tracking primitive (`apps.imaging`, 2026-05-20):**
  the tracking half of E-012 (DICOM/PACS). Clinics that already operate an
  Orthanc / PACS gateway can now register studies through Vitali's REST,
  and clinics without a PACS deployment can still keep a structured
  reference to imaging studies cited in their referrals + reports.
  - `apps/imaging/models.py:DicomStudy` — tenant-scoped, keyed by the
    DICOM `study_instance_uid` (unique). Carries Patient FK, optional
    Encounter FK, accession_number (DICOM tag 0008,0050), modality
    (CR/CT/DX/MG/MR/NM/OT/PT/RF/US/XA), body_part_examined, description,
    study_date, number_of_series, number_of_instances, and a nullable
    `orthanc_study_id` populated once the PACS layer ingests the study.
    `has_pixel_data` property returns True once that field is set.
    Two indexes (`img_pat_date_idx`, `img_mod_date_idx`).
  - REST: `GET /api/v1/imaging/studies/?patient=…&modality=…&encounter=…&_count=…`,
    `POST /api/v1/imaging/studies/`, `GET /api/v1/imaging/studies/{id}/`,
    `PATCH /api/v1/imaging/studies/{id}/orthanc/` (backfill the Orthanc UID
    + series/instance counts once the PACS confirms ingestion).
  - Module key `imaging` added to `ALLOWED_MODULE_KEYS` (default OFF).
    Permissions `imaging.read` + `imaging.write` seeded into
    `ADMIN_PERMISSIONS` and `CLINICAL_PRESCRIBER_PERMISSIONS`.
  - 13 integration tests covering list / patient + modality + encounter
    filtering, detail, create + duplicate-uid rejection, Orthanc backfill
    + permission gate, module + auth gates.
  - Scope: the *tracking* layer. The OHIF Viewer frontend integration and
    the Orthanc HTTP client (webhook handler + REST poller) are deploy-time
    concerns that plug into `orthanc_study_id`; documented as follow-up in
    `EPICS_AND_ROADMAP.md` §6.
  - Verified: 730/730 backend tests pass · mypy clean · ruff clean · format
    clean.
- **Phase 3 — FHIR R4 ServiceRequest resource (`apps.fhir`, 2026-05-20):**
  completes the FHIR interop primitive — **8 of 8 documented resources**
  (`EPICS_AND_ROADMAP.md` §6 Phase 3 FHIR scope closed).
  - `apps/fhir/services/service_request_mapper.py` — maps
    `apps.emr.ClinicalDocument` rows of types `referral` and `exam_request`
    to FHIR ServiceRequest. Category uses SNOMED codes (306206005 / Referral
    to service, 108252007 / Laboratory procedure). Status derives from the
    signature: unsigned → `draft`, signed → `active`. Other ClinicalDocument
    types (`certificate`, `prescription`, `report`) are deliberately NOT
    exposed here — they belong to different FHIR resource types
    (DocumentReference, DiagnosticReport, …) in a future expansion.
  - Endpoints (2 new):
    - `GET /api/v1/fhir/ServiceRequest/{id}/` (404 when underlying
      ClinicalDocument is not a referral / exam_request)
    - `GET /api/v1/fhir/ServiceRequest/?patient=…&status=…&category=…&_count=…`
  - Capability Statement updated — now advertises **8 resources** end-to-end.
  - 26 tests: 13 mapper unit + 13 view integration (capability listing,
    read, certificate-not-found 404, search by patient / status / category,
    unknown-status / unknown-category empty bundles, module gate).
  - Verified: 717/717 backend tests pass · mypy clean · ruff clean · format
    clean.
- **Phase 3 — FHIR R4 Observation + Condition resources (`apps.fhir`,
  2026-05-20):** two more resources, taking the FHIR primitive from 5 to 7
  of 8 documented resources.
  - `apps/fhir/services/observation_mapper.py` — splits one
    `apps.emr.VitalSigns` row into N FHIR Observation resources (one per
    vital), each with a stable LOINC code (29463-7 / weight, 8302-2 /
    height, 8480-6 / systolic BP, 8462-4 / diastolic BP, 8867-4 / heart
    rate, 8310-5 / body temp, 59408-5 / SpO₂, 39156-5 / BMI derived from
    weight+height). UCUM unit codes carried in `valueQuantity`. Resource
    id format is `<encounter-uuid>_<loinc>` (underscore separator —
    UUIDs and LOINC codes both use `-`, so an underscore keeps the parser
    unambiguous).
  - `apps/fhir/services/condition_mapper.py` — maps `apps.emr.MedicalHistory`
    to FHIR Condition with CID-10 / ICD-10 system URI on the coding,
    clinicalStatus (active / resolved; "controlled" rolls into active with
    a note carrying the original Vitali state), verificationStatus =
    confirmed, category derived from the Vitali type (chronic/acute →
    problem-list-item, surgical/family → encounter-diagnosis with a
    "Family history" text discriminator).
  - Endpoints (4 new):
    - `GET /api/v1/fhir/Observation/<encounter-uuid>_<loinc>/`
    - `GET /api/v1/fhir/Observation/?patient=…&encounter=…&code=…&_count=…`
    - `GET /api/v1/fhir/Condition/{id}/`
    - `GET /api/v1/fhir/Condition/?patient=…&clinical-status=…&category=…&_count=…`
  - Capability Statement updated to advertise both (7 resources total).
  - 36 tests: 11 observation mapper + 12 condition mapper + 13 view
    integration (capability listing, read by composite LOINC id, search by
    patient / encounter / code / clinical-status / category, module gate).
  - Verified: 691/691 backend tests pass · mypy clean · ruff clean · format
    clean.
- **Phase 3 — FHIR R4 AllergyIntolerance + MedicationRequest resources
  (`apps.fhir`, 2026-05-20):** two more resources on the interop layer,
  taking the FHIR primitive from 3 to 5 of 8 documented resources.
  - `apps/fhir/services/allergy_mapper.py:allergy_to_fhir` — maps
    `apps.emr.Allergy` to FHIR AllergyIntolerance with criticality derived
    from severity (`mild` → `low`; `moderate`/`severe`/`life_threatening`
    → `high`), clinicalStatus (active/inactive/resolved), verificationStatus
    (confirmed when `confirmed_by` present), substance in `code.text`,
    patient reference, recordedDate, and a reaction sub-element when the
    free-text `reaction` is populated.
  - `apps/fhir/services/medication_request_mapper.py` — maps the Vitali
    Prescription → N FHIR MedicationRequest resources (one per
    `PrescriptionItem`, per FHIR spec). Carries `groupIdentifier`
    (`urn:vitali:prescription`) so clients can group items by their parent
    prescription. `status` translated to FHIR valueset (`signed` /
    `partially_dispensed` → `active`; `dispensed` → `completed`; `draft` /
    `cancelled` passthrough). Emits `medicationCodeableConcept` from the
    item's `generic_name` (falls back to the catalogued Drug),
    `dosageInstruction` with quantity + unit + free-text directions, and
    references to Patient / Practitioner / Encounter.
  - Endpoints (4 new):
    - `GET /api/v1/fhir/AllergyIntolerance/{id}/`
    - `GET /api/v1/fhir/AllergyIntolerance/?patient=…&clinical-status=…&_count=…`
    - `GET /api/v1/fhir/MedicationRequest/{id}/`
    - `GET /api/v1/fhir/MedicationRequest/?patient=…&status=…&_count=…`
  - Capability Statement updated to advertise both resources (5 total now).
  - 37 tests: 12 allergy mapper + 13 medication-request mapper + 12 view
    integration (capability, read, search by patient / clinical-status /
    status, unknown-status empty, group identifier carry-through, module
    gate).
  - Verified: 655/655 backend tests pass · mypy clean · ruff clean · format
    clean.
- **Phase 3 — FHIR R4 Practitioner resource (`apps.fhir`, 2026-05-20):**
  third resource on the interoperability layer. Closes the dangling
  `Practitioner/<id>` references the Encounter resource already emits — FHIR
  clients can now follow those references to a real resource.
  - `apps/fhir/services/practitioner_mapper.py:professional_to_fhir` —
    emits Practitioner with one identifier per council registry
    (`urn:vitali:council/{crm,cro,coren,…}` + state as assigner; CRM uses
    the v2-0203 `MD` type code, other councils use `LN`), name split from
    the linked User, email telecom, qualification entries for both the
    council itself and CBO code (Brazilian Classificação Brasileira de
    Ocupações system), and an `active` flag from `Professional.is_active`.
  - Endpoints: `GET /api/v1/fhir/Practitioner/{id}/` (read),
    `GET /api/v1/fhir/Practitioner/?identifier=…|…&name=…&active=…&_count=…`
    (search returning a searchset Bundle).
  - Capability Statement updated to advertise Practitioner (read +
    search-type with `identifier`, `name`, and `active` search params).
  - 20 tests: 10 mapper unit tests (council identifier system URI, name
    split, CBO qualification, fallback to specialty free-text, missing
    fields drop optional output) + 10 view integration tests (capability
    listing, read, search by council token / bare council number / name /
    active boolean, module + permission gates).
  - Verified: 618/618 backend tests pass · mypy clean · ruff clean · format
    clean.
- **Phase 3 — FHIR R4 Encounter resource (`apps.fhir`, 2026-05-20):** second
  resource on the interoperability layer, follows the Patient pattern (pure
  stateless transform over `apps.emr.Encounter`).
  - `apps/fhir/services/encounter_mapper.py:encounter_to_fhir` — emits
    Encounter with status mapped to FHIR valueset (`open` → `in-progress`,
    `signed` → `finished`, `cancelled` → `cancelled`), ambulatory `class`
    code (AMB / v3-ActCode), `subject` → `Patient/<uuid>`,
    `participant.individual` → `Practitioner/<uuid>` with PPRF
    (primary-performer) participation, period (start = `encounter_date`,
    end = `signed_at` when signed), and `reasonCode.text` populated from
    the chief complaint.
  - Endpoints: `GET /api/v1/fhir/Encounter/{id}/` (read),
    `GET /api/v1/fhir/Encounter/?subject=Patient/{id}&status=…&_count=…`
    (search returning a searchset Bundle). `patient` is supported as an
    alias of `subject` per FHIR. `status` accepts the FHIR codes and is
    translated back to the internal lifecycle.
  - Capability Statement updated to advertise Encounter (read + search-type
    with `subject` and `status` search params).
  - 22 tests: 11 mapper unit tests (status mapping, class, subject &
    participant refs, period, reason code, empty-state behaviour,
    `base_url` prefix) + 11 view integration tests (capability listing,
    read, search by `subject` / `patient` / `status`, unknown status,
    permission / module / 404 gates).
  - Verified: 598/598 backend tests pass · mypy clean · ruff clean · format
    clean.
- **Phase 3 — FHIR R4 Patient resource (`apps.fhir`, 2026-05-20):** first
  bite of the interoperability layer from `EPICS_AND_ROADMAP.md` §6 Phase 3.
  Stateless surface over existing tenant data — no new models — so the
  module ships in one vertical slice and can grow resource-by-resource
  without further migrations. Endpoints:
  - `GET /api/v1/fhir/metadata` (public Capability Statement, FHIR R4 §3.2).
  - `GET /api/v1/fhir/Patient/{id}/` — single-resource read.
  - `GET /api/v1/fhir/Patient/?identifier=…|…&name=…&_count=…` — searchset
    `Bundle`, supports the canonical `identifier` (MRN + CPF, BR-Core OID)
    and `name` search params. `_count` capped at 100.
  - `apps/fhir/services/patient_mapper.py:patient_to_fhir` — pure transform
    that emits FHIR R4 Patient with identifiers (MRN + national CPF
    coding), official + usual names, telecom (phone/mobile/email), gender,
    birthDate, and structured address with `country: BR`.
  - Gated by FeatureFlag `fhir` (default OFF) + per-user `fhir.read`
    permission (seeded into `ADMIN_PERMISSIONS` and
    `CLINICAL_PRESCRIBER_PERMISSIONS`).
  - 22 tests: 10 mapper unit tests (gender mapping, identifier system URIs,
    name splitting, social-name fallback, telecom, address, empty-address
    omission) + 12 view integration tests (capability statement public,
    read + search by MRN / CPF / name, module + permission + auth gates,
    `_count` cap).
  - Scope: Patient + Capability Statement only. Observation, Encounter,
    MedicationRequest, Practitioner are follow-up resources that plug into
    the same pattern.
  - Verified: 576/576 backend tests pass · mypy clean · ruff clean · format
    clean.
- **Phase 2 — ICP-Brasil digital signature primitive (`apps.signatures`,
  2026-05-20):** the first Phase 2 item from `EPICS_AND_ROADMAP.md` §6 lands
  as a complete, tenant-scoped vertical. Implements the cryptographic core of
  MP 2.200-2/2001 (ICP-Brasil) + CFM Res. 2.299/2021 (paperless clinical
  records) — load A1 PKCS#12, SHA-256 + RSA-PKCS#1v15 sign (the AD-RB profile
  in DOC-ICP-15.03), verify against the embedded cert. New module:
  - `apps/signatures/models.py:DigitalSignature` — append-only record bound
    to a `document_hash_hex` + cert metadata + signer; polymorphic
    `document_type` × `document_id` reference (encounter, prescription,
    custom). Two indexes (`sig_doc_idx`, `sig_signer_idx`).
  - `apps/signatures/services/icp_brasil.py:ICPBrasilSigner` — stateless
    primitive with `load_pkcs12 / compute_hash / sign / verify /
    is_icp_brasil`. Returns a `SignatureResult` dataclass that maps 1-1 to
    the storage layer.
  - REST: `POST /api/v1/signatures/sign/` (write — gated by
    `signatures.sign` + module `signatures`), `GET /api/v1/signatures/`
    (read — filterable by `document_type` + `document_id`, gated by
    `signatures.read`). Bundle accepted as base64 in the body so the key
    payload never touches multipart or query-string logging surfaces.
  - New module key `"signatures"` in `apps.core.constants:ALLOWED_MODULE_KEYS`
    + default-OFF tenant FeatureFlag. `signatures.read` /
    `signatures.sign` permissions seeded into `admin` and
    `medico` / `dentista` default roles (`CLINICAL_PRESCRIBER_PERMISSIONS`).
  - Admin: read-only `DigitalSignatureAdmin` (add/change/delete disabled —
    signatures are produced by the API, not via admin).
  - Tests: 8 unit tests for the cryptographic primitive (PKCS#12 parse, sign
    + verify roundtrip, tampered-document detection, wrong-password
    rejection, no-password bundle, ICP-Brasil issuer detection, well-known
    SHA-256 baseline) + 9 integration tests for the REST surface
    (module/permission/auth gates, validation, list filtering). Uses
    ephemeral self-signed RSA-2048 PKCS#12 — no real ICP-Brasil cert needed
    in CI.
  - Scope deliberately at the primitive layer. Full chain-of-trust
    validation against the ICP-Brasil DOC-ICP-04 trust store, A3 hardware
    tokens (PKCS#11), and end-to-end integration into the encounter /
    prescription sign flows are follow-up work — but the primitive is
    complete: sign + verify + store are all wired and tested.
  - Verified: 554/554 backend tests pass · mypy clean · ruff clean · format
    clean.
- **`docs/TODOS.md` Lower-Priority closed — ClaudeGateway client pooling
  (2026-05-20):** the underlying `anthropic.Anthropic` client is now cached
  at module level keyed by `(api_key, timeout)`. The hot path
  (`predict_glosa`, `suggest_tuss_codes`, scribe transcription) used to
  rebuild the HTTP connection pool on every gateway instantiation; concurrent
  scribe sessions saw measurable overhead at >10 sessions. Now: one shared
  client per credential pair. `reset_anthropic_client_cache()` exported for
  tests. Backend regression coverage in `apps/ai/tests/test_gateway.py`.
- **P3 closed — Batch Glosa Prediction Endpoint
  (`POST /api/v1/ai/glosa-predict-batch/`, 2026-05-20):** wraps the per-row
  predictor so a multi-item TISS guide is one round-trip instead of N
  parallel fires. Accepts a shared `insurer_ans_code` + `insurer_name` +
  `guide_type` and a list of `items` (each `{tuss_code, cid10_codes}`),
  capped at 50 items per batch. Same fail-open contract as the per-row
  endpoint: `degraded_overall=True` when any item degrades or when the
  global `FEATURE_AI_GLOSA` / per-tenant `ai_glosa_prediction_enabled` gate
  is off. Closes [TODOS.md](./TODOS.md) P3 — Batch Glosa Prediction Endpoint.
  Backend regression tests in
  `apps/ai/tests/test_views_glosa.py::GlosaPredictBatchViewTest`.

### Changed

- **`DESIGN.md` v2.0 contract enforced system-wide (2026-05-20):** R0–R5
  reconciled the canonical surfaces; this sweep closes every remaining
  absolute-rule violation on every other dashboard page and shared
  component. After the pass, the audit counters are all zero across
  `frontend/app/(dashboard)/` and `frontend/components/`:
  - `rounded-xl` — retired everywhere (§7 + §12). 29 files swept to
    `rounded-lg`.
  - `shadow-sm` on static cards — retired (§7 "Static cards […] are flat";
    §12 Don'ts). Surgically removed only where the same className already
    carries `rounded-lg` + `border` (the card-chrome signature); kept on
    legitimately floating surfaces (segmented-control active state, modals
    use `shadow-2xl`). 8 files swept.
  - `gray-*` palette — retired (§3 "Use `slate-*` for text, bg, and
    borders"). Mechanical `gray-N` → `slate-N` substitution; 460+ class
    occurrences across the dashboard. Tailwind's slate scale is the cooler
    cousin of gray — visual impact is minimal but consistency is now
    enforced.
  - `<h1>`/`<h2>` titles on `font-bold` — retired (§6 + §12 "v1's
    `font-bold` and the `<h2>` workbench titles are retired"). Targeted
    `<h1>`/`<h2>` regex; 9 files swept. `font-bold` on non-title elements
    (badges, etc.) untouched.
  - `<h1 text-xl>` page titles — retired in favour of `text-2xl` (§6).
    Last remaining instance is the clinical-workspace patient bar header
    (`encounters/[id]`), which is a Tasy-idiom still pending codification
    per `docs/PLAN_UI_UX_RECONCILIATION.md`.

  Verified green after every sweep: `tsc --noEmit`, `eslint
  --max-warnings=0`, 17/17 vitest files (74/74 tests).
- **R5 UI reconciliation — Admin / AI / WhatsApp / HR / Platform / Profile (2026-05-20):**
  Closes the last `planned` block in
  [`docs/PLAN_UI_UX_RECONCILIATION.md`](./docs/PLAN_UI_UX_RECONCILIATION.md).
  Seven settings/admin surfaces (`/configuracoes/ai`, `/configuracoes/assinatura`,
  `/configuracoes/whatsapp`, `/configuracoes/profissionais`, `/rh/funcionarios`,
  `/platform/monitor`, `/profile/security`) now run on the shared
  `PageShell` / `StatusBadge` / `KpiTile` / `SectionState` primitives.
  `<h1>` titles unified at `text-2xl font-semibold`, retired `rounded-xl` and
  `shadow-sm`-on-static-cards, and removed every inline status→colour ternary.
- **`lib/operational-ui.ts` extended with R5 vocabulary:** new
  `SUBSCRIPTION_STATUS_META`, `EMPLOYMENT_STATUS_META`,
  `WA_CONNECTION_STATUS_META` enum maps, plus derived-boolean adapters
  `getActivenessMeta`, `getDpaStatusMeta`, `getMfaStatusMeta`, `getOptInMeta`.
  The cadastro ativo/inativo pill (`ProfessionalRow`) now resolves through
  the canonical adapter — colour and label live in one place.
- **`/platform/monitor` KPIs** switched from a local `KpiCard` to the shared
  `<KpiTile>`, retiring the unused sparkline scaffolding.
- **`DESIGN.md` `v2.0` contract now covers every dashboard surface** — there
  are no remaining screens that declare status colours, page shells, or KPI
  tiles outside the shared primitives.

### Verified

- `tsc --noEmit` clean.
- `eslint . --max-warnings=0` clean.
- `vitest run` — 17/17 files, 74/74 tests (added two covering the new R5
  vocabulary in `operational-ui.test.ts`).

## [1.0.0] — 2026-04-22

### Added
- **Clinical AI Layer + MFA (Sprint 15, S-062–S-066):** First Phase 2 release. AI becomes a clinical co-pilot — prescription safety checks, CID-10 suggestions, SOAP transcription — and MFA protects staff accounts for the live pilot. Version bump to v1.0.0 marks the first production-grade release.
  - **S-062 Multi-Factor Authentication (TOTP):** `django-otp`, `pyotp`, `qrcode[pil]` added. `TOTPDevice` migration (`core/0010_totpdevice.py`). `MFARequiredMiddleware` enforces `mfa_verified` JWT claim on staff/superuser requests. Endpoints: `POST /auth/mfa/setup/` (QR URI + base32), `POST /auth/mfa/verify/` (backup codes shown once), `POST /auth/mfa/login/` (second-step JWT), `POST /auth/mfa/disable/` (platform admin). `MFA_GRACE_PERIOD_DAYS` env var (default 30). Frontend: `/profile/security` (enrollment + QR + backup codes download), `/auth/mfa` (6-digit auto-submit), MFA status badge on settings.
  - **S-063 AI Prescription Safety Net:** `PrescriptionSafetyChecker` service (Claude Haiku) — drug-drug interactions, dose validation, allergy cross-check, contraindications for encounter diagnoses. `AISafetyAlert` model + migration (`emr/0010_aisafetyalert.py`). Signal `post_save` on `PrescriptionItem` → `check_prescription_safety` Celery task. Redis cache 1h by `sha256(drug + other_drugs_sorted + allergies_sorted)`. Feature flag `ai_prescription_safety`. Endpoints: `POST /emr/prescriptions/{id}/items/{item_id}/safety-check/`, `POST .../acknowledge-alert/` (override logged to AuditLog). Frontend: `SafetyBadge`, `SafetyAlertModal`, `PrescriptionBuilder` polls for 10s with amber → green/yellow/red state.
  - **S-064 AI CID-10 Suggester:** `CID10Suggester` service — top-3 ICD-10 suggestions with confidence, validated against local `CID10Code` table (rejects hallucinated codes). `AICIDSuggestion` model tracks accepted/rejected outcomes. `CID10Code` migration (`core/0008_cid10code.py`). Redis cache 24h by `sha256(normalized_text)`. Feature flag `ai_cid10_suggest`. Endpoints: `POST /emr/encounters/{id}/cid10-suggest/`, `POST .../cid10-accept/`. Frontend: `CID10Suggest` component with 1.5s debounce + 3 suggestion chips, wired into `SOAPEditor`.
  - **S-065 Prescription PDF Export:** `weasyprint` added. `PrescriptionPDFGenerator` — Jinja2 HTML → PDF with clinic logo, doctor CRM, patient info, items, digital hash (sha256), watermark. Controlled substances render on separate page with blue border (Receituário Azul). Signature required before PDF generation. `GET /emr/prescriptions/{id}/pdf/` returns `application/pdf` with 1h Redis cache. `PRESCRIPTION_PDF_CACHE_TTL` env var. `backend/Dockerfile` + `docker-compose` add libcairo2, libpango, fonts-liberation for WeasyPrint OS deps. CI smoke test verifies WeasyPrint before pytest.
  - **S-066 Appointment Cancellation Waitlist:** `WaitlistEntry` model + migration (`emr/0012_waitlistentry.py`) with status machine (`waiting/notified/booked/expired/cancelled`) and preferred date/time ranges. Signal `on_appointment_cancelled` → `notify_next_waitlist_entry` Celery task sends WhatsApp. `expire_waitlist_notification` task fires after 30min countdown via `apply_async`. WhatsApp response handler routes `SIM`/`NÃO` from notified entries → book-or-skip. REST: `GET/POST /emr/waitlist/`, `DELETE /emr/waitlist/{id}/`. Frontend: `/appointments/waitlist` management view, "Entrar na fila de espera" on unavailable slots, status-badge sidebar panel.
  - **Sprint 15-17 catch-up (f135c28):** AI Scribe (Whisper service + `views_scribe.py` + `AudioRecorder` + `ScribeButton` + SOAP editor integration), DPA modal (`AIDPAStatus` migration `core/0009_aidpastatus.py` + `views_dpa.py` + `DPASignModal`), AI config page (`/configuracoes/ai`), patient check-in flow (`/waiting-room` + `WaitTimeCard`), WhatsApp appointment reminder uniqueness constraint (`whatsapp/0005_alter_appointmentreminder_unique...`).

### Fixed
- **DX-07:** `docs/PLAN_SPRINT15.md` migration table now documents django-tenants run order — use `migrate_schemas` (not `migrate`), shared-first then tenant-second.
- **DX-08:** `.github/workflows/ci.yml` backend-test installs libcairo2/libpango/fonts + smoke-tests WeasyPrint before pytest, catching OS-dep regressions that would otherwise surface as cryptic Cairo errors in S-065 PDF tests.
- `backend/conftest.py` (new): close stale DB connections at test-class boundaries to fix `TenantTestCase` teardown cascade.
- `backend/.dockerignore` (new): exclude `.venv` so docker build context reads cleanly on Windows (`.venv/lib64` is a symlink Docker can't traverse).

### Changed
- `backend/requirements/base.txt`: + `pyotp`, `qrcode[pil]` (MFA), `weasyprint` (PDF).
- `.env.example`: + `MFA_GRACE_PERIOD_DAYS`, `PRESCRIPTION_PDF_CACHE_TTL`.
- `.gitignore`: + pytest scratch files (`check_run*`, `fix_testdb`, `drop_testdb.py`, `uv.lock`).

## [0.9.0] — 2026-04-05

### Added
- **First Pilot Readiness (Sprint 14, S-054–S-061):** End-to-end pilot clinic operations — onboarding wizard, real PIX payments via Asaas, transactional email confirmations, demo seed data, 5 performance indexes, mobile-responsive pages, user guide, and pilot monitoring dashboard.
  - **S-054 Tenant Onboarding Wizard:** 5-step frontend wizard at `/setup` (clinic name, professional credentials, working hours click-to-toggle days, PIX key, completion screen). Backend: `POST /api/v1/emr/setup/professional/` (idempotent — creates/updates Professional + ScheduleConfig atomically), `GET /api/v1/emr/setup/status/`. `ProfessionalSetupSerializer` validates `council_type`, `council_state`, `working_days`, and slot duration.
  - **S-055 PIX Payment Integration (Asaas):** `AsaasService` (LGPD: name+email only, no CPF to Asaas), `PIXCharge` model, `AsaasChargeMap` (public schema webhook routing), `PIXChargeView` (idempotent), `AsaasWebhookView` (`hmac.compare_digest`, `select_for_update()` idempotency, tenant routing). Celery task `expire_pix_charges` every 5 min. `MIGRATION_MODULES` workaround for root-owned billing migrations dir.
  - **S-056 Transactional Email:** `EmailService.send_appointment_confirmation/reminder()`, HTML templates, signal receiver `on_appointment_paid` → `Celery.delay()`, daily 08:00 reminder beat task.
  - **S-057 Seed Data:** `make seed-demo tenant=<schema>` seeds patients, appointments, and 6 PIXCharge records with varied statuses.
  - **S-058 Performance Indexes:** RunSQL function index on `DATE(start_time AT TIME ZONE 'America/Sao_Paulo')`, GIN on `Patient.insurance_data`, composite `(action, created_at)` on AuditLog, `(status, expires_at)` on PIXCharge. `docs/PERFORMANCE.md`.
  - **S-059 Mobile Responsiveness:** Appointments page day-list card view on `<md` (patient name, time, status, action button); header/legend responsive. Setup wizard mobile-first.
  - **S-060 User Guide:** `docs/USER_GUIDE.md` — 10 sections in PT-BR including "AI em breve" section.
  - **S-061 Pilot Monitoring Dashboard:** `GET /api/v1/platform/pilot-health/` (platform admin) with per-tenant KPIs + system health. Frontend `/platform/monitor` — 30s auto-refresh, stale indicator, sparklines.
  - **DX:** `docs/DEVELOPMENT.md`, `docs/USER_GUIDE.md`, `.env.example` Asaas vars.

### Fixed
- `billing/models.py` missing `import uuid` for PIXCharge model.
- `apps/core/apps.py` imports `billing.services.tasks` in `ready()` to wire `appointment_paid` signal receiver.

## [0.8.0] — 2026-04-05

### Added
- **Pre-Production Hardening (Sprint 13, S-044–S-053):** Full production readiness — connection pooling, Redis cache, structured logging, Sentry tenant tagging, rate limiting, staging infra, CI/CD pipeline, and operations documentation.
  - **S-044/S-046 Production Settings Hardening:** `production.py` rewritten from 48 lines to full production config. DB connection pooling (`CONN_MAX_AGE=60`, `CONN_HEALTH_CHECKS=True`). Redis cache via `django_redis` replacing in-memory. Session engine switched to Redis (`SESSION_ENGINE=cache`). `SECURE_HSTS_PRELOAD=True`. Upload size limits (10 MB). `DATA_UPLOAD_MAX_MEMORY_SIZE`.
  - **S-046 Structured JSON Logging:** `python-json-logger==2.0.7` added. `LOGGING` config in `production.py` emits JSON with `tenant` and `request_id` fields on every log line. `TenantRequestLogFilter` injects schema name (falls back to `"shared"` in Celery context). `RequestIdMiddleware` generates UUID4 per request, echoed in `X-Request-ID` response header, cleaned up in `finally` block.
  - **S-045 Sentry Integration:** `sentry_sdk.init` with `DjangoIntegration` + `CeleryIntegration`, `traces_sample_rate=0.1`, `profiles_sample_rate=0.1`. `before_send` hook tags events with `connection.tenant.schema_name` for per-clinic Sentry triage. PHI stripping (`cpf`, `patient_id`, `patient_name`, `phone`, `email`) from `user` and `extra` dicts for LGPD compliance. `@sentry/nextjs@8` added to frontend. `sentry.client.config.ts` and `sentry.server.config.ts` with `maskAllText=true`, `blockAllMedia=true` Session Replay, PHI stripping in `beforeSend`. `next.config.mjs` wrapped with `withSentryConfig`.
  - **S-047 Global Rate Limiting:** `TenantUserRateThrottle` subclasses `UserRateThrottle` with `throttle:{schema}:{base_key}` cache key to prevent cross-tenant bucket collision in shared Redis. `DEFAULT_THROTTLE_CLASSES` + `DEFAULT_THROTTLE_RATES` added to `REST_FRAMEWORK` in `base.py` (anon: 100/hr, user: 1000/hr). `LoginRateThrottle` (5/min, `AnonRateThrottle` subclass) applied to `LoginView`.
  - **S-048 CI Fixes:** `ci.yml` branch trigger updated from `[main, develop]` to `[main, master, develop]` — CI was never running on production branch. `docker-validate` job condition updated to include `refs/heads/master`. `frontend/app/(dashboard)/farmacia/catalog/page.tsx`: added `anvisa_code?: string | null` to `Drug` type (pre-existing TS error).
  - **S-049 Staging Compose:** `docker-compose.staging.yml` using GHCR images (`vitali-backend` + `vitali-frontend`), `restart: always`, no exposed host DB/Redis ports, `--env-file .env.staging` pattern. `.env.staging.example` with all 20+ required env vars.
  - **S-050 Smoke Tests:** `scripts/smoke_test.sh` — 7 checks: `/health/` (200 + <500ms warning), `POST /api/v1/auth/login` (401 + `Content-Type: application/json`), `/api/schema/` (200), frontend (200), static files, Celery task execution (enqueue + `result.get(timeout=10)` with Redis ping fallback), HTTPS redirect. Exit 0 on pass, exit 1 with named failures.
  - **S-051 Staging CD Pipeline:** `.github/workflows/deploy-staging.yml` — triggers on push to master + `workflow_dispatch`. Build-and-push job (GHCR, sha + latest tags, layer caching). Deploy job via SSH: pre-deploy rollback snapshot using GHCR image names, pull + `up -d`, `migrate_schemas --shared`, `collectstatic`. Auto-rollback on smoke test failure.
  - **S-052 Operations Documentation:** `docs/DEPLOY.md` — 9-step quickstart, full env var reference table, GitHub Secrets table, rollback procedure (manual + automatic + specific tag), post-deploy verification. `docs/RUNBOOK.md` — reading JSON log lines by tenant/request_id, restarting services in correct order, Django shell with tenant context, Redis key inspection and flush procedures, Celery inspection. `docs/TENANT_MIGRATIONS.md` — additive-only migration rule, pre-migration per-tenant pg_dump snapshot, `migrate_schemas --shared` first then all tenants, single-tenant retry, rollback procedure with explicit downtime disclosure and `DROP SCHEMA / restore` steps.
  - **S-053 Hardening Tests:** `backend/apps/core/tests/test_middleware_hardening.py` — 17 tests covering `RequestIdMiddleware` (UUID4 header, uniqueness, thread-local cleanup, exception safety), `TenantRequestLogFilter` (tenant/request_id injection, shared fallback, always returns True), `TenantUserRateThrottle` (per-schema key scoping, cross-tenant isolation, anonymous None key), production settings (CONN_MAX_AGE, CONN_HEALTH_CHECKS, SESSION_ENGINE, CSRF_TRUSTED_ORIGINS as list).

### Fixed
- **Critical: `DATABASES` engine lost in production** — `production.py` rewrote `DATABASES` entirely, dropping `ENGINE=django_tenants.postgresql_backend` set in `base.py`. Fixed by using `.update()` instead of full reassignment. Would have broken all tenant schema routing on first production deploy.
- **Critical: CD rollback broken** — `deploy-staging.yml` tagged `vitali-django:rollback` / `vitali-nextjs:rollback` (nonexistent local names) instead of actual GHCR image paths. Rollback would silently fail. Fixed with `ghcr.io/{owner}/vitali-backend:rollback` naming.
- **Redis cache backend mismatch** — `CACHES` used `django.core.cache.backends.redis.RedisCache` (Django built-in) but specified `CLIENT_CLASS: django_redis.client.DefaultClient` (django-redis option). Changed backend to `django_redis.cache.RedisCache`.

## [0.7.0] — 2026-04-05

### Added
- **WhatsApp Patient Engagement (Sprint 12, S-032/033/034/035):** Full WhatsApp appointment scheduling via conversational FSM, LGPD-compliant opt-in/opt-out, 24h and 2h automated reminders, post-visit satisfaction surveys, and receptionist conversation history panel.
  - **S-032 WhatsApp Webhook + LGPD Consent:** `WebhookView` with HMAC-SHA256 validation (fail-closed when secret unset), per-contact rate limiting (20 msg/min, atomic `cache.incr`), `WhatsAppContact` model with opt-in lifecycle (`do_opt_in` / `do_opt_out`), `MessageLog` audit trail with CPF fully masked (`***.***.***-**`). Evolution API integration via `EvolutionAPIGateway`. REST API: `GET/POST /api/v1/whatsapp/contacts/`, `GET /api/v1/whatsapp/message-logs/`, `GET /api/v1/whatsapp/health/`, `POST /api/v1/whatsapp/setup-webhook/`. 6 test files.
  - **S-033 Appointment Scheduling FSM:** 13-state `ConversationFSM` covering LGPD consent → specialty/professional/date/time selection → confirmation → booking. Intent detection for 30+ PT-BR phrases. Max 3 unrecognized inputs before FALLBACK_HUMAN. `select_for_update()` on Professional row prevents double-booking of empty slots. Session deleted after booking (CPF/PII gone). `slot_service.py` generates available slots from `ScheduleConfig` (working hours, lunch break, slot duration) minus booked appointments. 
  - **S-034 Appointment Reminders:** Celery tasks `send_appointment_reminders` (24h + 2h windows, every 15 min) and `mark_no_shows` (hourly) with `select_for_update(skip_locked=True)` inside `transaction.atomic()`. `ScheduledReminder` model with `unique_together` guard prevents duplicate sends.
  - **S-035 Satisfaction Surveys + Settings UI:** `send_satisfaction_surveys` task sends post-visit survey 2h after appointment completion. Frontend: `/configuracoes/whatsapp` settings page (QR code scan flow, connection status, conversation history with contact list + message thread), appointment badge in `/appointments` page.

### Fixed
- **WhatsApp booking flow (6 critical pre-ship bugs):** `_parse_date_selection` returned raw int instead of ISO date string; `_get_specialties` used Professional PK as specialty menu ID; `_get_professionals` had same PK-vs-menu-index bug; `select_for_update()` called outside `transaction.atomic()` in tasks (TransactionManagementError); `"2"` in global INTENT_MAP triggered opt-out from every numeric menu state; `session.save()` called after `session.delete()` on booking confirmation (IntegrityError). All fixed.
- **Security (3 pre-ship bugs):** Webhook fail-open when `WHATSAPP_WEBHOOK_SECRET` unset (now fail-closed); `SetupWebhookView` accepted client-supplied webhook URL (SSRF, now server-side only); `_log_message` CPF mask exposed last digit via `m.group()[-1]` (now fully masked).
- **Rate limiter race condition:** Non-atomic `cache.get`/`cache.set` in `_check_rate_limit` replaced with atomic `cache.incr()`.
- **Pagination missing:** `WhatsAppContactViewSet` had no pagination (50k-row response risk); added `MessageLogPagination`.

## [0.6.0] — 2026-04-05

### Added
- **Commercialization Layer (Sprint 11):** Module gating, subscription management, purchase orders, and pilot readiness — the infrastructure for a real revenue model
  - **S-039 Module Permission Layer:** `ModuleRequiredPermission` DRF permission class gates every billing, pharmacy, analytics, and AI endpoint by tenant `FeatureFlag`. Frontend `useHasModule()` hook with 5-minute `sessionStorage` TTL hides nav items for inactive modules (fail-open — all items visible until fetch completes, no layout shift). Applied to 15 ViewSets/Views across billing, analytics, pharmacy, and AI apps. `ALLOWED_MODULE_KEYS` constant in `core/constants.py` as the single source of truth. 9 tests.
  - **S-040 Platform Admin Subscription API:** REST API for `Plan`, `PlanModule`, and `Subscription` in the public schema — the Vitali operator control plane. `IsPlatformAdmin` permission (superuser only). `ActivateModuleView` and `DeactivateModuleView` with `select_for_update()` TOCTOU protection. PATCH on `Subscription.active_modules` uses double-lock pattern to sync `FeatureFlag` rows atomically. `POST /api/v1/platform/subscriptions/{id}/activate-module/` and `deactivate-module/`. 7 tests.
  - **S-041 Tenant Subscription Status Page:** `GET /api/v1/subscription/` returns current plan, active modules, and pricing for the tenant admin. New `/configuracoes/assinatura` page — shows plan name, active module badges, and renewal date. "Configurações" nav item (gear icon, admin-only). Graceful 404 empty-state when no subscription is configured.
  - **S-042 Purchase Orders:** `Supplier`, `PurchaseOrder`, `PurchaseOrderItem` models. Full PO lifecycle: create → send → receive (partial or full). `POST /pharmacy/purchase-orders/{id}/receive/` creates `StockMovements` and updates `StockItem.quantity` atomically via `F()` expressions with `select_for_update()`. New `'purchase_order_receiving'` movement type added to `StockMovement.MOVEMENT_TYPES`. Frontend: PO list (`/farmacia/compras`), PO detail (`/farmacia/compras/{id}`), create PO form (`/farmacia/compras/nova`) with supplier autocomplete and drug/material search. Status badges match DESIGN.md semantic color system. 9 tests.
  - **S-043 Pilot Readiness:** `seed_demo_data` management command populates a tenant with realistic demo data. `DemoModeMiddleware` wraps all write endpoints in 403 when `DEMO_MODE=true` (auth and platform admin paths whitelisted). `OnboardingView` (`GET /api/v1/onboarding/`) returns step completion state. `OnboardingWidget` renders on the dashboard when any step is incomplete — progress bar + step list with "Fazer agora →" CTAs. 6 tests.

### Fixed
- **Dashboard CORS failure:** Analytics fetches used `http://localhost:8000` directly — CORS blocked in browser. Now uses relative `/api/v1/analytics` path through the Next.js catch-all proxy.
- **OnboardingWidget 404:** Widget called `/api/v1/core/onboarding/` (wrong URL). Corrected to `/api/v1/onboarding/` per `core/urls.py` routing.
- **OnboardingWidget hidden on analytics error:** Error state rendered without `<OnboardingWidget />`. Fixed — widget now shows even when analytics returns an error.
- **Analytics 403 not cleared:** 403 response (analytics module inactive) left `error` state set, causing a red error banner. Fixed — `setError(null)` added before the early return.
- **Next.js proxy trailing-slash loss:** `next.config.mjs` rewrites stripped trailing slashes before forwarding, causing Django DRF 404s. Replaced with a catch-all proxy route (`app/api/[...path]/route.ts`) that preserves trailing slashes explicitly.
- **Docker-internal tenant routing:** Server-side `fetch()` from Next.js to Django used the container hostname (`django:8000`) as the `Host` header, which didn't match any `django-tenants` `Domain` row. Fixed by forwarding `X-Forwarded-Host` (stripped port) and enabling `USE_X_FORWARDED_HOST=True` in Django settings.

## [0.5.0] — 2026-04-02

### Added
- **Billing Intelligence Dashboard (Sprint 10):** Full analytics layer for billing — 5 API endpoints, 6 frontend components, and a TUSS staleness monitor
  - **S-035 Billing Analytics API:** 5 aggregate endpoints — `GET /api/v1/analytics/billing/overview/` (KPI cards: denial rate, total billed/collected/denied for current month); `GET /api/v1/analytics/billing/monthly-revenue/` (monthly revenue trend grouped by `competency` field, not `created_at`); `GET /api/v1/analytics/billing/denial-by-insurer/` (top insurers by denied value, ≥10 guide volume floor); `GET /api/v1/analytics/billing/batch-throughput/` (created vs closed batches per month, two-query merge); `GET /api/v1/analytics/billing/glosa-accuracy/` (AI prediction precision and recall per insurer); all protected with `IsAuthenticated`; 35 tests covering edge cases including appeal-status in denial totals, draft exclusion from denial rate denominator, cross-month batch merge, precision=null guard
  - **S-036 Billing Intelligence Page:** New `/billing/analytics` frontend page — sidebar "Análise" nav item (BarChart2 icon); KPI cards row (locked to current month, 2×4 responsive grid); denial-by-insurer horizontal bar chart with click-to-filter navigation to `/billing/guides`; revenue trend stacked area chart ("Não Glosado" vs "Glosado"); batch throughput line chart; Glosa AI Accuracy table with cold-start onboarding copy and warming-up progress indicators; 3m/6m/12m period toggle (default 6m, affects charts only); per-section independent error banners with retry; animate-pulse skeletons during load; keyboard-accessible chart bars
  - **S-037 Glosa Prediction Accuracy Tracker:** Integrated into S-035/S-036 — precision = true_positives / predicted_high; recall = true_positives / was_denied; precision=null when no high-risk predictions; unresolved predictions (was_denied=None) excluded from denominator
  - **S-038 TUSS Staleness Monitor:** `check_tuss_staleness` Celery task — three thresholds: <14d = fresh (no log), 14–29d = INFO "ageing", ≥30d = WARNING "stale"; queries `TUSSSyncLog` from public schema; DB errors caught and returned gracefully; registered via data migration `apps.ai.0004` using `PeriodicTask.get_or_create` (idempotent); `cleanup_orphaned_glosa_predictions` also registered in the same migration

## [0.4.0] — 2026-03-31

### Added
- **AI TUSS Auto-Coding (Sprint 8):** AI-assisted procedure code suggestion for faturistas — `apps/ai` Django app with full LLM integration pipeline
  - **S-030 LLM Integration Layer:** `LLMGateway` abstract class + `ClaudeGateway` (claude-haiku-4-5-20251001); `AIPromptTemplate` model with `(name, version)` unique constraint for safe versioning; `AIUsageLog` append-only call log with event types (llm_call, cache_hit, zero_result, validation_dropout, degraded); per-tenant Redis rate limiter (default 100 calls/hour, fail-open); Redis circuit breaker (3 failures/60s → 5min cooldown, fail-open); `run_llm_task` Celery task; admin interface for templates and logs
  - **S-031 TUSS Suggestion API:** Two-stage retrieval pipeline: GIN search_vector (Portuguese FTS) → trigram fallback → Claude re-ranking; DB validation gate blocks hallucinated codes; `TUSSAISuggestion` model records every suggestion shown with acceptance tracking; 24h tenant-scoped Redis cache (SHA-256 key, prompt-version-aware); `POST /api/v1/ai/tuss-suggest/` returns up to 3 ranked suggestions with `tuss_code_id`, `suggestion_id`, and `degraded`/`cached` flags; `POST /api/v1/ai/tuss-suggest/feedback/` records faturista accept/reject; `GET /api/v1/ai/usage/` admin monthly usage dashboard (tokens in/out, latency, acceptance rate); gated by `FEATURE_AI_TUSS` feature flag (default off)
  - **Frontend `TUSSSuggestionInline`:** 6-state pill component (idle/loading/suggestions/empty/degraded/idle-after-select) wired into guide creation form; 600ms debounce, per-row AbortController for race-safe fetches; overwrite confirmation dialog; fires acceptance feedback on pill selection; clears after selection
  - **Security hardening:** `guide_type` allowlist validation in serializer; curly-brace stripping on user inputs before LLM prompt `.format()`; JSON parse errors do not trip circuit breaker (only API transport failures do); prompt injection guards on both description and guide_type fields

## [0.3.0] — 2026-03-30

### Added
- **Pharmacy app (Sprint 7):** Full pharmacy module — catalog, stock management, dispensation
  - **S-026 Drug & Material Catalog:** `Drug` model with ANVISA code, barcode, controlled-substance classification (ANVISA lists A1–C5), and soft-delete; `Material` model for non-drug hospital supplies; full CRUD REST API with search, permission-gated writes (`pharmacy.catalog_manage`)
  - **S-027 Stock Management:** `StockItem` (lot ledger) + `StockMovement` (append-only movement log); FEFO-ready lot ordering; `CheckConstraint(quantity >= 0)` at DB level; F()-based atomic quantity updates preventing race conditions; stock adjustment endpoint (`POST /pharmacy/stock/items/{id}/adjust/`) requiring `pharmacy.stock_manage`; `StockAlertsView` reading pre-computed expiry + low-stock alerts from Redis; Celery tasks (`check_expiry_alerts`, `check_min_stock_alerts`) writing tenant-scoped Redis keys
  - **S-028 Dispensation:** Atomic FEFO multi-lot dispensation (`POST /pharmacy/dispense/`) with `select_for_update()` on both `PrescriptionItem` (over-dispense guard) and stock lots; controlled-substance gate (`pharmacy.dispense_controlled`); mandatory notes for controlled drugs; `Dispensation` + `DispensationLot` models; stock availability query endpoint
  - **Prescription items (EMR):** `Prescription` + `PrescriptionItem` models with sign/cancel lifecycle; `MinValueValidator(Decimal('0.001'))` on item quantity; serializer blocks adding items to signed prescriptions; REST API under `/api/v1/` with permission guards
  - **Pharmacy frontend (Sprint 7):** 5 pages under `/farmacia/`
    - Catalog page (drug + material tabs, search, inline creation form, clickable rows)
    - Drug detail page (view/edit/deactivate, controlled-class badge)
    - Material detail page (view/edit/deactivate)
    - Stock list page (KPI alert cards, filters, entry form with drug search, clickable rows)
    - Stock item detail page (quantity/min/expiry KPI cards, adjustment form, movement history)
  - **Pharmacy nav link** in `DashboardShell`

### Fixed
- **Stock adjust permission gap:** `adjust` action on `StockItemViewSet` previously fell through to `pharmacy.read`; now correctly requires `pharmacy.stock_manage`
- **PrescriptionItem `MinValueValidator`:** Changed from string `'0.001'` to `Decimal('0.001')` to avoid `TypeError` on decimal field comparison
- **Prescription status never updated after dispensation:** `_dispense_fefo()` completed dispensation without updating `Prescription.status`; now locks the prescription row and sets `partially_dispensed` or `dispensed` correctly. Regression tests added.
- **`StockAlertsView` silent Redis failure:** On cache miss/failure the view returned an empty list with 200 and no indication of failure; now returns `cache_available: false` so the frontend can show a warning.
- **`timezone.timedelta` crash in Celery tasks:** `django.utils.timezone` has no `timedelta` attribute; `check_expiry_alerts` and `check_min_stock_alerts` crashed on every invocation. Fixed by importing `from datetime import timedelta` directly.
- **Duplicate drugs in search results:** Queryset union (`|`) on `name` + `generic_name` returned duplicates for drugs matching both fields. Fixed using a single `Q()` OR filter.
- **Audit logged before save in `perform_destroy`:** Audit record was written before `save()` completed; if save raised, a phantom audit entry would exist. Fixed: log after save.
- **Missing auth headers on all pharmacy frontend pages:** All 19 fetch calls across 6 pharmacy pages (`catalog`, `drugs/[id]`, `materials/[id]`, `stock`, `stock/[id]`, `dispense`) were missing `Authorization: Bearer <token>` headers, causing 401s in production. Fixed.
- **Null token sending `Authorization: Bearer null`:** `getAccessToken()` returns `null` when session is expired; string interpolation produced a literally invalid header. Added `!token` guards to all write handlers — they now surface "Sessão expirada" instead of silently failing.
- **`materials/[id]` DELETE always navigated on failure:** `router.push()` was called unconditionally after DELETE; now checks for `res.ok || res.status === 204` before navigating.
- **`filterExpiring` included null-expiry items:** When "expiring in 30 days" filter was active, items with no expiry date appeared in results. Fixed: null-expiry items are now hidden when filter is active.

### Changed
- API version bumped from `0.2.0` → `0.3.0`

---

## [0.2.0] — 2026-03-30

### Added
- **Billing app (Sprint 6a):** Full TISS/TUSS billing foundation
  - `TISSGuide` model with atomic sequential guide number generation (`YYYYMM + 6-digit seq`)
  - `TISSBatch` model with open/close lifecycle and double-submit protection
  - `Glosa` model with appeal workflow
  - `InsuranceProvider` and `PriceTable` models
  - TISS XML generation engine with ANS XSD validation
  - TISS retorno XML parser (updates guide statuses and creates Glosa records)
  - Role-based permission guard (`IsFaturistaOrAdmin`) on all billing endpoints
  - Full REST API: guides, batches, glosas, providers, price tables, TUSS code search
- **TUSSCode model:** Shared-schema TUSS procedure code table with full-text search
  - Management command `import_tuss` for loading ANS TUSS CSV
  - GIN index on `search_vector` for fast combobox queries
- **PatientInsurance model (EMR):** Links patients to insurance providers with card numbers
- **Billing frontend (Sprint 6b):** 9 pages under `/billing/`
  - Overview dashboard with KPI cards, recent guides, open batches
  - Guides list with status/search filters
  - Guide creation form (encounter, patient, provider, TISS items)
  - Guide detail with submit action and glosas section
  - Batches list with new batch modal
  - Batch detail with close/export/upload retorno actions
  - Glosas management with appeal filing
  - Price tables management
  - Billing nav link in `DashboardShell`

### Fixed
- **Auth token access (ISSUE-001):** Dashboard and encounter pages read `localStorage.getItem('access_token')` but login only sets an `httpOnly` cookie invisible to JS. Fixed by adding a non-httpOnly `access_token_js` mirror cookie in login/refresh/logout routes and centralizing token access in `lib/auth.ts:getAccessToken()`.
- **Auth tests:** `AuthTestCase` ran in public schema (Django `TestCase`), causing 404s on tenant auth endpoints. Migrated to `TenantTestCase` with `SERVER_NAME` routing and `cache.clear()` in setUp.
- **XML XXE vulnerability:** `lxml.etree.fromstring()` called without parser options in retorno parser and XSD validator. Fixed by passing `XMLParser(resolve_entities=False, no_network=True)`.

### Changed
- API version bumped from `0.1.0` → `0.2.0`
- `backend/requirements/base.txt`: added `jinja2>=3.1` (TISS XML templates), `lxml>=5` (XSD validation)

## [0.1.0] — 2026-03-01

- Sprint 1–5: Multi-tenant foundation, EMR core, authentication, patient management, appointments, encounters, SOAP notes, waiting room
