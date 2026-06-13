# Sprint 29: Data Curation Tooling

## Context (ler antes de começar)

- `docs/AI-NATIVE-WEDGES.md` (checklist de go-live de cada wedge — fonte de verdade)
- `backend/apps/pharmacy/` — `MedicationFormulary`, `DoseRule`, `Drug`, `AllergenClass`, `DrugInteraction` (tabelas vazias)
- `backend/apps/billing/` — `TUSSCode`, `services/glosa_checker.py`
- `backend/apps/ai/` — prompt templates, usage logs
- Princípio inviolável: **nenhum número clínico/contratual/ANS é inventado em código.** Este sprint constrói as FERRAMENTAS para humanos carregarem e validarem dados; não carrega dados de verdade.

## Goal

Construir as ferramentas de importação e validação que destravam os wedges bloqueados por dados (dose, glosa clínica, alergia cross-reactivity, controlled refill). Ao fim, um farmacêutico/admin consegue popular e validar os dados de referência pela UI/CLI, sem engenheiro.

## Planned Scope

### S29-01: ANS TUSS Importer

- Management command `import_tuss --file <csv>` que importa a tabela TUSS oficial da ANS para `TUSSCode` (code, term, table_type, chapter, ans_version), idempotente (upsert por code + version).
- Validação: rejeita CSV malformado com relatório de linhas inválidas; nunca importa parcial silenciosamente.
- Registrar a versão ANS importada; permitir múltiplas versões coexistindo.
- Testes com um CSV fixture pequeno.

### S29-02: Medication Formulary Importer + Validation UI

- Command `import_formulary --file <csv>` para `MedicationFormulary`/`DoseRule` (drug, faixa de dose, frequência, via, dose_role, enforcement level), idempotente.
- Tela admin em `/configuracoes/farmacia/formulario`: lista regras, permite revisão e marcação `validated_by` + `validated_at` (a decisão D-T1 do farmacêutico vira um registro auditável).
- Uma `DoseRule` só é elegível para enforcement quando `validated=True`. O `DoseChecker` deve ignorar regras não validadas (não inventa).
- Testes: importação, fluxo de validação, checker respeita o flag de validação.

### S29-03: Allergy Cross-Reactivity & Drug-Interaction Loaders

- Command `import_allergen_classes` e `import_drug_interactions` (CSV → `AllergenClass`, `DrugInteraction`), idempotentes, com proveniência (fonte + versão).
- Tela admin de revisão (read + marcar como ativo) em `/configuracoes/farmacia/interacoes`.
- Match direto (alergia conhecida) já funciona sem isso; cross-reactivity/interaction só ativam com dados marcados ativos.

### S29-04: Supply Config (Stockout/Controlled)

- UI por estabelecimento em `/configuracoes/farmacia/suprimentos`: editar `lead_time_days`, `safety_stock` por item; `min_refill_interval_days` por droga controlada.
- Defaults nullable → wedge trata ausência como "sem config" (não bloqueia, não inventa).
- Testes: stockout/controlled usam config quando presente, degradam para advise-only quando ausente.

### S29-05: Curation Readiness Dashboard

- Painel em `/configuracoes/ai` (ou nova aba) mostrando, por wedge, o status de prontidão de dados: quantas regras validadas, % de cobertura, o que falta para poder ligar a flag.
- Reusar `ReadinessPanel` do design system.

## Acceptance Criteria

- Todos os importers são idempotentes, validam entrada e reportam erros por linha.
- `DoseRule` não validada nunca participa de enforcement (teste prova).
- Telas de validação gravam `validated_by`/`validated_at` com audit log.
- Readiness dashboard reflete corretamente o estado dos dados por wedge.
- Nenhum dado clínico/ANS fictício commitado no repo (apenas fixtures de teste claramente marcados).

## Verification Commands

```bash
cd backend && pytest apps/pharmacy apps/billing apps/ai -q --reuse-db
cd backend && python manage.py import_tuss --file apps/billing/tests/fixtures/tuss_sample.csv --dry-run
cd frontend && npm run build && npx vitest run
```

## Out of Scope

- Carregar os dados REAIS (é trabalho humano: farmacêutico + import ANS oficial) — acontece entre S29 e S31
- ML de previsão (smart scheduling / pharmacy forecast) — Fase 3
