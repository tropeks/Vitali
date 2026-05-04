# Sprint 25: Clinical Journey Gate

## Goal

Make the core clinic flow operational end to end: patient registration, appointment arrival, start of care, encounter documentation, signature, and patient timeline traceability.

## Shipped Scope

### S25-01: Patient Registration UI

- Added `/patients/new`.
- The patients list now loads initial data instead of staying empty until search.
- Patient detail uses the canonical `/api/v1/patients/` API path.

### S25-02: Appointment Start Cascade

- `POST /api/v1/appointments/<id>/start/` now creates or reuses the linked `Encounter`.
- The action also ensures `SOAPNote` and `VitalSigns` exist.
- Terminal appointments (`completed`, `cancelled`, `no_show`) cannot be started.
- The response includes `encounter_id` and `encounter_created`.

### S25-03: Frontend Clinical Handoff

- The waiting room "Chamar" action calls the start endpoint and routes to the encounter.
- The appointment detail "Iniciar" action uses the same start endpoint.
- Patient timeline now reads the backend timeline endpoint and links to encounters.

### S25-04: Clinical Staff Bootstrap

- HR onboarding for clinical roles creates a default weekday `ScheduleConfig`.
- This removes the hidden manual setup step before a newly hired doctor can receive appointments.

### S25-05: Blocking E2E

- Added `clinical-journey.spec.ts`.
- The spec covers patient registration -> appointment -> check-in -> start -> SOAP/vitals -> sign -> patient timeline.

## Verification Commands

Backend:

```bash
docker compose exec -T django pytest -v apps/emr/tests/test_appointment_checkin.py apps/hr/tests/test_api_onboarding.py
```

Frontend:

```bash
cd frontend
npm run lint
npm run type-check
npx playwright test clinical-journey.spec.ts
```

## Acceptance Criteria

- A newly created patient can be opened from the UI.
- A checked-in appointment can be started exactly once without duplicate encounters.
- Starting the appointment sends the user to the encounter detail screen.
- SOAP/vitals can be recorded before signing.
- Signed encounters appear in the patient's timeline.
