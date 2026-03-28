# TODOS

## Security

### Upgrade Next.js from 14.2.29 (security vulnerability)

**What:** Upgrade `next` from `14.2.29` to the latest patched version.

**Why:** `next@14.2.29` has a known security vulnerability. See https://nextjs.org/blog/security-update-2025-12-11. npm flags it as 4 high severity vulnerabilities.

**Context:** Discovered during `npm install` on 2026-03-28. Run `npm audit` in `frontend/` for details. Upgrade may include breaking changes — test the build and all pages after upgrading. Run `npm install next@latest` and resolve any peer dep conflicts.

**Effort:** S (human: ~2h) → S with CC+gstack (~15 min)
**Priority:** P1
**Depends on:** None

---

## Pharmacy / Prescriptions

### PDF archival: cache-on-first-print for signed prescriptions

**What:** Store generated WeasyPrint PDFs in object storage (S3/MinIO) on first print, keyed by `prescription_id`. Subsequent prints serve the stored file.

**Why:** WeasyPrint regenerates the same bytes on every call to `GET /api/v1/emr/prescriptions/{id}/print/`. Since prescriptions are immutable after signing, the cache never expires. At 500+ renders/day across 50 clinics, regeneration becomes a scaling cost. Object storage also provides an audit-proof PDF archive for clinics.

**Context:** WeasyPrint decided over browser print CSS in Sprint 6 (Decision #17 in `docs/PLAN_SPRINT6.md`) for reliable prescription output. The `print/` endpoint currently calls WeasyPrint on every request. Implementation: on first print, store the PDF bytes to object storage keyed by `prescription_id`; set a `pdf_url` field on Prescription (nullable FK or separate `PrescriptionPDF` model); on subsequent requests, redirect to the stored URL instead of regenerating. Requires object storage setup (S3 or MinIO) which is not yet configured for Vitali.

**Effort:** M (human: ~2 days) → S with CC+gstack (~20 min once object storage is set up)
**Priority:** P2
**Depends on:** Object storage configuration (not in any current sprint)
