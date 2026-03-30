<!-- autoplan: tropeks-Vitali / master / 002fa5c / 2026-03-28 -->
# Sprint 6 Plan — Billing Foundation (TISS/TUSS)

**Branch:** master
**Sprint:** 6
**Epic:** E-006 — Billing TISS/TUSS
**Stories:** S-021, S-022, S-023, S-023b, S-024, S-025
**Total points:** 41 (original 36 + Retorno TISS cherry-pick +5pts)
**Design doc:** `~/.gstack/projects/tropeks-Vitali/halfk-master-design-20260328-145944.md` (APPROVED)

---

## Goal

Deliver end-to-end TISS billing for SADT/ambulatory guides: import the TUSS code table,
create TISS XML guides from existing encounter data, export batch XML for convênio submission,
track denied guides (glosas), and configure price tables per insurer. After this sprint, a
faturista can create a valid TISS batch and download it for manual portal upload.

**Explicit out-of-scope:** Internação guides, honorários guides, in-app ICP-Brasil XML signing
(deferred to Sprint 6b — see ICP-Brasil decision below).

---

## Pre-Sprint Gates (must resolve before writing code)

### Gate 1: TISS Version
Verify the active ANS TISS schema version before building any XML.

```bash
# Check padrao.tiss.ans.gov.br or ANS downloads
# Target version in EPICS: TISS 4.01.00
# If 4.02.00 is now in force, the XSD namespace and envelope structure differ
```

Decision needed: is TISS 4.01.00 still active, or has 4.02.00 been published?
**Action:** browse padrao.tiss.ans.gov.br before S-022 XML work starts.

### Gate 2: TUSS Table Architecture
TUSS codes (~6,000-8,000 ANS codes) must be shared across all tenants.
`apps.billing` is in `TENANT_APPS` (per-tenant schema). Cross-schema query required.

**Decision: put TUSSCode model in `apps.core` (already in SHARED_APPS/public schema).**

Rationale: avoids duplicating 6-8k rows per tenant, avoids raw SQL `SET search_path` hacks,
consistent with how `Role`, `Plan`, `PlanModule` are already handled in core.
The billing app references `core.TUSSCode` via FK. The `TenantSyncRouter` handles this
naturally since core is in SHARED_APPS.

**Cross-schema FK caveat (eng review finding):** PostgreSQL does NOT enforce referential
integrity across schemas. `on_delete=models.PROTECT` on `TISSGuideItem.tuss_code` will not
be enforced at the DB level — it is application-layer only. Compensating check: add a
pre-delete signal on `TUSSCode` that checks for live guide/price-table references and
raises `ProtectedError` if any exist.

