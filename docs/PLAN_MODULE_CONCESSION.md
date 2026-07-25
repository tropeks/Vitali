# Vitali — Módulo "Comodato & Suprimentos de Diagnóstico" (integração do TCX)

> Traz a capacidade do TCX-SMART (outsourcing "all-inclusive" de imagem: concessão de
> equipamento + logística de insumos + P&L por contrato) para dentro do Vitali como um
> **módulo tier-gated** que o dono do SaaS ativa por tenant. Fonte: modelo do TCX em
> `/home/rcosta00/dev/TCX-SMART/packages/shared/prisma/schema.prisma`.

## Por que módulo, não produto novo
O cliente do TCX é o mesmo do Vitali. A infra de tier já existe: `core.FeatureFlag(tenant,
module_key)` + `ModuleRequiredPermission(module_key)` + `Plan`→módulos + `useHasModule`.
Módulo novo = `module_key = "diagnostic_concession"`, ligado por tenant. Sem produto paralelo.

## REUSA do Vitali (não duplicar)
| Conceito TCX | Reusa no Vitali |
|---|---|
| Product / insumo | `pharmacy.Material`/`Drug` (já tem ANVISA/NCM, lote/validade, controlados) |
| Stock (por unidade) | `pharmacy.StockItem` em `Warehouse`/`StorageLocation` da Facility + `StockMovement` (ledger append-only) |
| Order / InboundOrder / Supplier | `pharmacy.PurchaseOrder`→`StockReceipt`→`ThreeWayMatch`, `NFeReceipt`, `Supplier` |
| Dispatch / entrega | base: `pharmacy.StockTransfer` (saída/aceite) |
| Client / Unit | `organization.Facility`/`OrganizationalUnit`/`LegalEntity` |
| Exam / PacsReport | `imaging.DicomStudy`/`ImagingModality`/MWL (Orthanc) |
| Invoice / receita-custo | `billing` (DRE, recebível, CBHPM/pacotes — M1 já entregue) |
| Tier / feature flag | `core.FeatureFlag` + `ModuleRequiredPermission` + `useHasModule` |

## NOVO — o que o módulo adiciona (`apps/concession`, novo app tenant, gated)
1. **Frota em comodato (Asset):** `EquipmentAsset` (patrimônio/tag, modelo, serial, status
   ACTIVE/IN_MAINTENANCE/BACKUP/WRITTEN_OFF, ownership OPERADOR/CLIENTE/MÉDICO, depreciação,
   localização = Facility), `AssetService` (exames que o equipamento habilita), `AssetMovement`
   (DEPLOYMENT/RETRIEVAL/TRANSFER/SWAP, auditado), `MaintenanceTicket` (custo, evidência, resolução).
2. **Contrato all-inclusive:** `ConcessionContract` (cliente/unidades, valor mensal, vigência),
   `ContractServicePrice` (preço por serviço por unidade — receita; flag isBillable = conta volume
   mesmo com receita 0), `ServiceRecipe` (exame consome N de um insumo — driver de custo).
3. **Reposição de insumos (logística):** requisição da unidade → picking → despacho → prova de
   entrega (QR + assinatura + GPS) → recebimento + divergência. Sobre o `pharmacy.StockItem`.
4. **Consumo automático por exame:** exame roda (imaging) → `ServiceRecipe` deduz insumo do estoque
   da unidade (StockMovement) → alimenta o custo do contrato.
5. **P&L por contrato/unidade:** receita (exames × preço) vs custo (insumos consumidos + frete +
   manutenção) — view sobre `billing`/DRE.

## Fases (build por sprint, cada uma: gate `diagnostic_concession` + TDD + /cso + deploy)
- **C1 — Frota em comodato** (`EquipmentAsset`/`AssetMovement`/`MaintenanceTicket`/`AssetService`).
  O coração distintivo. App novo, disjunto. Modelo: Opus.
- **C2 — Contrato + recipe + preço** (`ConcessionContract`/`ContractServicePrice`/`ServiceRecipe`).
- **C3 — Reposição de insumos** (requisição→picking→despacho→prova-de-entrega, sobre pharmacy stock).
- **C4 — Consumo automático por exame + P&L do contrato** (costura imaging↔pharmacy↔billing).

## Decisões abertas (pré-build)
1. **Escopo da fase 1:** focar no que foi pedido (comodato + estoque + insumos) e deixar
   PACS→faturamento de exame pra fase posterior (Vitali já fatura via billing)?
2. **Logística:** estender `StockTransfer` (menos código) vs fluxo dedicado requisição→picking→
   despacho→prova-de-entrega (mais fiel ao TCX, mais trabalho)?
3. **App:** novo `apps/concession` (recomendado) — mantém o domínio de comodato isolado e gated.
4. **Estoque:** reusar 100% `pharmacy.StockItem` (recomendado) — "Stock por unidade" do TCX vira
   StockItem em StorageLocation da Facility. Sem tabela de estoque nova.
