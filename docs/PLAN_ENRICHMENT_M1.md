# Vitali — Plano de Enriquecimento M1 (eficiência clínica e financeira)

> Continuação de `docs/PLAN_ENRICHMENT_M0.md` (M0 shipped: E1-E6). Fonte:
> `scratchpad/ENTERPRISE_GAP_ANALYSIS.md` §4 (roadmap M1, itens 7-12). Doutrina:
> superpowers/TDD por task (red→green, com `TDD_LOG.md` auditável e verificação
> independente do vermelho pelo integrador), suíte verde no container por task
> (`scratchpad/vt.sh`), `/cso` por wave, modelo Opus (domínio complexo). Fanout por
> APP disjunto pra integração limpa (1 migration leaf por app, sem merge migration).

M1 é onde o Tasy vence: precificação por porte, ciclo de faturamento completo,
escrituração regulatória de controlados, reconciliação medicamentosa, portal
transacional. Reusa o backbone do M0 (TerminologyCatalog/CatalogImporter, padrão
cross-schema FK + signal de proteção, ledger append-only maker-checker do pharmacy).

## Ordem por dependência
- **Wave 1 (disjunta, paralela agora):** S1 CBHPM (core), S2 Controlados (pharmacy),
  S3 Reconciliação medicamentosa (emr). Nenhum depende do outro; todos herdam o M0.
- **Wave 2 (depende da Wave 1):** S4 Ciclo de faturamento/recebível (billing — usa CBHPM
  da S1 para pacotes/porte). S5 Portal transacional (patient_portal — usa recebível da S4
  + slot_service/whatsapp + PIXCharge).

---

## WAVE 1

### SPRINT M1-S1 — Catálogo CBHPM + valoração por porte (core) · Opus
Reusa `core.terminology_base.TerminologyCatalog`/`CatalogImporter` (padrão E1/ANVISA).
- **S1-T1** `core.CBHPMItem` (código CBHPM/AMB, porte, UCO/valor-CH, porte anestésico, nº
  filme, nº auxiliares, vigência) reusando o backbone; importador `import_cbhpm` idempotente
  (dry-run, proveniência, erro por linha, fixture local). TDD.
- **S1-T2** Ligar ao TUSS: `TUSSCode.table_number` + FK opcional `CBHPMItem.tuss` (procedimento
  TUSS ↔ porte CBHPM). Helper de valoração por porte (CH × valor-CH). TDD.
- **Gate:** suíte verde; catálogo importa e valora por porte.

### SPRINT M1-S2 — Livro de escrituração de controlados / SNGPC-like (pharmacy) · Opus
ENT-009 (P0 do assessment). Constrói sobre o `StockMovement` append-only + maker-checker existentes.
- **S2-T1** `pharmacy.ControlledSubstanceLedger` (livro por substância/apresentação Portaria 344:
  saldo anterior, entradas, saídas, saldo, período/competência) alimentado dos StockMovement de
  itens `is_controlled`; append-only, imutável. TDD.
- **S2-T2** Fechamento de período assinado (RT/farmacêutico), balanço conferido, e relatório de
  escrituração exportável (base para SNGPC). Dupla conferência para controlados. TDD.
- **Gate:** suíte verde; livro concilia com o ledger de estoque; fechamento assinado imutável.

### SPRINT M1-S3 — Reconciliação medicamentosa + order sets (emr) · Opus
Depende do M0-E2 (problem list / medication history) — já no ar.
- **S3-T1** `emr.MedicationReconciliation` (lista de uso contínuo do paciente ↔ prescrição atual;
  ações continue/stop/modify por item; momento admissão/alta; autor/timestamp). Conecta com os
  wedges de dose/alergia existentes. TDD.
- **S3-T2** `emr.OrderSet`/`OrderSetItem` versionado e aprovado (fluxo `governance.ApprovalRequest`
  reusado) — conjunto de ordens (med/lab/imagem) aplicável a um encontro. TDD.
- **Gate:** suíte verde; reconciliação registra decisões auditadas; order set versionado aplica ordens.

---

## WAVE 2 (após Wave 1)

### SPRINT M1-S4 — Ciclo de faturamento e recebível completo (billing) · Opus
Usa CBHPM (S1). Sequencial dentro de billing.
- Pacotes/regras contratuais por operadora (`Package`/`ContractRule`: fecha N TUSS por preço,
  taxas/diárias/filme/UCO); precificação por porte CBHPM.
- Guia de honorários + anexos (OPME/quimio conforme cliente); motor XML já existe.
- Recebível completo: desamarrar `AccountsReceivable` da guia (particular/PIX/pacote geram título),
  baixa parcial, FK real `organization.CostCenter`. Fecha ENT-010/011.
- **Gate:** faturamento particular e por convênio gera recebível; fechamento de competência com trava; `/cso`.

### SPRINT M1-S5 — Portal transacional (patient_portal) · Opus
Usa recebível (S4). Reusa `whatsapp/slot_service.py` e `billing.PIXCharge`.
- Agendar/remarcar/cancelar self-service; pagamento PIX no portal; formulários pré-consulta
  (reusa `ClinicalFormTemplate` do M0-E4). Tudo com consentimento LGPD auditado.
- **Gate:** fluxo agendar→pagar→formulário via portal; `/cso`.

---

## Loop por task
Idêntico ao M0: teste vermelho → mínimo verde → refactor → `vt.sh` verde no container →
`TDD_LOG.md`. Integração: verificação independente do vermelho (testes-only na base pré-sprint),
commit test→impl bisectável, `/cso` por wave, deploy.
