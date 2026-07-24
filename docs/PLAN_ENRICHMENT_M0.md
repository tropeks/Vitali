# Vitali — Plano de Enriquecimento M0 (profundidade dados+features, classe Tasy)

> Fonte: `scratchpad/ENTERPRISE_GAP_ANALYSIS.md` (Fable, 2026-07-24). Doutrina:
> **superpowers/TDD por task** (test-first, vermelho→verde→refactor), suíte verde no
> container a cada task, modelo dimensionado à complexidade da task, `/cso` no fim de
> cada sprint. Sequência por **fundação**, não calendário. Semeado no Shrimp.

## Princípio-guia
Onde o Tasy tem **catálogo governado + FK + versão**, o Vitali tem hoje `CharField`/`JSON`
solto. O trabalho é construir o **backbone de dados mestres** e ligá-lo aos módulos, começando
pela terminologia (destrava EMR, faturamento, farmácia). Régua interna de profundidade:
Farmácia (31 modelos) e LIS.

---

## SPRINT E1 — Backbone de Terminologia (fundação, item M0-1) · modelo: Opus
Pré-requisito de E2/E3. Padrão reutilizável: tabela no schema compartilhado + `version`/
`competency` + importador idempotente com proveniência (padrão Sprint 29) + signal de
proteção cross-schema (padrão `EncounterProcedure`→TUSS) + terminology service (busca/autocomplete).

- **E1-T1** `core.terminology`: classe-base abstrata `TerminologyCatalog` (code, display, system,
  version, active, `search_vector`/normalização) + mixin de import com log. TDD.
- **E1-T2** CID-10 rico: evoluir `core.CID10Code` → `parent`, `chapter`, `group`, `category`,
  `sex_allowed`, `age_min/max`, `is_notifiable`, `version`. Migration + backfill do import atual. TDD.
- **E1-T3** Importador `import_cid10` reescrito: hierárquico, dry-run, erro por linha, proveniência
  (fonte DATASUS). Idempotente. TDD (fixture pequena).
- **E1-T4** `core/terminology.py` — serviço de busca unificada (prefixo+full-text, ranqueado),
  API `GET /api/v1/terminology/<system>/?q=` para autocomplete. TDD (contrato).
- **E1-T5** Migrar usos soltos para FK: `emr.SOAPNote.cid10_codes` (JSON) e
  `emr.MedicalHistory.cid10_code` (CharField) → M2M/FK `CID10Code`, com data-migration e signal
  de proteção cross-schema. TDD (inclui teste de que soltar CID inválido falha).
- **Gate:** suíte verde no container; autocomplete de CID retorna hierarquia; `/cso` diff.

## SPRINT E2 — EMR orientado a problemas (item M0-2) · modelo: Opus
Depende de E1 (CID10 FK).
- **E2-T1** `emr.ProblemListItem` (FK CID10, onset/abatement, clinical_status, verification_status —
  espelho FHIR Condition), ligado ao `Encounter`/`Patient`. TDD.
- **E2-T2** `emr.Allergy.allergen_class` FK → `pharmacy.AllergenClass` (**já existe, hoje não
  referenciada**) + reação codificada + criticidade + verification_status. Data-migration do texto
  livre atual (best-effort match, resto vira `unmapped`). TDD.
- **E2-T3** `emr.Immunization` (imunobiológico, dose, lote, calendário PNI). TDD.
- **E2-T4** Serviços: problema ativo alimenta SOAP e faturamento; alergia entra no check de dose/
  interação existente (`pharmacy/services`). TDD.
- **Gate:** suíte verde; `/cso` diff.

## SPRINT E3 — Catálogo de medicamentos ANVISA/DCB (item M0-3) · modelo: Opus
- **E3-T1** `pharmacy.AnvisaProduct`/DCB no schema compartilhado (registro, dcb, apresentação, EAN,
  classe, lista 344). Importador dados-abertos ANVISA (proveniência). TDD.
- **E3-T2** `pharmacy.Drug.anvisa_product` FK (mantém `anvisa_code` legado durante transição);
  ligar `NFeCatalogMapping` a match por EAN. TDD.
- **Gate:** suíte verde; `/cso` diff.

## SPRINT E4 — Formulários/anamnese configuráveis (item M0-4) · modelo: Sonnet
- **E4-T1** `emr.ClinicalFormTemplate` versionado + `ClinicalFormResponse` (schema JSON validado por
  template, por especialidade). TDD.
- **E4-T2** 1 especialidade âncora semeada (conteúdo Humano) + render no encontro. TDD.
- **Gate:** suíte verde; `/cso` diff.

## SPRINT E5 — Agenda multi-recurso (item M0-5) · modelo: Opus
- **E5-T1** `emr.Resource` (sala/equipamento, FK `organization.Facility`) + `AppointmentResource` M2M;
  anti-double-booking por recurso (hoje só por profissional). TDD.
- **E5-T2** `ScheduleException`/`ScheduleBlock` (férias/feriado/bloqueio) sobre `ScheduleConfig`. TDD.
- **E5-T3** Encaixe/overbooking com permissão+motivo auditado. TDD.
- **Gate:** suíte verde; `/cso` diff.

## SPRINT E6 — Adendo pós-assinatura (item M0-6, requisito CFM) · modelo: Sonnet
- **E6-T1** `emr.EncounterAddendum` (documento assinado imutável + adendo encadeado, autor, motivo,
  timestamp). Nunca edita o original. TDD.
- **Gate:** suíte verde; `/cso` diff.

---

## Regra transversal (checklist de review)
Proibir novo `CharField` para conceito que tem catálogo. Casos abertos hoje a fechar ao longo
dos sprints: `cost_center`, `cbo_code`, `cnes_code`, `loinc_code`, `anvisa_code`,
`provider_ans_code`, `cid10_code*`.

## Loop de execução por task (superpowers/TDD)
1. Escrever teste que falha (vermelho) — contrato/comportamento, não implementação.
2. Implementar mínimo para passar (verde). 3. Refatorar. 4. Rodar a suíte do app no container
(`scratchpad/vt.sh`). 5. Marcar task no Shrimp. `/cso` diff ao fechar o sprint.
