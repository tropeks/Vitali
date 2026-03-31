# TODOS

## ~~P1 — TISS XSD Schema File Missing~~ DONE

All 6 schema files committed to `backend/apps/billing/schemas/` (ANS + W3C xmldsig).
`validate_xml()` now performs real XSD validation. Tested via docker.
Commit: `feat(billing): add ANS TISS 4.01.00 XSD schema files`.

---

## ~~P1 — PatientInsurance API Endpoint Missing~~ DONE

Endpoints shipped: `GET/POST /api/v1/emr/patients/{id}/insurance/` and
`PATCH/DELETE /api/v1/emr/patients/{id}/insurance/{card_id}/`.
Commit: `feat(emr): add PatientInsurance REST endpoints`.

---

## ~~P1 — TUSSCodeSearch Frontend Combobox Missing~~ DONE

Guide and price-table creation forms need a TUSS code search combobox (debounce 300ms,
calls `GET /api/v1/billing/tuss/?q=`). Without it, faturistas must type codes manually
and the inline add-item UX on the guide form is incomplete.

**Fix:** Create `frontend/components/billing/TUSSCodeSearch.tsx` (combobox with debounce),
wire into `guides/new/page.tsx` items table and `price-tables/` item form.

**Deferred from plan:** `docs/PLAN_SPRINT6.md` — S-021.
**Priority:** P1 — Sprint 6b.

---

## ~~P1 — [Criar Guia TISS →] Button on Encounter Detail~~ DONE

The encounter detail page (`/encounters/[id]`) has no link to create a TISS guide from
that encounter. Faturistas must navigate to `/billing/guides/new` and manually select the
encounter — losing context.

**Fix:** Add a "Criar Guia TISS →" button to `frontend/app/(dashboard)/encounters/[id]/page.tsx`
that navigates to `/billing/guides/new?encounter={id}`. The guide form should prefill
encounter, patient, and professional from the query param.

**Deferred from plan:** `docs/PLAN_SPRINT6.md` — S-022.
**Priority:** P1 — Sprint 6b.

---

## ~~P2 — TISSGuide.total_value Drift~~ DONE

`TISSGuide.total_value` is set on guide creation but not recalculated when `TISSGuideItem`
records are edited or deleted post-creation. The guide XML uses `total_value` for TISS reporting.
Stale value = incorrect XML = potential insurer rejection or overpayment claim.

**Fix:** Override `TISSGuideItem.save()` and `delete()` to recalculate and save the parent
guide's `total_value`:
```python
def save(self, *args, **kwargs):
    self.total_value = self.unit_value * self.quantity
    super().save(*args, **kwargs)
    self.guide.total_value = self.guide.items.aggregate(t=Sum('total_value'))['t'] or 0
    self.guide.save(update_fields=['total_value', 'updated_at'])
```
Apply same recalculation in a `post_delete` signal on `TISSGuideItem`.

**Priority:** P2 — Sprint 6b. Pilot has simple guide workflows (create + submit, rarely edit).

---

## ~~P2 — TISSBatch M2M Provider Homogeneity~~ DONE

`TISSBatch.guides` M2M allows adding guides from any provider. TISS submission is per-provider;
a mixed-provider batch produces invalid XML that will fail at the insurer portal.

**Fix:** Add validation to the batch creation/update serializer:
```python
for guide in validated_guides:
    if guide.provider_id != provider.id:
        raise ValidationError(f"Guide {guide.guide_number} belongs to a different provider.")
```

**Priority:** P2 — Sprint 6b. Pilot clinic uses one provider; mixing can't happen with one provider.
Blocked by: nothing. Bundle with double-submit protection cleanup.

---

## ~~P2 — TISSGuide Status Bypass via Direct PATCH~~ DONE

`PATCH /api/v1/billing/guides/{id}/` accepts `{"status": "paid"}` — the serializer doesn't
restrict the status field. Dedicated action endpoints (`/submit`, close via batch) enforce
lifecycle rules, but a buggy client can bypass them.

