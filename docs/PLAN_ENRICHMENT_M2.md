# Vitali — Plano de Enriquecimento M2 (operação enterprise ambulatorial)

> Continuação de M0 (E1-E6) e M1 (S1-S5), ambos shipped. Fonte: `scratchpad/
> ENTERPRISE_GAP_ANALYSIS.md` §4 (itens 13-15) + `PLAN_PLATFORM_ROADMAP.md` (M2).
> Doutrina: superpowers/TDD por task (red→green auditável + verificação independente do
> vermelho pelo integrador), suíte verde no container (`scratchpad/vt.sh`), gate de CI
> COMPLETO local antes do push (ruff check+format `.`, mypy, lint-imports, makemigrations),
> `/cso` por wave, modelo por complexidade, fanout por APP disjunto → integração limpa.

M2 é a camada que o Tasy usa pra ganhar cliente multiunidade / com compliance formal:
catálogos oficiais (CNES/CBO), RH operacional, LIS governado, qualidade, multiunidade,
interop nacional (RNDS), SSO. Reusa o backbone do M0 (TerminologyCatalog/CatalogImporter,
padrão cross-schema FK+signal) e o padrão de fanout de M1/concessão.

---

## WAVE 1 (disjunta, paralela) — os pré-requisitos de mais alavancagem (gap §4 13-15)

### SPRINT M2-S1 — Catálogos CNES + CBO + FK (core/organization/emr) · Opus
Reusa `core.terminology_base` (padrão E1/ANVISA/CBHPM).
- `core.CBOCode` (ocupação: code, título, família) + importer.
- `core.CNESEstablishment` (estabelecimento: CNES, nome, tipo, município) + importer (dados abertos DATASUS).
- FK/validação: `emr.Professional.cbo`/`cnes` (hoje CharField) → catálogo; `organization.Facility.cnes`.
- **Gate:** catálogos importam idempotente; Professional/Facility referenciam por FK.

### SPRINT M2-S2 — RH operacional: cargo/lotação/férias + escala (hr/emr) · Opus
- `hr.Position` (cargo, FK `core.CBOCode`), `hr.EmployeeAssignment` (lotação: FK OrgUnit/CostCenter, vigência), `hr.LeaveRequest` (férias/afastamento com aprovação maker-checker), dependentes.
- Escala assistencial: `hr.DutyRoster`/`RosterSlot` ligada à agenda (`emr.ScheduleConfig`/`Resource` do M0-E5) — quem está de plantão alimenta a disponibilidade.
- **Gate:** cargo/lotação/férias com aprovação; escala reflete na agenda.

### SPRINT M2-S3 — LIS governado: LOINC/UCUM + delta check + LabOrder→SADT (emr-lab/billing) · Opus
- `core.LoincCode` (subset BR ~2k) + `core.UcumUnit` + importer; FK em `emr.LabTest.loinc_code`/unidades.
- Delta check: comparar resultado com o anterior do mesmo paciente/teste → alerta de variação.
- Ponte faturamento: `LabOrder` aprovado gera guia TISS SADT (reusa billing M1) — fecha a receita do exame.
- **Gate:** LOINC/UCUM por FK; delta check dispara; LabOrder→guia SADT.

---

## WAVE 2 (após Wave 1)

### SPRINT M2-S4 — Qualidade & segurança do paciente (app novo `quality` ou emr) · Opus
Incidentes/eventos adversos, CAPA (ação corretiva/preventiva), protocolos versionados (reusa
`governance.ApprovalRequest`), indicadores. Notificação compulsória (liga com CID `is_notifiable` do E1).

### SPRINT M2-S5 — Multiunidade: rateios + catálogos + permissões hierárquicas (organization/billing) · Opus
Rateio de custo entre filiais, catálogos por unidade, permissões hierárquicas (rede→unidade).
Fecha o gap de `organization` (esqueleto existe, pouco referenciado).

### SPRINT M2-S6 — Interop nacional: FHIR R4 escrita + RNDS (fhir) · Opus
Mapear Problem/Allergy/Immunization (M0-E2) → Condition/AllergyIntolerance/Immunization; Provenance;
preparar envio RNDS. Amplia o `apps/fhir` (hoje só a porta OAuth SMART).

### SPRINT M2-S7 — SSO empresarial + MFA adaptativo (core/auth) · Opus
OIDC/SAML por tenant, MFA adaptativo, ciclo de vida de acesso, relatórios de auditoria de acesso.

---

## Ordem / loop
Wave 1 (S1-S3) em paralelo (apps disjuntos: core+organization+emr / hr / emr-lab+billing —
atenção ao overlap emr entre S2 escala e S3 lab: usar arquivos de modelo dedicados). Integro,
gate CI completo, `/cso`, deploy. Wave 2 por dependência/gatilho de mercado. Cada task:
teste vermelho → verde → container → TDD_LOG; integrador prova o vermelho + gate CI + /cso.
