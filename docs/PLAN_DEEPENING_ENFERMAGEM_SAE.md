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

### N4 · Workspace SAE (frontend)  ·  **Opus**  ·  ✅ FEITO
No prontuário (`patients/[id]`): nova aba **SAE** — Diagnósticos (picker NANDA via terminology search) → Plano (NOC/NIC)
→ Prescrição de enfermagem → Evolução. Leitura para todos; adicionar gated em `sae.write` (enfermeiro). Componentes
`components/nursing/Sae*` + `types.ts`. Vitest TDD (20 testes nursing + 29 no escopo patients+nursing).
> **Fix de backend acoplado** (`serializers_sae._CatalogCodeWriteMixin`): o picker de terminologia só expõe `code`/`display`
> (sem PK do catálogo), então a UI posta `nanda_code`/`noc_code`/`nic_code`. Esses campos eram `read_only` → o vínculo à
> catálogo governada era perdido (FK nula → unmatched). Agora o `*_code` é gravável e roteia pelo setter do modelo
> (resolve code→FK, senão marca unmatched + guarda texto) — mesma forma reconcile-safe de `cbo`/`cnes`.

### N5 · Checagem beira-leito / MAR (frontend)  ·  **Opus**  ·  ✅ FEITO
Nova rota `/enfermagem/checagem` (nav "Checagem (MAR)" em Atendimento, gated `emar.administer`): scan paciente+medicamento
→ `POST /emar/check/` → 201 registra / 422 mostra os "5 certos" com o direito que falhou / override justificado. Meds
devidos vêm das prescrições assinadas (`/prescriptions/?patient=` → `items[]`). Componentes `Mar*`/`Bcma*`. Vitest TDD (13).

> **Épico N1..N5 concluído** (2026-07-26): catálogos NANDA/NIC/NOC governados → domínio SAE executável + aprazamento →
> BCMA/eMAR beira-leito → workspace SAE no prontuário → checagem MAR. Camadas modelo/API/UI/RBAC cobertas.

## Ordem
N1 → N2 (dependência de catálogo) → N3 (BCMA, paralelo a N2 possível) → N4 (depende N2) → N5 (depende N3).
Cada sprint: integra na base canônica, roda gate de CI, deploy staging, verifica.

## Régua
Maturidade por camada (modelo/API/UI/RBAC/e2e). Toda feature declara persona×escopo. Catálogos = amostra
representativa (taxonomias licenciadas); a infra é o produto.