**Fix:** Add `status` to `read_only_fields` in `TISSGuideSerializer`. Status changes must go
through dedicated action endpoints only. Same for `TISSBatch.status`.

**Priority:** P2 — Sprint 6b. Single faturista pilot = low risk. Required before multi-user.
Blocked by: nothing.

---

## ~~P2 — Retorno Upload Not Idempotent~~ DONE

Uploading the same retorno XML twice (double-click, network retry) processes it twice,
creating duplicate `Glosa` records for each denied item. Duplicate glosas inflate denial
counts in analytics and are hard to clean up in financial records.

**Fix:** Add idempotency check at the start of `upload_retorno`:
```python
if batch.retorno_xml_file:
    return Response(
        {"detail": "Retorno already processed for this batch. Use ?force=true to reprocess."},
        status=status.HTTP_409_CONFLICT,
    )
```

**Priority:** P2 — Sprint 6b. Pilot won't accidentally double-upload retornos.
Blocked by: `retorno_xml_file` field (Sprint 6, now added).

---

## ~~P2 — Guide Double-Submit Protection~~ DONE

A `TISSGuide` can currently be added to multiple `TISSBatch` objects via the M2M relationship.
This means the same guide could be submitted to the convênio twice in different batches —
a compliance risk (double billing).

**Fix:** Add a `clean()` validator on `TISSBatch` (or a pre-add M2M signal) that checks:
```python
if TISSBatch.objects.filter(
    guides=guide, status__in=["closed", "submitted"]
).exclude(pk=self.pk).exists():
    raise ValidationError(f"Guide {guide.guide_number} already in a submitted batch")
```
Alternatively, add a `batch = models.ForeignKey(TISSBatch, null=True)` on `TISSGuide` and
enforce uniqueness that way — cleaner than M2M for this constraint.

**Priority:** P2 — not needed for pilot demo but must be fixed before multiple clinics use billing.
**Update (2026-03-30 eng review):** Serializer-layer protection is already in place
(`serializers.py:184` calls `check_guide_not_double_submitted()`). What remains: direct
`.guides.add(guide)` calls bypass the serializer check. The TODOS item stands for adding
an M2M signal or FK constraint to close this gap.

---

## ~~P2 — DESIGN.md (after Sprint 6 ships)~~ DONE

`DESIGN.md` created via `/design-consultation` after Sprint 6. Vitali design system documented:
color tokens, typography, semantic status colors, spacing, component vocabulary.
Commit: `docs(design): add Vitali design system (DESIGN.md + HTML preview)`.
**Completed:** v0.4.0 (2026-03-31)

---

## ~~P2 — PatientInsurance CRUD on Patient Detail Page~~ DONE

The `PatientInsurance` model introduced in Sprint 6 allows inline card registration during
guide creation, but there is no management UI. Patients with two convênios can't add a second
card. Existing cards can't be updated or deactivated from the patient page.

**Fix:** Add a "Convênios" tab to `/patients/[id]/page.tsx` showing all insurance cards with
edit / add / deactivate actions. Uses the same `POST/PATCH /api/v1/emr/patients/{id}/insurance/`
endpoint family introduced in Sprint 6.

**Priority:** P2 — Sprint 6b alongside ICP-Brasil cert management. Blocked by: PatientInsurance model (Sprint 6).

---

## ~~P2 — Faturamento Card on Encounter Detail~~ DONE

The encounter detail page needs a "Faturamento" card as its last section, showing linked TISS
guides and a `[+ Criar Guia TISS →]` button. This is a cross-app UI concern — it lives in the
EMR app (`app/(dashboard)/emr/encounters/[id]/page.tsx`) but is not covered by any billing story
task. Easy to ship all billing stories and still leave faturistas with no entry point from the
clinical workflow.

