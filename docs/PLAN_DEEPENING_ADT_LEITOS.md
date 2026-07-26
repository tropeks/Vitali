# PLAN — Deepening: ADT / Gestão de Leitos / Internação

> Épico de aprofundamento enterprise (camada **M3 inpatient** do roadmap). Vitali hoje é arquiteturalmente
> **ambulatorial**: `Encounter` (apps/emr/models.py:671) só tem status documental (open/signed/cancelled), sem
> `encounter_type`, sem admissão/alta/disposição; **não existe** Leito, Internação, Transferência nem Censo
> (mapa read-only 2026-07-26). O `apps/fhir/services/encounter_mapper.py:14` já sinaliza o gap ("inpatient/emergency
> classes são follow-up"). Metodologia: fanout TDD, melhor modelo por task, red→green, integração file-copy, deploy
> host-build+overlay, verificação headless. Régua: maturidade por camada (modelo/API/UI/RBAC/e2e).

## Reaproveitar (não duplicar)
- Backbone de catálogo governado `core.terminology_base.TerminologyCatalog` + `CatalogImporter` → catálogo de **tipo de leito** (CNES: clínico/cirúrgico/UTI/obstétrico/…).
- Hierarquia org `organization.Facility` / `OrganizationalUnit` (self-nesting "ward"). Leito pendura numa **InpatientUnit** ligada a `Facility`.
- RBAC `"module.action"` (JSON em `Role.permissions`) + bundles `NURSING_PERMISSIONS`/`RECEPTION_PERMISSIONS`/`CLINICAL_PRESCRIBER_PERMISSIONS` (apps/core/permissions.py).
- SAE já existe (épico N1..N5) e passa a ter **contexto de leito** real. `NursingAssessment` já tem kinds admissão/alta; `reconciliation_models` já tem gatilhos admission/transfer/discharge.

## Ownership (persona × escopo)
- **Recepção/Internação** admite (gera a estada + atribui leito) — `adt.admit`. **Médico** interna/dá alta com disposição — `adt.admit`/`adt.discharge`. **NIR/Gestão de Leitos** gere estrutura + censo + transferências — `beds.manage`/`adt.transfer`. **Enfermeiro** recebe no leito (SAE) — `beds.read`. Escopo: **leito/unidade**.

## Sprints

### L1 · Estrutura de leitos (backend) · **Opus**
Catálogo governado `BedType` (subclass `TerminologyCatalog`, tipos CNES) + hierarquia **InpatientUnit (ala/unidade)** →
**Room (quarto)** → **Bed (leito)**, todos FK a `Facility`. `Bed.status` enum (livre/ocupado/higienização/bloqueado/
reservado/interditado) + `bed_type` FK cross-schema (padrão DO_NOTHING + pre_delete protect). CRUD DRF (gestor/NIR),
RBAC `beds.read`/`beds.manage`. Migração. pytest TDD + `@extend_schema`.

### L2 · Admissão/Internação + ciclo ADT (backend) · **Opus** (dep L1)
`Admission` (estada): patient, admitting/attending professional, admission_source, admission/discharge datetimes,
expected_discharge, disposition, `status` (admitted/discharged/cancelled), `current_bed` FK. Adiciona `encounter_type`
(ambulatorial/internação/emergência/observação) em `Encounter` (default ambulatorial — não-quebra; destrava o FHIR mapper)
e vincula estada↔encounter. **Log ADT append-only** `AdmissionEvent` (admit/transfer/discharge, from_bed/to_bed, actor,
motivo, timestamp). Admitir **ocupa** o leito; alta **libera** → higienização (transição atômica). RBAC `adt.admit`/`adt.discharge`. pytest TDD.

### L3 · Transferência + Censo/Ocupação (backend) · **Opus** (dep L2)
Serviço de transferência (leito→leito / unidade→unidade: grava `AdmissionEvent`, atualiza status dos dois leitos
atomicamente, bloqueia destino ocupado). Serviço de **censo/ocupação**: taxa por unidade, contagem de leitos por status,
lista de internados, **LOS** (tempo de permanência). Endpoints `/api/v1/beds/board/` (mapa de leitos) e
`/api/v1/admissions/census/`. RBAC `adt.transfer`. pytest TDD.

### L4 · Mapa de Leitos + Painel de Internação (frontend) · **Opus** (dep L3)
Bed-board (grade por unidade, cor por status), KPIs de censo/ocupação, lista de internados. Ações admitir/transferir/alta
gated. Nav "Internação" (grupo Atendimento ou novo grupo). Vitest TDD.

### L5 · Fluxo admissão/alta na recepção + prontuário (frontend) · **Opus** (dep L2/L4)
Admitir (da sala de espera ou novo) → atribuir leito → definir responsável; dar alta com disposição. Banner/aba
"Internação" em `patients/[id]` mostrando a estada corrente + histórico ADT; integra com a aba SAE (leito real).
Vitest TDD.

## Ordem
L1 → L2 → L3 → (L4 depende L3, L5 depende L2/L4). Cada sprint: integra na base canônica, roda gate, deploy staging,
verifica headless. RBAC novo entra em `DEFAULT_ROLES` **e** roda `create_default_roles --overwrite` por tenant no deploy
(gotcha 2026-07-26: perms novas não propagam sem `--overwrite`).

## Régua
Maturidade por camada. Toda feature declara persona×escopo. Catálogo de tipo de leito = amostra representativa
(infra é o produto). Não quebrar o fluxo ambulatorial (encounter_type default = ambulatorial).