### Gate 3: ICP-Brasil Digital Signature
TISS batch XML submission to convênios requires a digital signature with the clinic's
ICP-Brasil A1/A3 certificate (PKCS#12). Without this, the XML is valid but cannot be
submitted.

**Decision for Sprint 6: ship as "generate + export XML, sign manually with clinic's
existing tool." In-app per-tenant certificate management deferred to Sprint 6b.**

This is sufficient for the pilot demo (the clinic owner can use their existing ICP
tool to sign the exported batch XML). Sprint 6b will add: per-tenant cert upload,
PKCS#12 storage (encrypted), and automatic signing on export.

**Required action before pilot:** confirm with the clinic owner that they have an
existing ICP-Brasil signing tool (AssistenteXML, PortalANS client, etc.) and that
"generate XML, sign manually" is acceptable for the pilot period. Document this
explicitly in the pilot agreement. Sprint 6b must have a committed date before Sprint 6
ships to the clinic.

### Gate 4: `django.contrib.postgres` (BLOCKING — fix before any migration)
`SearchVectorField` and `GinIndex` (used for TUSS fuzzy search) require
`django.contrib.postgres` in `INSTALLED_APPS`. It is currently absent from
`backend/vitali/settings/base.py`.

**Fix: add `"django.contrib.postgres"` to `SHARED_APPS` in `base.py`.**

```python
SHARED_APPS = [
    "django_tenants",
    "apps.core",
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.postgres",   # ← add this
    ...
]
```

This is a pre-S-021 task. Without it, `makemigrations` for TUSSCode crashes.

### Gate 5: MinIO / Django Storages (required for S-023 batch download)
`base.py` has `MEDIA_ROOT` set but no `DEFAULT_FILE_STORAGE` override. The S-023 batch
XML download endpoint requires a storage backend.

**Decision for Sprint 6 dev:** use `FileSystemStorage` (default) in development, write
batch XML to `MEDIA_ROOT/billing/batches/`. The download endpoint returns a direct URL.

**For production:** configure `django-storages` with MinIO/S3. Add to `pyproject.toml`:
```
django-storages[s3] = "^1.14"
boto3 = "^1.34"
```
Set in `settings/production.py`:
```python
DEFAULT_FILE_STORAGE = "storages.backends.s3boto3.S3Boto3Storage"
AWS_S3_ENDPOINT_URL = env("MINIO_ENDPOINT_URL")
AWS_ACCESS_KEY_ID = env("MINIO_ACCESS_KEY")
AWS_SECRET_ACCESS_KEY = env("MINIO_SECRET_KEY")
AWS_STORAGE_BUCKET_NAME = "vitali-billing"
```

This is a pre-S-023 task. The download endpoint must work in dev (local file) and
production (MinIO) without code changes — use `default_storage` from `django.core.files.storage`.

---

## Architecture

### Database Models

**`apps.core` (public schema — shared)**

```python
# apps/core/models.py — add TUSSCode

class TUSSCode(models.Model):
    """ANS TUSS procedure/material/fee code table. Shared across all tenants."""
    code = models.CharField(max_length=20, unique=True, db_index=True)
    description = models.TextField()
    group = models.CharField(max_length=100)  # procedimento, material, diaria, taxa, etc.
    subgroup = models.CharField(max_length=100, blank=True)
    version = models.CharField(max_length=20)  # e.g. "2024-01"
    active = models.BooleanField(default=True)
    search_vector = SearchVectorField(null=True)  # pg_trgm + tsvector for fuzzy

    class Meta:
        app_label = "core"
        indexes = [GinIndex(fields=["search_vector"])]
```

**`apps.billing` (tenant schema — per-clinic)**

```python
# apps/billing/models.py — new file

from django.db import models
from django.core.validators import MinValueValidator
from apps.core.models import TUSSCode
from apps.emr.models import Encounter, Patient

# -- Guide lifecycle --
GUIDE_STATUS = [
    ("draft", "Rascunho"),
    ("pending", "Pendente envio"),
    ("submitted", "Enviado"),
    ("paid", "Pago"),
    ("denied", "Glosado"),
    ("appeal", "Em recurso"),
]

BATCH_STATUS = [
    ("open", "Aberto"),
    ("closed", "Fechado"),
    ("submitted", "Enviado"),
    ("processed", "Processado"),
]

class InsuranceProvider(models.Model):
    name = models.CharField(max_length=200)
    ans_code = models.CharField(max_length=20)  # código ANS da operadora
    cnpj = models.CharField(max_length=18, blank=True)

class PriceTable(models.Model):
    provider = models.ForeignKey(InsuranceProvider, on_delete=models.CASCADE,
                                  related_name="price_tables")
    name = models.CharField(max_length=100)
    valid_from = models.DateField()
    valid_until = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = [("provider", "valid_from")]  # one table per provider per start date

    def clean(self):
        # Codex finding: unique_together only prevents same start date, not overlapping windows
        # (Jan–June + March–December would both pass unique_together)
        if self.valid_until:
            qs = PriceTable.objects.filter(provider=self.provider).exclude(pk=self.pk)
            for other in qs:
                if other.valid_until is None or other.valid_until >= self.valid_from:
                    if self.valid_until is None or self.valid_from <= other.valid_from:
                        raise ValidationError(
                            f"Tabela de preços sobrepõe período com '{other.name}'"
                        )

class PriceTableItem(models.Model):
    table = models.ForeignKey(PriceTable, on_delete=models.CASCADE, related_name="items")
    tuss_code = models.ForeignKey(TUSSCode, on_delete=models.PROTECT)
    negotiated_value = models.DecimalField(max_digits=10, decimal_places=2,
                                            validators=[MinValueValidator(0)])

    class Meta:
        unique_together = [("table", "tuss_code")]  # no duplicate codes per table (Codex #5)

class TISSGuide(models.Model):
    guide_number = models.CharField(max_length=20, unique=True)  # auto-generated, see note
    guide_type = models.CharField(max_length=20,
                                   choices=[("sadt", "SP/SADT"), ("consulta", "Consulta")])
    encounter = models.ForeignKey(Encounter, on_delete=models.PROTECT,
                                   related_name="tiss_guides")
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT)
    provider = models.ForeignKey(InsuranceProvider, on_delete=models.PROTECT)
    price_table = models.ForeignKey(PriceTable, on_delete=models.SET_NULL, null=True)
    status = models.CharField(max_length=20, choices=GUIDE_STATUS, default="draft")
    xml_content = models.TextField(blank=True)  # generated XML fragment
    total_value = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    # TISS mandatory fields (required for XSD validation — eng review finding)
    insured_card_number = models.CharField(max_length=20)  # número carteirinha do beneficiário
    authorization_number = models.CharField(max_length=20, blank=True)  # senha de autorização
    competency = models.CharField(max_length=7)  # YYYY-MM (competência do lote)
    cid10_codes = models.JSONField(default=list)  # from SOAPNote, list of {"code": "X00"}
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def generate_guide_number(self):
        # Sequential per tenant: YYYYMM + 6-digit seq, protected with select_for_update
        # Use: with transaction.atomic(): last = TISSGuide.objects.select_for_update()...
        ...

class TISSGuideItem(models.Model):
    guide = models.ForeignKey(TISSGuide, on_delete=models.CASCADE, related_name="items")
    tuss_code = models.ForeignKey(TUSSCode, on_delete=models.PROTECT)
    description = models.CharField(max_length=300)
    quantity = models.DecimalField(max_digits=8, decimal_places=2, default=1)
    unit_value = models.DecimalField(max_digits=10, decimal_places=2)
    total_value = models.DecimalField(max_digits=12, decimal_places=2)

class TISSBatch(models.Model):
    batch_number = models.CharField(max_length=20, unique=True)  # lote number
    provider = models.ForeignKey(InsuranceProvider, on_delete=models.PROTECT)
    guides = models.ManyToManyField(TISSGuide, related_name="batches")
    status = models.CharField(max_length=20, choices=BATCH_STATUS, default="open")
    xml_file = models.CharField(max_length=500, blank=True)  # MinIO path
    total_value = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True)

GLOSA_REASON_CODES = [
    # ANS standard reason codes — subset
    ("00", "Não informado"),
    ("01", "Procedimento não coberto"),
    ("02", "Incompatibilidade de sexo"),
    ("03", "Incompatibilidade de idade"),
    ("04", "Prazo de carência"),
    ("05", "Inconsistência nos dados do beneficiário"),
    ("99", "Outro"),
]

class Glosa(models.Model):
    guide = models.ForeignKey(TISSGuide, on_delete=models.CASCADE, related_name="glosas")
    guide_item = models.ForeignKey(TISSGuideItem, on_delete=models.SET_NULL,
                                    null=True, blank=True)
    reason_code = models.CharField(max_length=5, choices=GLOSA_REASON_CODES)
    reason_description = models.TextField()
    value_denied = models.DecimalField(max_digits=12, decimal_places=2)
    appeal_status = models.CharField(max_length=20,
                                      choices=[("none", "Sem recurso"),
                                               ("filed", "Recurso enviado"),
                                               ("accepted", "Recurso aceito"),
                                               ("rejected", "Recurso rejeitado")],
                                      default="none")
    appeal_text = models.TextField(blank=True)
    appeal_filed_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
```

**`apps.emr` (tenant schema — cherry-pick from CEO review)**

```python
# apps/emr/models.py — add PatientInsurance (new model, CEO review cherry-pick)
from django_encrypted_fields.fields import EncryptedCharField  # LGPD pattern

class PatientInsurance(models.Model):
    """Patient's insurance card data. Stored per tenant."""
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE,
                                related_name="insurance_cards")
    # provider_ans_code as CharField (NOT FK to apps.billing.InsuranceProvider)
    # Rationale: avoids apps.emr → apps.billing circular dependency inversion
    # Look up InsuranceProvider separately in the guide creation view using ans_code
    provider_ans_code = models.CharField(max_length=20)  # código ANS da operadora
    provider_name = models.CharField(max_length=200)     # denormalized for display
    card_number = EncryptedCharField(max_length=50)      # carteirinha (LGPD — PII)
    valid_until = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-is_active", "-created_at"]
```

Key architecture decisions:
- `provider_ans_code` is a plain `CharField`, not an FK to `InsuranceProvider`. This keeps
  `apps.emr` free of any dependency on `apps.billing`.
- `card_number` uses `EncryptedCharField` (LGPD — PHI, same encryption pattern as other
  PII fields in core). The guide creation view reads the decrypted value and copies it
  to `TISSGuide.insured_card_number` (stored unencrypted in billing — acceptable per TISS
  spec since guide XML contains it in plaintext anyway).
- Migration: `apps/emr/migrations/000X_add_patientinsurance.py` — normal tenant migration.

---

### XML Generation

Jinja2 templates under `backend/apps/billing/templates/tiss/`:
- `batch_envelope.xml.j2` — TISS 4.01.00 lote wrapper
- `sadt_guide.xml.j2` — SP/SADT guide fragment
- `consulta_guide.xml.j2` — consultation guide fragment

XSD validation via `lxml` against the official ANS schema:
```python
# apps/billing/services/xml_engine.py
from lxml import etree

from pathlib import Path
# Use absolute path — relative paths break when cwd is not the project root (eng review)
TISS_XSD_PATH = Path(__file__).parent.parent / "schemas" / "tissV4_01_00.xsd"

def validate_xml(xml_string: str) -> list[str]:
    """Returns list of validation errors, empty = valid."""
    schema = etree.XMLSchema(file=str(TISS_XSD_PATH))
    doc = etree.fromstring(xml_string.encode())
    schema.validate(doc)
    return [str(e) for e in schema.error_log]
```

### API Endpoints

All under `/api/v1/billing/`. Auth required. Permission: `faturista` or `admin`.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET/POST | `/tuss/` | TUSS code search |
| GET/POST | `/guides/` | List / create TISS guides |
| GET/PUT/PATCH | `/guides/{id}/` | Guide detail / update |
| POST | `/guides/{id}/generate-xml/` | Generate XML for guide |
| GET/POST | `/batches/` | List / create batches |
| GET | `/batches/{id}/download/` | Download batch XML file |
| GET/POST | `/glosas/` | List / create glosas |
| GET/PUT/PATCH | `/glosas/{id}/` | Glosa detail / appeal |
| GET/POST | `/price-tables/` | List / create price tables |
| GET/POST | `/price-tables/{id}/items/` | Price table items |
| GET/POST | `/providers/` | Insurance providers |

### Frontend Pages

New pages under `frontend/app/(dashboard)/billing/`:

```
billing/
  page.tsx               — billing dashboard
  guides/
    page.tsx             — guide list with status filter
    new/page.tsx         — create guide from encounter (single-page form)
    [id]/page.tsx        — guide detail + XML preview
  batches/
    page.tsx             — batch management
    [id]/page.tsx        — batch detail + download
  glosas/
    page.tsx             — glosa management + appeal
  price-tables/
    page.tsx             — price table configuration
    [id]/page.tsx        — table items
```

**Routing fix (design review):** `DashboardShell.tsx` nav item for billing uses `href: "/dashboard/faturamento"`. Change to `href: "/billing"` to match the route structure above. All other nav items (`/patients`, `/appointments`) use root-relative paths — billing must match.

**Routing fix — explicit task (plan-design-review):**
- [ ] `DashboardShell.tsx:40` — change `href: "/dashboard/faturamento"` → `href: "/billing"`. Without this the active-state highlight never fires and the link 404s. Must ship with S-022.

**Page-level auth (plan-design-review):**
- [ ] `app/(dashboard)/billing/layout.tsx` — create a billing layout that checks `user.active_modules.includes('billing')`. If not present, redirect to `/dashboard`. Use same cookie-read pattern as `(dashboard)/layout.tsx`. Applies to all routes under `/billing/`. This protects direct URL navigation by non-billing roles.

Roles shown in nav: `faturista`, `admin`. Hidden for `medico`, `enfermeiro`, `recepcionista`.

---

### Faturista User Journey (plan-design-review — Pass 3)

**Persona:** Faturista — billing specialist. Deals with glosas (rejected claims) daily. Core goal: minimize denied revenue, close monthly batches on time. Moderate technical skill, high domain expertise.

**Primary morning loop (5-sec → 5-min → 5-year):**
1. Opens `/billing` → immediately sees Glosas este Mês in red → clicks → goes to `/billing/glosas`
2. Reviews each glosa, files appeals for recoverable ones
3. Returns to `/billing/guides` → filters by `status=pending` → selects this week's guides
4. Clicks "Criar Lote com Selecionadas" → closes batch → downloads XML → signs externally
5. Uploads retorno XML from previous batch → sees "X guias pagas, Y glosas criadas" summary

**Post-encounter billing loop (triggered by medico completing a consultation):**
1. Medico finishes encounter, encounter detail shows `[Criar Guia TISS →]` button
2. Faturista (or medico if authorized) opens guide creation form pre-filled with encounter
3. Selects insurer, adds procedure codes, saves guide as draft
4. Later: guide moves to `pending` when ready for batch

---

### Interaction State Coverage (plan-design-review — Pass 2)

| Screen | Loading | Empty | Error | Success |
|--------|---------|-------|-------|---------|
| Billing Dashboard | Skeleton stat card numbers (`w-16 h-8 animate-pulse rounded`); skeleton guide table rows (5 rows) | "Nenhuma guia criada ainda." + primary `[Criar Guia →]` button | Top-of-page `bg-red-50 border border-red-200 rounded-xl px-4 py-3 text-sm text-red-700` error banner | — |
| Guide List | Skeleton 10 rows (same pattern as `patients/page.tsx`) | "Nenhuma guia encontrada." + if filter active: "Tente outro filtro." + `[Criar Guia →]` | Toast error (top-right) | — |
| Guide Create | Spinner (16px) inside encounter search input (right side); spinner inside TUSS combobox (right side) | PatientInsurance missing → inline "Cadastrar Carteirinha" expandable section (already spec'd) | Field validation: inline `text-xs text-red-500 mt-1`; XML generation failure: `bg-red-50 rounded-xl p-4` error block — each error on its own line prefixed with `<code className="font-mono text-xs">elementName</code>`: e.g. "codigoProcedimento: valor inválido" | "Guia {number} criada com sucesso." toast + redirect to guide detail |
| Batch List | Skeleton 5 rows | "Nenhum lote criado ainda. Selecione guias na lista de guias e clique 'Criar Lote com Selecionadas'." with arrow illustration | — | — |
| Batch Detail | — | Batch has 0 guides: `bg-yellow-50 rounded-xl p-4 text-sm text-yellow-700` "Lote vazio. Adicione guias antes de fechar." | Retorno upload invalid: `bg-red-50 rounded-xl p-4` "Arquivo inválido — não é um retorno TISS válido. Erros: {list}" | Retorno success: `bg-green-50 rounded-xl` summary (spec'd) |
| Glosas | Skeleton 5 rows | `bg-green-50 rounded-xl p-6 text-center`: "Nenhuma glosa registrada. Continue assim!" | — | Appeal filed: status badge updates inline to `bg-orange-50 text-orange-700` "Recurso enviado" (optimistic update) |
| Price Tables | Skeleton accordion rows | "Nenhuma tabela de preços cadastrada. [Nova Tabela →]" | Date overlap validation: `text-xs text-red-500` inline below `valid_until` field | — |

---

### Screen Hierarchy Specs (design review — Pass 1)

**`billing/page.tsx` — Billing Dashboard**
```
1. Page header: "Faturamento" (text-2xl font-semibold) | subtitle: dynamic current competency month (text-sm text-gray-500): `new Intl.DateTimeFormat('pt-BR', { month: 'long', year: 'numeric' }).format(new Date())` — e.g. "março de 2026"
         [Criar Guia →]  ← primary action always visible
2. Stat cards row (4 cards, bg-white rounded-xl border):
   - Guias Pendentes: count + "enviar para operadora" hint → links to `/billing/guides?status=pending`
   - Glosas este mês: R$ value in RED (most urgent, clinic pain point) → links to `/billing/glosas`
   - Lotes Abertos: count → links to `/billing/batches?status=open`
   - Receita Enviada: R$ value (positive, green) → links to `/billing/batches?status=submitted`
   All 4 cards are clickable links (anchor tags wrapping the card, hover: shadow-md transition).
   Visual priority: Glosas card gets red accent border-l-4 border-red-500 (only exception to app UI rules)
   Keyboard accessible: cards are `<a>` elements with `focus:ring-2 focus:ring-blue-500`
3. Recent guides table (last 10): guide_number | patient | operadora | type | value | status_badge
   - Status badge system: see Design System section below
   - "Ver todas as guias →" link at table bottom
4. Open batches section (compact list, 3 items max): lote_number | guide_count | competência | status
   "Ver todos os lotes →" link
```

**`billing/guides/page.tsx` — Guide List**
```
1. Page header: "Guias TISS" | subtitle: "{count} guias"
         [Criar Guia →]  ← always visible
2. Filter bar: [Status: Todos v] [Operadora: Todas v] [Competência: v] [Buscar guia #...]
3. Guides table: guide_number | patient_name | insurer | competency | total_value | status_badge | [actions]
   - Default sort: updated_at desc (most recent activity first)
   - Row click → guide detail
   - Checkbox column for bulk batch creation (see batch UX note)
4. "Criar Lote com Selecionadas" sticky footer bar: appears when 1+ checkboxes checked
   Shows: "3 guias selecionadas — R$1.420,00 total → [Criar Lote]"
```

**`billing/guides/new/page.tsx` — Create Guide (single-page form, design review)**
```
1. Page header: "Nova Guia TISS"     [← Voltar]
2. Section: Consulta (encounter selector)
   [Buscar consulta por paciente ou data...]    [Tipo de guia: SP/SADT v]
3. Auto-populated patient info strip (appears after encounter selected):
   bg-slate-50 rounded-lg border border-slate-200 px-4 py-3  ← NOT a prominent card, a data strip
   - Patient: full_name font-medium | MR: number text-slate-500 | Data: encounter.date
   - CID-10 chips inline: `<span class="px-1.5 py-0.5 bg-slate-200 text-slate-600 text-xs rounded">`
   - Carteirinha: ••••••••• [EDIT link text-blue-600] (auto-populated from PatientInsurance, editable)
   - Competência: YYYY-MM text-slate-500 (read-only, auto-derived)
   PatientInsurance exists → show masked card: ••••••••••• + [EDIT link]
   PatientInsurance missing → show inline "Cadastrar Carteirinha" expandable section:
     - Fields: Nº do Cartão (card_number) + Operadora (pre-selected from guide's operadora if set)
     - [Salvar Carteirinha] → POST /api/v1/emr/patients/{id}/insurance/
     - On success: section collapses, carteirinha shows as ••••••••• [EDIT]
     - API endpoint POST /api/v1/emr/patients/{id}/insurance/ must be added to S-022 tasks
4. Two selects in a row (not a card — just a form row with labels):
   [Operadora *] ← dropdown, REQUIRED, red asterisk
   [Tabela de Preços] ← dropdown, optional, auto-selects active table for provider
   Note: operadora NOT auto-populated — manual selection required (Codex finding)
5. Procedures section — PRIMARY work area, full-width, bg-white, no nested card:
   h3 "Procedimentos" font-semibold text-slate-900 mb-3
   [+ Buscar código TUSS...] ← TUSSCodeSearch combobox full-width, debounced 300ms
   Table: Código | Descrição | Qtd | Valor Unit. | Total | [×]
   - Unit value: auto-fills from price table + "Da tabela ✓" hint text-xs text-green-600
   - Manual override: unit value is editable even when auto-filled
   - Running total: right-aligned below table, text-xl font-semibold text-slate-900
6. Sticky footer bar (bottom-0, bg-white border-t border-slate-200 px-6 py-3):
   [Salvar Rascunho]  (secondary, outlined)    [Gerar XML e Enviar →]  (primary, blue-600)
```

**`billing/guides/[id]/page.tsx` — Guide Detail**
```
1. Page header: "Guia #{guide_number}" | status_badge | [actions dropdown]
2. 2-column layout (lg:grid-cols-3):
   - Left 2/3: Guide info card + items table
   - Right 1/3: Status timeline (draft→pending→submitted→paid/denied)
3. XML Preview accordion (collapsed by default):
   - "Ver XML Gerado" expandable section
   - Monospace code block, syntax-highlighted XML
   - [Copiar XML] button (for manual ICP-Brasil signing)
   - Validation status: "✓ Válido — 0 erros XSD" or error list
4. Glosas section (only shown if status=denied): list of glosa records with appeal CTA
```

**`billing/batches/page.tsx` — Batch Management**
```
1. Page header: "Lotes TISS" | [Criar Lote →] (from guide list checkboxes, not here)
2. Batch list: lote_number | competência | provider | guide_count | total_value | status_badge | [download/upload]
3. Status: open=gray, closed=blue, submitted=yellow, processed=green
```

**`billing/batches/[id]/page.tsx` — Batch Detail**
```
1. Page header: "Lote #{batch_number}" | status_badge
2. Batch summary: operadora | competência | N guias | R$ total
3. Guides in batch: read-only list (guide_number | patient | value | status)
4. Actions section:
   - [Fechar Lote + Gerar XML] (only if status=open)
   - [⬇ Baixar XML] (if closed/submitted) — streams file via FileResponse
   - [⬆ Enviar Retorno TISS] (if submitted) — file input for retorno XML upload
5. Retorno result summary (appears after upload):
   bg-green-50 rounded-xl: "X guias pagas, Y glosas criadas"
```

**`billing/glosas/page.tsx` — Glosa Management**
```
1. Page header: "Glosas" | analytics row (total denied, open appeals, accepted)
2. Glosa list: guide_number | patient | reason_code+description | value_denied | appeal_status | [Recorrer]
3. Filter: [Operadora v] [Motivo v] [Status recurso v]
```

**`billing/price-tables/page.tsx` — Price Tables (admin only)**
```
1. Page header: "Tabelas de Preços" | [Nova Tabela →]
2. Provider accordion: each InsuranceProvider expands to show its price tables
3. Table row: name | valid_from-valid_until | item_count | active badge | [Editar] [Ver Itens]
```

---

### Status Badge Design System (design review — Pass 5)

All 6 guide statuses and 4 batch statuses use this token set:

| Status | BG | Text | Border | Label PT |
|--------|-----|------|--------|----------|
| draft | `bg-slate-100` | `text-slate-600` | — | Rascunho |
| pending | `bg-yellow-50` | `text-yellow-700` | `border border-yellow-200` | Pendente |
| submitted | `bg-blue-50` | `text-blue-700` | `border border-blue-200` | Enviado |
| paid | `bg-green-50` | `text-green-700` | `border border-green-200` | Pago |
| denied | `bg-red-50` | `text-red-700` | `border border-red-200` | Glosado |
| appeal | `bg-orange-50` | `text-orange-700` | `border border-orange-200` | Em Recurso |

Component: `<StatusBadge status={guide.status} />` — shared across all billing screens.
Size: `px-2 py-0.5 rounded-full text-xs font-medium`.

**Currency formatting (design review — all billing screens):**
- Use Brazilian format throughout: `R$\u00a01.200,00` (dot thousands separator, comma decimal)
- Helper: `formatBRL(value: number) → string` using `Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' })`
- Never use `$` or US number format anywhere in billing UI
- Stat card values: `text-2xl font-bold` for the amount, `text-xs text-slate-500` for the label above
- Total in guide form: `text-xl font-semibold` — not `text-2xl` (would overpower the page header)

**TUSSCodeSearch component spec (design review — new component):**
```tsx
// components/billing/TUSSCodeSearch.tsx
// Combobox, debounced 300ms, shows top 10 results
// Result item: code (monospace text-xs text-slate-500) + description (text-sm)
// Keyboard: arrow keys navigate, Enter selects, Esc closes
// On selection: calls onSelect(tussCode), input clears and focuses back
// Loading state: spinner inside input (right side)
// Empty state: "Nenhum código encontrado para '{query}'"
// Width: full-width of its container
// Dropdown: absolute positioned popover, z-50, bg-white rounded-xl border border-gray-200
//   shadow-lg, max-h-64 overflow-y-auto. Appears BELOW the input, full width.
//   Close on: Esc, click outside, selection. Open on: input focus + min 2 chars typed.
```

**StatusBadge component (design review — Pass 5):**
```tsx
// components/billing/StatusBadge.tsx
// Single shared badge used across all billing screens.
// Props: status: keyof typeof BADGE_MAP
// Size: px-2 py-0.5 rounded-full text-xs font-medium (as specified in badge table above)
```

**Competência filter spec (design review — Pass 5):**
```tsx
// The [Competência: v] filter in guide list is a <select> populated with the last
// 12 months in YYYY-MM format, formatted as "Mar/2026" for display.
// Generated client-side: Array.from({length: 12}, (_, i) => {
//   const d = new Date(); d.setMonth(d.getMonth() - i);
//   return { value: `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}`,
//            label: d.toLocaleDateString('pt-BR', {month: 'short', year: 'numeric'}) }
// })
// Default: empty string = "Todos os meses" (no filter applied)
```

**Billing utilities (design review — Pass 5):**
```ts
// frontend/lib/billing.ts — shared billing utilities
// export formatBRL(value: number): string
//   → Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(value)
// export formatCompetency(yyyyMM: string): string
//   → e.g. "2026-03" → "Mar/2026"
// export GUIDE_STATUS_LABELS: Record<string, string>
//   → maps status keys to Portuguese labels
```

### Responsive & Accessibility Spec (plan-design-review — Pass 6)

**Guide List — responsive:**
- `sm` (< 768px): card list. Each guide renders as:
  ```
  bg-white rounded-xl border border-gray-200 px-4 py-3
  [checkbox]  [patient_name font-medium] [status_badge float-right]
              [guide_number text-xs text-slate-500] [R$ value text-sm]
  ```
- `md+` (≥ 768px): full table (7 columns + checkbox).
- Implementation: `hidden md:table` on `<table>`, `md:hidden` on card list wrapper.

**Bulk batch sticky footer — responsive:**
- `sm` (< 768px): bottom sheet. Slides up from screen bottom (`translate-y-full` → `translate-y-0` transition-300ms). Full-width, `bg-white border-t border-slate-200 px-4 py-4 rounded-t-xl shadow-lg`. Content: guide count (large) + total value + `[Criar Lote]` full-width button.
- `md+`: sticky bar at bottom of viewport: `fixed bottom-0 inset-x-0 bg-white border-t border-slate-200 px-6 py-3 flex items-center justify-between`. Same content, inline layout.
- Both viewports: add `pb-20` to the guide list container when bar is visible to prevent last row overlap.

**Guide creation form — responsive:**
- Form sections stack vertically on all viewports (single column).
- Provider + price table selects: `flex gap-4` on `md+`, stacked on `sm`.
- Procedures table: on `sm`, hide "Valor Unit." column, show only Código + Descrição + Qtd + Total + [×].

**Guide detail — responsive:**
- 2-column layout (`lg:grid-cols-3`): on `sm`/`md`, single column. Status timeline moves below guide info.
- XML preview accordion: always full-width. On `sm`, code block has `max-h-64 overflow-y-auto`.

**Accessibility — all billing screens:**
- Keyboard navigation: tab order follows visual order. Interactive elements have `focus:ring-2 focus:ring-blue-500 focus:ring-offset-2`.
- `StatusBadge`: include `aria-label={guide.get_status_display()}` for screen readers.
- Stat cards (dashboard): wrap each in `<a>` with `aria-label="X guias pendentes — ver lista"`.
- Guide table checkboxes: `aria-label="Selecionar guia {guide_number}"`. Header checkbox: `aria-label="Selecionar todas as guias visíveis"`.
- Sticky/bottom-sheet footer: `role="status" aria-live="polite"` so screen readers announce selection count changes.
- Touch targets: all interactive elements minimum 44×44px (Tailwind: `min-h-[44px] min-w-[44px]`). Applies to: table action buttons, badge clicks, accordion toggles.
- Color contrast: all status badge text meets WCAG AA (4.5:1). Verify: red-700 on red-50 ✓, green-700 on green-50 ✓, yellow-700 on yellow-50 ✓.

### Unresolved Design Decisions (plan-design-review — Pass 7)

**Decision 7a: Post-XML-generation flow**
After `POST /billing/guides/{id}/generate-xml/` succeeds, show a toast with two action buttons:
- `[↓ Baixar XML]` — triggers immediate file download (guide's individual XML)
- `[→ Ver no lote #XXXXXX]` — navigates to the batch detail page with this guide's row highlighted (`?highlight={guide_id}` query param → yellow `bg-yellow-50` row for 3s then fades)
Implementation: `GuideDetailPage.tsx` — on successful `mutate()` response, call `window.URL.createObjectURL()` for the download, then show the toast via `useToast()`. Batch link is derived from `guide.batch` FK (if guide is not yet in a batch, show only `[↓ Baixar XML]` + `[+ Adicionar ao lote]` link to `/billing/batches/new?guide={id}`).

**Decision 7b: Retorno upload on batch detail**
On `BatchDetailPage`, show a drag-and-drop upload zone **only when batch status is `closed` or `submitted`** (not `open`, not `processed`):
```
border-2 border-dashed border-slate-300 rounded-xl p-6 text-center
bg-slate-50 hover:bg-slate-100 transition-colors cursor-pointer
```
Text: "↑ **Enviar retorno do convênio** / Arraste o .xml ou clique para selecionar"
Accept: `.xml` only (`accept=".xml"`). On drop: call `POST /api/v1/billing/batches/upload-retorno/` with `multipart/form-data`. On success: show summary toast "X guias atualizadas, Y glosas registradas". On error: show each error as a red `<li>`. Zone disappears when batch status becomes `processed`.

**Decision 7c: "Criar Guia TISS" entry point on encounter detail**
Add a `Faturamento` card as the **last section** of the encounter detail page (`app/(dashboard)/emr/encounters/[id]/page.tsx`):
```
bg-white rounded-xl border border-gray-200 px-6 py-4
h2: "Faturamento"  class="text-base font-semibold text-gray-900 mb-3"
```
States:
- **No guides:** "Nenhuma guia TISS criada para esta consulta." + `[+ Criar Guia TISS →]` (blue primary button, `href="/billing/guides/new?encounter={id}"`)
- **1+ guides:** list each as `Guia #{number} — {StatusBadge} → ` (link to guide detail) + `[+ Nova Guia]` ghost button
- **Role guard:** card only renders if `user.role` has `billing.read` permission. For `medico`/`enfermeiro` without billing access, card is hidden entirely (not 403 — just absent).

**Decision 7d: Price tables page layout**
`PriceTablesPage` (`/billing/price-tables`): group tables by provider. Provider name is a collapsible section header (`<details open>` initially). Search bar at top filters both provider names and table names client-side (debounced 200ms). Each provider shows table count in header: "Unimed Seguros (2 tabelas)". Tables within a provider: `name | valid_from–valid_until | ● ativa / arquivada | [→]` row. `[+ Nova Tabela]` button sits outside any group (always visible, floating right above the list).

---

## Stories

### S-021 — TUSS Code Database (5 pts)

**Acceptance criteria:**
- ANS TUSS CSV imported into `core_tusscode` table (public schema)
- Full-text + trigram fuzzy search: `GET /api/v1/billing/tuss/?q=hemograma` returns ranked results in < 200ms
- Version field tracks import date, `active` flag allows deprecation without deletion
- Reusable `<TUSSCodeSearch>` React component for use in guide creation form

**Tasks:**
- [ ] **Pre-task:** add `"django.contrib.postgres"` to `SHARED_APPS` in `base.py` (Gate 4 fix)
- [ ] **Pre-task:** verify `faturista` role seeded in `create_tenant` command; add if missing
- [ ] `TUSSCode` model in `apps/core/models.py`
- [ ] Migration: `apps/core/migrations/000X_add_tusscode.py` (run with `migrate_schemas --shared`)
  - Include `RunSQL("CREATE EXTENSION IF NOT EXISTS pg_trgm")` at migration start (Codex: required for trigram similarity, missing from plan)
  - Include `RunSQL("CREATE EXTENSION IF NOT EXISTS unaccent")` (needed for accent-insensitive search)
- [ ] Management command: `python manage.py import_tuss --file tuss.csv` (idempotent — ON CONFLICT DO UPDATE)
- [ ] TUSS search API: `GET /api/v1/billing/tuss/?q=&group=` (pg_trgm + tsvector, returns top 20)
- [ ] `GinIndex` on `search_vector` field
- [ ] Seed fixture: at least Unimed (ANS 00043753) and Bradesco Saúde (ANS 005711) as `InsuranceProvider`
- [ ] Pre-delete signal on `TUSSCode`: raise `ProtectedError` if referenced by active guide items
- [ ] Frontend: `TUSSCodeSearch` component (combobox with debounce, 300ms)
- [ ] Test: search "hemograma" returns code 40303616 in top 3 results
- [ ] Test: cross-schema read — create TUSSCode in public, query from tenant context
- [ ] Test: import command is idempotent (run twice = no duplicate rows)

**Notes:**
- Download TUSS CSV from dados.ans.gov.br (Tabela TUSS — Procedimentos e Eventos em Saúde)
- Import must be idempotent (run twice = no duplicate rows, update on code conflict)
- `group` values: procedimento_clinico, procedimento_cirurgico, material, medicamento,
  diaria, taxa, pacote — used for filtering in the guide form

---

### S-022 — TISS Guide Creation (13 pts)

**Acceptance criteria:**
- Faturista opens an encounter and creates a TISS SADT guide auto-populated with: patient data,
  insurer, CID-10 codes (from SOAPNote), procedures (empty — faturista adds TUSS items)
- Guide items: add TUSS code (via TUSSCodeSearch), quantity, unit value (auto-filled from price
  table if configured), total computed
- Guide generates valid TISS 4.01.00 XML (passes XSD validation, 0 errors)
- Scope: **SADT/ambulatory guides only** (consulta and SP/SADT guide types)
- Guide lifecycle: draft → pending → submitted → paid/denied

**Tasks:**
- [ ] `TISSGuide`, `TISSGuideItem`, `InsuranceProvider` models in `apps/billing/models.py`
- [ ] Migration: `apps/billing/migrations/0001_initial.py`
- [ ] Guide creation API: `POST /api/v1/billing/guides/` (auto-populate from encounter)
- [ ] Guide item CRUD: `POST/PUT/DELETE /api/v1/billing/guides/{id}/items/`
- [ ] Guide number generator: `YYYYMM{6-digit-seq}` sequential per tenant
- [ ] XML generation engine: `apps/billing/services/xml_engine.py`
  - `generate_sadt_guide_xml(guide: TISSGuide) -> str`
  - `generate_consulta_guide_xml(guide: TISSGuide) -> str`
  - `validate_xml(xml: str) -> list[str]` (XSD validation via lxml)
- [ ] Jinja2 templates: `sadt_guide.xml.j2`, `consulta_guide.xml.j2`
- [ ] TISS XSD schema file: `apps/billing/schemas/tissV4_01_00.xsd`
- [ ] `POST /api/v1/billing/guides/{id}/generate-xml/` — generates + stores XML fragment
- [ ] Status transition API: `POST /api/v1/billing/guides/{id}/transition/` (with lifecycle validation)
  - On every status change, write to `AuditLog` (Codex: billing state is financial record, must be auditable): `AuditLog.objects.create(tenant=..., user=request.user, action=f"guide_{guide.guide_number}_status_{old}→{new}", extra={...})`
- [ ] Frontend: `billing/guides/new/page.tsx` — single-page form (encounter selector, patient card, insurer, items table)
  - Accept `?encounter_id=<id>` query param to pre-select encounter (used by encounter detail page button)
- [ ] Frontend: `billing/guides/page.tsx` — guide list with status badges + filters
  - Checkbox column + sticky "Criar Lote com Selecionadas" footer bar for bulk batch creation
- [ ] Frontend: `billing/guides/[id]/page.tsx` — guide detail with XML preview accordion + [Copiar XML] button
- [ ] **Cross-module task:** Add `[Criar Guia TISS →]` button to `app/(dashboard)/encounters/[id]/page.tsx`
  - Shown when `user.active_modules.includes("billing")` AND encounter has no existing guide
  - Navigates to `/billing/guides/new?encounter_id={encounter.id}`
  - This is a Sprint 6 task — do not defer (it's the primary morning billing entry point)
- [ ] `POST /api/v1/emr/patients/{id}/insurance/` — create PatientInsurance record (used by inline form on guide creation)
- [ ] Test: create guide from fixture encounter → generate XML → XSD validate → 0 errors
- [ ] Test: status transition out-of-order (pending → draft) rejected with 400
- [ ] Test: guide creation with PatientInsurance missing → inline form saves card → guide gets card number

**Notes:**
- Auto-populate logic: encounter.soapnote.cid10_codes → TISSGuide.cid10; encounter.patient →
  TISSGuide.patient
- **Insurer auto-lookup (Codex finding):** `encounter.appointment.provider` links to
  `Professional`, NOT `InsuranceProvider`. There is no automatic path from encounter to
  insurer. Guide creation form MUST include a manual insurer selector. Do not attempt
  to auto-populate the insurance provider field from the encounter.
- Price table auto-fill: when guide has a price_table, adding a TISSGuideItem auto-fills
  unit_value from PriceTableItem.negotiated_value if the TUSS code exists
- `insured_card_number` must come from `PatientInsurance` model (see Architecture section)
  or manual entry. Not on the Encounter model.

---

### S-023 — Batch XML Export (5 pts)

**Acceptance criteria:**
- Faturista selects guides (status=pending) and creates a batch
- Batch generates a single TISS 4.01.00 XML envelope containing all guide fragments
- Batch XML stored in MinIO, download link generated (pre-signed URL, 24h expiry)
- Batch status: open → closed (on XML generation) → submitted (manual update)

**Tasks:**
- [ ] `TISSBatch` model in `apps/billing/models.py`
- [ ] `POST /api/v1/billing/batches/` — create batch with list of guide IDs
- [ ] Batch XML engine: `generate_batch_xml(batch: TISSBatch) -> str`
  - Wraps individual guide XML fragments in TISS envelope
  - Calculates `valorTotalGeral`, guide count, transaction date
- [ ] Jinja2 template: `batch_envelope.xml.j2`
- [ ] MinIO file storage: `billing/batches/{batch_number}.xml` (or S3-compatible)
- [ ] `GET /api/v1/billing/batches/{id}/download/` — returns pre-signed download URL
- [ ] Batch number generator: `L{YYYYMM}{4-digit-seq}`
- [ ] Frontend: `billing/batches/page.tsx` — batch list, create batch (guide selector)
- [ ] Frontend: `billing/batches/[id]/page.tsx` — batch detail + download button
- [ ] Test: create batch with 2 guides → generate XML → XSD validate envelope → download link 200
- [ ] Test: batch rejects guide with status != pending

**Notes:**
- TISS envelope root element: `mensagemTISS` with `cabecalho` (transactionType, sequence number,
  sender/receiver registrationNumber, destination, date, time, competency)
- Batch number (lote) must be sequential per provider per competency month
- Guides must be marked `submitted` after batch is closed (status transition)

---

### S-023b — Retorno TISS Upload (5 pts) [CEO review cherry-pick]

**Why this sprint:** The convênio sends back a "retorno" XML after processing a batch.
Without parsing it, the faturista must update guide statuses (paid/denied) manually.
With it, one XML upload auto-populates glosas and marks guides paid. This is the difference
between billing that's useful and billing that's annoying.

**Acceptance criteria:**
- Faturista uploads a Retorno TISS XML file (convênio response to a submitted batch)
- System parses the XML, matches guides by guide number, creates `Glosa` records for denied
  items and transitions those guides to `denied`
- Paid guides (no glosa) transition to `paid`
- Upload result summary: X guides paid, Y guides denied, Z glosas created

**Tasks:**
- [ ] Download Retorno TISS XSD from ANS — `tissRetorno4_01_00.xsd` (separate from submission XSD)
  - Place at `apps/billing/schemas/tissRetorno4_01_00.xsd`
  - **Note: verify correct version as part of Gate 1 (same browse session as submission XSD)**
- [ ] `RetornoTISSParser` service: `apps/billing/services/retorno_parser.py`
  - Parse `<mensagemTISS>` retorno envelope
  - Extract per-guide: `numeroGuiaPrestador`, status, paid amount, glosa items with reason codes
  - Validate XML against `tissRetorno4_01_00.xsd` before processing
- [ ] `POST /api/v1/billing/batches/{id}/retorno/` — upload + parse retorno XML
  - Returns: `{"guides_paid": N, "guides_denied": M, "glosas_created": K, "errors": [...]}`
- [ ] Status transitions from retorno: guide → paid (full payment), guide → denied (any glosa)
- [ ] Glosa auto-creation from retorno parser output
- [ ] Frontend: upload button on `billing/batches/[id]/page.tsx` — file input + results modal
- [ ] Test: `test_retorno.py`
  - `test_retorno_xml_parsed_correctly` — fixture retorno XML → correct guide status transitions
  - `test_retorno_creates_glosas` — denied guide item → Glosa record created with correct reason code
  - `test_retorno_xsd_validation` — invalid XML rejected before processing

**Notes:**
- Store the raw retorno XML on the `TISSBatch` record (`retorno_xml_file = models.CharField(...)`)
  for audit trail — do not discard after parsing.
- Retorno XSD namespace may differ from submission XSD — verify during Gate 1 browse session.

---

### S-024 — Glosa Management (8 pts)

**Acceptance criteria:**
- Faturista records a glosa against a specific guide (and optionally a specific item)
- Appeal workflow: add appeal text → file appeal → track outcome (accepted/rejected)
- Glosa dashboard: total denied this month, top denial reason codes, denied by provider
- Guide status auto-transitions to `denied` when a glosa is created (if not already)

**Tasks:**
- [ ] `Glosa` model in `apps/billing/models.py`
- [ ] `POST /api/v1/billing/glosas/` — record glosa (guide_id, item_id optional, reason_code,
  value_denied, reason_description)
- [ ] `POST /api/v1/billing/glosas/{id}/appeal/` — file appeal (text required)
- [ ] `PATCH /api/v1/billing/glosas/{id}/appeal-outcome/` — record outcome (accepted/rejected)
- [ ] Glosa signal: on glosa create, transition guide to `denied` if not already
- [ ] Analytics endpoint: `GET /api/v1/billing/glosas/analytics/` — returns:
  ```json
  {
    "total_denied_value": "...",
    "count_by_reason": [...],
    "count_by_provider": [...],
    "monthly_trend": [...]
  }
  ```
- [ ] Frontend: `billing/glosas/page.tsx` — glosa list with filters (provider, reason, status)
  plus analytics summary cards (total denied, top reason, open appeals)
- [ ] Test: create glosa → guide status → denied
- [ ] Test: appeal workflow state machine (cannot appeal accepted glosa twice)
- [ ] Test: analytics endpoint returns correct totals for fixture data

---

### S-025 — Price Tables (5 pts)

**Acceptance criteria:**
- Admin configures a price table for an insurer (name, validity period)
- Add TUSS codes with negotiated values
- When a guide is created with a provider that has an active price table, items auto-fill values
- Multiple tables per provider (different competency periods), only one active at a time

**Tasks:**
- [ ] `PriceTable`, `PriceTableItem`, `InsuranceProvider` models
- [ ] `InsuranceProvider` CRUD: `GET/POST /api/v1/billing/providers/`
- [ ] `PriceTable` CRUD: `GET/POST /api/v1/billing/price-tables/`
- [ ] `PriceTableItem` bulk import: `POST /api/v1/billing/price-tables/{id}/items/bulk/`
  (accepts JSON array of `{tuss_code, negotiated_value}`)
- [ ] Price lookup service: `get_price(provider_id, tuss_code_id, date) -> Decimal | None`
- [ ] Auto-fill hook in guide item creation
- [ ] Frontend: `billing/price-tables/page.tsx` — provider + table management
- [ ] Frontend: `billing/price-tables/[id]/page.tsx` — table items with inline edit
- [ ] Test: price lookup returns active table value, ignores expired table
- [ ] Test: guide item auto-fills value when price table exists

---

## Billing Dashboard (`billing/page.tsx`)

Visible to `faturista` and `admin`. Summary cards + quick actions:

```
┌─────────────────────────────────────────────────────────────────┐
│  FATURAMENTO — Maio/2026                                        │
│                                                                 │
│  Guias pendentes: 12    Lotes abertos: 2    Glosas: R$4.200    │
│                                                                 │
│  [Criar Guia]  [Novo Lote]  [Registrar Glosa]                  │
│                                                                 │
│  Guias recentes ─────────────────────────────────────────────  │
│  G202605001  João Silva  Unimed  SADT  R$320  [Pendente]       │
│  G202605002  Maria Costa  SulAmérica  Consulta  R$180  [Pago]  │
│  ...                                                            │
└─────────────────────────────────────────────────────────────────┘
```

---

## Permission Matrix

| Route | Required Role |
|-------|--------------|
| `/billing/` | faturista, admin |
| `/billing/guides` | faturista, admin |
| `/billing/guides/new` | faturista, admin |
| `/billing/batches` | faturista, admin |
| `/billing/glosas` | faturista, admin |
| `/billing/price-tables` | admin |

API permissions mirror frontend (DRF permission class: `HasBillingAccess`).
`faturista` can create/edit guides, batches, glosas. Only `admin` can manage price tables.

---

## Dependencies

### Existing code that Sprint 6 consumes

| Dependency | Where | Status |
|------------|-------|--------|
| `apps.emr.Encounter` | guide auto-populate | Done (Sprint 4/5) |
| `apps.emr.SOAPNote.cid10_codes` | CID-10 on guide | Done |
| `apps.emr.Patient` | guide patient ref | Done |
| `apps.core.Role` (faturista) | RBAC | Verify exists |
| `apps.core.FeatureFlag` (billing) | module gate | Done |
| MinIO / S3 storage backend | batch XML storage | Verify Django Storages config |

Verify `faturista` role exists before writing permission code:
```bash
python manage.py shell -c "from apps.core.models import Role; print(Role.objects.filter(name='faturista').exists())"
```

### New dependencies to install

```
# backend/pyproject.toml
lxml = "^5.2"        # XSD validation
Jinja2 = "^3.1"     # XML templates (already likely installed via Django, verify)
```

---

## Test Plan

### Unit tests (`backend/apps/billing/tests/`)

```
test_tuss_search.py
  - test_search_by_description_returns_ranked_results
  - test_search_by_code_exact_match
  - test_search_inactive_codes_excluded

test_guide_creation.py
  - test_create_guide_auto_populates_from_encounter
  - test_guide_number_sequential_per_tenant
  - test_guide_number_no_race_condition (concurrent creation produces unique numbers)
  - test_status_transition_valid (draft → pending)
  - test_status_transition_invalid (pending → draft) raises 400
  - test_missing_insured_card_number_raises_xsd_error

test_xml_engine.py
  - test_sadt_guide_xml_passes_xsd_validation
  - test_consulta_guide_xml_passes_xsd_validation
  - test_batch_xml_passes_xsd_validation
  - test_batch_xml_contains_correct_guide_count

test_glosa.py
  - test_create_glosa_transitions_guide_to_denied
  - test_appeal_workflow_state_machine
  - test_analytics_returns_correct_totals

test_price_table.py
  - test_price_lookup_active_table
  - test_price_lookup_ignores_expired_table
  - test_guide_item_autofill_from_price_table
  - test_two_active_tables_same_provider_raises_integrity_error
  - test_price_table_clean_rejects_overlapping_validity_windows  # Codex finding

test_batch.py
  - test_create_batch_with_pending_guides
  - test_batch_rejects_non_pending_guides
  - test_batch_xml_xsd_valid
  - test_batch_download_returns_xml_file_via_fileresponse  # must NOT redirect to MEDIA_URL
  - test_batch_close_transitions_guides_to_submitted

test_retorno.py
  - test_retorno_xml_parsed_correctly
  - test_retorno_creates_glosas
  - test_retorno_xsd_validation
  - test_retorno_transitions_guides_paid_and_denied
  - test_retorno_stores_retorno_xml_file  # eng review: retorno_xml_file field populated after parse
  - test_upload_retorno_rejects_batch_mismatch  # eng review: batch_number mismatch → 400

test_guide_creation.py additions:
  - test_guide_submit_writes_audit_log  # eng review: AuditLog written on status transition
  - test_guide_number_retry_on_concurrent_create  # eng review: retry loop resolves race condition

test_glosa.py additions:
  - test_glosa_appeal_writes_audit_log  # eng review: AuditLog written on appeal filing

test_tuss_search.py additions:
  - test_tuss_default_list_paginated  # eng review: GET /tuss/ returns ≤50, not 6k rows

test_patient_insurance.py
  - test_patient_insurance_card_number_encrypted_at_rest
  - test_patient_insurance_card_number_readable_via_orm
  - test_guide_creation_copies_card_number_from_patient_insurance
```

### Integration test (end-to-end smoke)

```
test_billing_e2e.py
  - test_full_billing_workflow:
      1. Create InsuranceProvider + PriceTable with 3 TUSS codes
      2. Import 10 TUSS codes
      3. Create encounter (use fixture patient + appointment)
      4. Create TISSGuide from encounter (auto-populate)
      5. Add 2 TISSGuideItems (with TUSS codes from price table)
      6. Generate guide XML → XSD validate → 0 errors
      7. Create TISSBatch with 1 guide
      8. Generate batch XML → XSD validate → 0 errors
      9. Download batch → 200 OK, Content-Type: application/xml
      10. Record Glosa on guide item → guide status = denied
      11. File appeal → appeal_status = filed
```

### Interaction State Coverage (design review — Pass 2)

Every state is a user experience. Unspecified states ship as blank divs.

| Screen | Loading | Empty | Error | Success | Partial/Special |
|--------|---------|-------|-------|---------|-----------------|
| billing/page.tsx | 4 stat card skeletons + table skeleton rows | **See First Login Empty State below** | Full-page error toast | — | Glosas card: red accent when > R$0 |
| guides/page.tsx | Skeleton rows (5) in table | "Nenhuma guia encontrada." + [Criar Guia →] CTA | Toast: "Erro ao carregar guias" + retry | — | Filtered empty: "Nenhuma guia com status 'Pendente'. [Ver todas →]" |
| guides/new/page.tsx | Encounter search: spinner in input | Encounter search: "Nenhuma consulta encontrada para este paciente" | Form validation: field-level red borders + message | — | PatientInsurance missing: "Carteirinha não cadastrada. [Cadastrar →]" inline warning |
| guides/[id]/page.tsx | Full card skeleton | — | — | Guide saved: toast "Guia salva" | XML invalid: red banner "XML inválido — N erros" with error list |
| batches/page.tsx | Skeleton rows | "Nenhum lote criado ainda." + [Ver guias pendentes →] | Toast | — | — |
| batches/[id]/page.tsx | — | — | — | XML generated: "XML gerado — N guias, R$X" | Retorno processed: "X pagas, Y glosadas" in green/red summary |
| glosas/page.tsx | Skeleton rows | "Nenhuma glosa registrada. Ótimo sinal!" (warmth) | Toast | Appeal filed: "Recurso enviado" badge | — |
| price-tables/page.tsx | Skeleton | "Configure tabelas de preços por operadora. [Nova Tabela →]" | Toast | — | Overlap conflict: inline error on clean() validation |

**First Login Empty State — billing/page.tsx (critical for pilot demo):**
The billing dashboard when a clinic has zero guides, zero batches, zero glosas must not be a blank
grid of zero-value stat cards. This is the first thing the pilot clinic sees.

Specified empty state for billing dashboard:
```
bg-white rounded-xl border border-gray-200 p-12 text-center

  [Receipt icon, size-12, text-slate-300]

  "Bem-vindo ao Faturamento TISS"
  text-xl font-semibold text-slate-900

  "Comece criando uma guia a partir de uma consulta existente.
   O sistema gera o XML TISS automaticamente."
  text-sm text-slate-500 mt-2 max-w-md mx-auto

  [Criar Primeira Guia →]
  bg-blue-600 text-white px-6 py-2.5 rounded-lg mt-6
```
This replaces the 4-card stat row when all counts are zero on first load.

### Responsive Behavior (design review — Pass 6)

**Breakpoint targets:**
- `lg` (1024px+): full desktop layout as specified above
- `md` (768px — iPad landscape): primary target for demo scenarios
- `sm` (640px and below): usable but not optimized; items table scrolls horizontally

**Per-screen responsive rules:**

`billing/page.tsx`:
- `lg`: 4-stat cards in one row (`grid-cols-4`)
- `md`: 2×2 grid (`grid-cols-2`)
- `sm`: single column, compact stat format

`billing/guides/page.tsx`:
- `lg`: full 7-column table
- `md`: hide "Tipo" column; keep guide_number, patient, insurer, value, status, actions
- `sm`: `overflow-x-auto` wrapper; minimum 500px content width

`billing/guides/new/page.tsx`:
- `lg/md`: full single-column form as specified
- `sm`: patient info strip stacks vertically; insurer + price table dropdowns stack full-width; items table scrolls horizontally
- Guide creation is **DESKTOP-FIRST** for Sprint 6. Do not over-optimize mobile until pilot feedback.

`billing/batches/[id]/page.tsx`:
- All viewports: single column; action buttons stack vertically on `sm`

**Accessibility minimums (all billing screens):**
- Interactive elements: `focus-visible:ring-2 focus-visible:ring-blue-500` (matches existing app patterns)
- Status badges: text label always visible — NEVER color-only status signaling
- Touch targets: min 44px height on all buttons and clickable table rows
- `<table>` elements: `aria-label="Guias TISS"` etc.
- `<StatusBadge>`: `aria-label="Status: {labelPT}"`
- `TUSSCodeSearch`: `role="combobox"`, `aria-expanded`, `aria-autocomplete="list"`, `aria-activedescendant`

---

Manual checklist (automate in Sprint 7+):

- [ ] `/billing` loads for faturista role, 403 for enfermeiro role
- [ ] `/billing/guides/new` — create guide from encounter, add 2 items, save as draft
- [ ] `/billing/guides` — guide list shows status badge, filter by status works
- [ ] `/billing/guides/{id}` — XML preview accordion shows generated XML
- [ ] `/billing/batches` — create batch from 2 pending guides, close batch
- [ ] `/billing/batches/{id}` — download button returns XML file
- [ ] `/billing/glosas` — register glosa, see in list, analytics cards update
- [ ] `/billing/price-tables` — admin creates table, adds items; faturista gets 403

---

## Deployment Checklist

Before Sprint 6 ships to any environment:

- [ ] ANS XSD schema files present: `apps/billing/schemas/tissV4_01_00.xsd` (submission)
- [ ] ANS XSD schema files present: `apps/billing/schemas/tissRetorno4_01_00.xsd` (retorno)
- [ ] `pg_trgm` extension enabled in Postgres (`CREATE EXTENSION IF NOT EXISTS pg_trgm`)
- [ ] `django.contrib.postgres` in SHARED_APPS (Gate 4)
- [ ] `migrate_schemas --shared` run after `TUSSCode` migration
- [ ] TUSS CSV imported: `python manage.py import_tuss --file tuss.csv`
- [ ] `faturista` role verified in tenant Role seed
- [ ] Unimed (ANS 00043753) and Bradesco Saúde (ANS 005711) fixture loaded
- [ ] MinIO bucket `vitali-billing` created (production only)
- [ ] `django-storages[s3]` and `boto3` in `pyproject.toml` (production only)
- [ ] Pilot clinic ICP-Brasil workaround documented and acknowledged (Gate 3)

---

## Open Questions

1. **TISS version:** TISS 4.01.00 or 4.02.00? Check before any XML work. Gate 1 above.

2. **TUSS CSV source:** Official ANS download at dados.ans.gov.br. File format may require
   column mapping — verify before writing import command.

3. **MinIO setup:** Is Django Storages + MinIO configured in `vitali/settings/base.py`?
   If not, batch XML storage falls back to local filesystem for dev, MinIO for prod.
   Need to check `DEFAULT_FILE_STORAGE` setting before S-023.

4. **`faturista` role:** Verify exists in Role seeding (S-005 task). If not, add to
   `apps/core/management/commands/create_tenant.py` default roles.

5. **ICP-Brasil (Sprint 6b):** Deferred from this sprint. The generated XML will have a
   `<assinatura>` placeholder that the clinic fills manually with their signing tool.
   Sprint 6b scope: per-tenant cert upload, PKCS#12 encrypted storage, auto-sign on export.

---

## Success Criteria

Sprint 6 is DONE when:

1. A real encounter in the system generates a TISS XML guide that passes ANS XSD validation
   (0 errors from `lxml` against `tissV4_01_00.xsd`).
2. A batch of 2+ guides exports as a valid TISS envelope XML (0 XSD errors).
3. The batch XML downloads via the API (200 OK, `application/xml`).
4. A faturista can record a glosa and see the guide transition to `denied` status.
5. All 11 test files pass: `pytest apps/billing/tests/ apps/emr/tests/test_patient_insurance.py -v` — 0 failures.
6. `/billing/*` routes return 403 for `enfermeiro` and `medico` roles.

---

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 1 | APPROVED_WITH_CONCERNS | 4 concerns, 3 cherry-picks accepted |
| Codex Review | `/codex review` | Independent 2nd opinion | 1 | APPROVED_WITH_FIXES | 15 findings, 7 incorporated |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 2 | CLEAR | Run 1: 3 blockers fixed. Run 2 (2026-03-30): 9 issues found + fixed in implemented code (ContentFile bug, batch close guide transition, retorno URL, retorno_xml_file field, AuditLog wiring, PriceTable clean(), guide number retry, TUSS pagination, N+1 aggregate). 5 new tests added. 4 new TODOS. |
| Design Review | `/plan-design-review` | UI/UX gaps (billing UI in scope) | 1 | APPROVED | All 7 passes complete. Score 3/10 → 8/10. 13 decisions added, 1 TODOS entry filed. |
| Outside Voice | `/plan-eng-review` (Codex) | Independent plan challenge | 1 | issues_found | 18 findings. 4 cross-model tensions surfaced as TODOS (total_value drift, mixed-provider batch, status bypass, retorno idempotency). |

**VERDICT:** CLEARED — Eng Review passed. Code fixes applied. Implementation-ready.

**UNRESOLVED:** 1 critical gap (empty batch close is silent — no guard when closing a batch with 0 guides).

---

### CEO Review Findings (APPROVED_WITH_CONCERNS)

**Concerns:**
1. **Scope risk:** 36 points is aggressive solo. S-024 (Glosa, 8pts) and S-025 (Price Tables, 5pts) can be deferred to Sprint 6b without breaking the core demo (create guide → export XML → download batch). Core demo = S-021 + S-022 + S-023 = 23 points.
2. **Missing seed data:** Demo requires at least Unimed and Bradesco Saúde pre-configured as `InsuranceProvider`. Empty provider list on first login kills the demo. Add fixture seed to S-021 tasks.
3. **ICP-Brasil expectation gap:** Confirm with pilot clinic owner that "generate XML, sign manually" is acceptable before Sprint 6 ships. Added to Gate 3 above.
4. **EMR dependency unverified:** The `Encounter` model from Sprint 4/5 may not have `insured_card_number` captured. If the faturista must enter it manually on every guide, the auto-populate story (S-022) is partly broken. Verify against `apps/emr/models.py` before S-022.

---

### Eng Review Findings — 3 Blockers (all fixed in this plan)

**Fixed in plan:**
1. `django.contrib.postgres` missing from SHARED_APPS → added to Gate 4 with exact fix
2. `TISSGuide` missing `insured_card_number`, `authorization_number`, `competency` → added to model definition above
3. lxml XSD path relative → fixed to `Path(__file__).parent.parent / "schemas" / ...`

**Also fixed:**
- `PriceTable` active-uniqueness → added `unique_together = [("provider", "valid_from")]`
- MinIO/storage gap → documented in Gate 5 with dev (FileSystemStorage) and prod (S3Boto3) paths

**Non-blocking concerns (to address during implementation):**
- `guide_number` concurrency: use `select_for_update()` in `transaction.atomic()` — noted in model above
- Cross-schema FK not DB-enforced: add pre-delete signal on `TUSSCode` — noted in Gate 2
- `faturista` role existence: add role verification to S-021 tasks
- Test gaps added: cross-schema read test, concurrent guide number test, TISS mandatory field XSD test

---

### Codex Review Findings — 15 findings, 7 incorporated

**Incorporated into plan:**
1. `PriceTable.clean()` overlap validator — `unique_together(provider, valid_from)` doesn't prevent date range overlap. Added clean() method to model definition.
2. `PriceTableItem unique_together = [("table", "tuss_code")]` — prevents duplicate codes per table. Added to PriceTableItem Meta.
3. `pg_trgm` extension missing from migration — added `RunSQL("CREATE EXTENSION IF NOT EXISTS pg_trgm")` to S-021 migration task.
4. Insurer auto-lookup undefined — `Appointment.provider` → `Professional`, not `InsuranceProvider`. S-022 Notes now explicitly requires manual insurer selector in guide form.
5. AuditLog for billing status transitions — billing is financial record, every status change must be logged. Added to S-022 status transition task.
6. Retorno TISS upload (S-023b, +5pts) — accepted as cherry-pick. Full story added. `tissRetorno4_01_00.xsd` added to deployment checklist.
7. `PatientInsurance` model — accepted as cherry-pick. Model added to Architecture section (apps.emr, `card_number = EncryptedCharField`).

**Noted but not incorporated (deferred or already handled):**
8. Batch download must use `FileResponse()` not `MEDIA_URL` redirect — noted in Gate 5. Added `test_batch_download_returns_xml_file_via_fileresponse` to test plan.
9. `TISSBatch.retorno_xml_file` field — accepted. Add to TISSBatch model during implementation of S-023b.
10-15. Remaining Codex findings on XML template field ordering, namespace prefix, and minor serializer patterns — handle during implementation review.