**Fix:** Add Faturamento card to `app/(dashboard)/emr/encounters/[id]/page.tsx`:
- No guides: "Nenhuma guia TISS criada." + `[+ Criar Guia TISS →]` primary button linking to `/billing/guides/new?encounter={id}`
- 1+ guides: list each as `Guia #{number} — {StatusBadge}` with link to guide detail + `[+ Nova Guia]` ghost button
- Role guard: only render card if user has `billing.read` permission (hidden for roles without billing access)

Full spec: see "Decision 7c" in `docs/PLAN_SPRINT6.md` Pass 7 section.

**Priority:** P2 — Sprint 6, required for end-to-end faturista workflow demo.

---

## ~~P2 — TISSBatch.save() No Retry Loop~~ DONE

`TISSBatch.save()` calls `generate_batch_number()` with `select_for_update()` but has no
`IntegrityError` retry loop. If two batches are created concurrently on an empty month, the
second will throw an unhandled `IntegrityError`. Inconsistent with `TISSGuide.save()` which
has a 3-attempt retry.

**Fix:** Wrap `TISSBatch.save()` in the same retry pattern used by `TISSGuide.save()`.

**Priority:** P2 — Sprint 6b. Low risk for pilot (one faturista rarely creates batches
simultaneously) but required for correctness at scale.

---

## ~~P2 — Retorno Parser: TISS Namespace Fallback~~ DONE

`retorno_parser.py` uses `root.find(".//ans:retornoLote", NS)` with the full ANS namespace.
Some TISS implementations (older insurers, test environments) send XML without the `ans:`
namespace prefix. The parser returns `errors=["<retornoLote> not found"]` instead of parsing
the file.

**Fix:** If the namespaced find returns None, fall back to a namespace-agnostic search:
```python
retorno_lote = root.find(".//ans:retornoLote", NS) or root.find(".//retornoLote")
```

**Priority:** P2 — Sprint 6b. Affects compatibility with non-conforming TISS senders.

---

## ~~P1 — Pharmacy Module (Sprint 7)~~ DONE

S-026 Drug & Material catalog, S-027 Stock management (FEFO ledger, Celery alerts, Redis
alert cache), S-028 Dispensation (atomic FEFO multi-lot, controlled-substance gate).
Frontend: catalog page, drug/material detail pages, stock list, stock item detail with
adjustment form and movement history.

---

## P2 — TUSSSyncLog / import_tuss Refresh Documentation (Sprint 8)

`import_tuss` management command exists but there is no `TUSSSyncLog` model, no management
command to surface import status, and no `AIUsageLog` metadata extension to record last import
timestamp. The Sprint 8 plan allowed "or log in AIUsageLog metadata" as an alternative but
neither was implemented.

**Fix:** Add `TUSSSyncLog` model (or extend `AIUsageLog` with a `metadata` JSONField) to record
import timestamp, row count, and import source. Expose status via `GET /api/v1/ai/tuss-sync-status/`
(admin-only) so ops can verify the TUSS table is current before enabling `FEATURE_AI_TUSS`.

**Deferred from plan:** `docs/PLAN_SPRINT8.md`.
**Priority:** P2 — required before enabling `FEATURE_AI_TUSS` in production.

---

## P3 — TUSS Table Update Checker (Sprint 7)

The TUSS table is published by ANS periodically (~quarterly). The `import_tuss` management
command is idempotent but there is no automated check or alert when a new TUSS version is available.

**Fix:** Add a scheduled task (Celery Beat) that checks the ANS TUSS version endpoint and
logs a warning if the local version is older than 90 days. Optionally, auto-download and
re-import if running in a non-prod environment.

This belongs in Sprint 7 alongside the AI TUSS auto-coding work — both require the TUSS
table to be current for accurate suggestions.

**Priority:** P3 — informational. Stale TUSS codes cause guide validation failures, not
silent errors. The faturista will notice if a code is missing.
