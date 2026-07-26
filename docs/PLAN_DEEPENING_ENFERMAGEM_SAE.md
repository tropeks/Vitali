# PLAN — Deepening: Enfermagem / SAE + BCMA

> Épico de aprofundamento enterprise (vs Tasy). Ancorado em `CANONICAL_FEATURE_MAP.md` §A (SAE hoje é JSON
> genérico; deterioração/CPOE rasos) e nos **3 separadores enterprise** da pesquisa: **CDS governado, BCMA
> beira-leito, integração com dispositivos**. Metodologia: fanout TDD, melhor modelo por task, red→green,
> integração file-copy, deploy host-build+overlay, verificação headless.
>
> Estado atual: `NursingAssessment` (apps/emr/models.py:1510) é um JSON `content` genérico (admissão/diagnóstico/
> plano/evolução/alta) — SEM catálogos NANDA-I/NIC/NOC, sem vínculo diagnóstico→resultado→intervenção, sem
> prescrição de enfermagem executável, sem aprazamento, sem checagem beira-leito. `MedicationAdministration`
> (models.py:1459) é eMAR append-only sem BCMA (scan de pulseira/medicamento).

## Ownership (persona × escopo — feature-map §glossário)
- **Diagnóstico + prescrição de enfermagem = privativos do ENFERMEIRO** (COFEN Res. 736/2024). Execução/checagem
  = TÉCNICO sob supervisão. RBAC: `sae.write` (enfermeiro) vs `sae.read`/`emar.administer` (técnico). Escopo: leito.

## Sprints

### N1 · Catálogos NANDA-I / NIC / NOC governados  ·  backend  ·  **Opus**
Reusa o backbone de terminologia (`core.terminology_base.TerminologyCatalog` + `CatalogImporter`, como CID10/CBO/LOINC).
- Modelos SHARED em apps/core: `NandaDiagnosis` (código, título, domínio/classe, definição, características definidoras,
  fatores relacionados), `NicIntervention` (código, título, definição, atividades), `NocOutcome` (código, título,
  definição, indicadores). Proteção cross-schema `pre_delete` (padrão dos outros catálogos).
- Importers CLI (`import_nanda`/`import_nic`/`import_noc`) + registro no search de terminologia (§A1). Seed com
  subconjunto representativo (as taxonomias são licenciadas — infra + amostra, igual fizemos com CBO/LOINC).
- Expor no search platform-admin (governança de terminologia, tela já existe). pytest TDD + `@extend_schema`.

### N2 · Domínio SAE executável  ·  backend  ·  **Opus** (depende de N1)
- `NursingDiagnosis` (patient/encounter + FK NandaDiagnosis + fatores/sinais), `NursingCareplan` ligando
  Diagnóstico → NOC (resultado esperado + meta) → NIC (intervenção), `NursingPrescriptionItem` (intervenção
  executável com frequência/horário = **aprazamento**), `NursingEvolution`. Migração. Gate `sae.read/write`.
- Serviço de aprazamento (gera grade de horários a partir da frequência). pytest TDD + `@extend_schema`.

### N3 · BCMA / eMAR beira-leito  ·  backend  ·  **Opus**
- Estender `MedicationAdministration` com verificação dos "5 certos" via scan: `patient_barcode`, `medication_barcode`,
  vínculo à prescrição/aprazamento, alerta de divergência. Endpoint de checagem que valida paciente×medicamento×horário.
  pytest TDD.

### N4 · Workspace SAE (frontend)  ·  **Opus**
No prontuário (`patients/[id]` ou `encounters/[id]`): fluxo SAE — Histórico → Diagnósticos (picker NANDA via terminology
search) → Plano (NOC/NIC) → Prescrição de enfermagem + grade de aprazamento → Evolução. RBAC `sae.write` (enfermeiro).
Vitest TDD.

### N5 · Checagem beira-leito / MAR (frontend)  ·  **Opus**
Grade de administração (MAR) por leito/turno + fluxo de checagem com scan (input de código de barras), os "5 certos",
registro de não-administração com motivo. Vitest TDD. RBAC `emar.administer`.

## Ordem
N1 → N2 (dependência de catálogo) → N3 (BCMA, paralelo a N2 possível) → N4 (depende N2) → N5 (depende N3).
Cada sprint: integra na base canônica, roda gate de CI, deploy staging, verifica.

## Régua
Maturidade por camada (modelo/API/UI/RBAC/e2e). Toda feature declara persona×escopo. Catálogos = amostra
representativa (taxonomias licenciadas); a infra é o produto.
