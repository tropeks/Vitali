# PLAN — Frontend Wave (surfacing M2 Wave 1 + Concession module in the UI)

> Metodologia: mesma das waves de backend — sprints → tasks TDD (red→green auditável),
> melhor modelo por task, fanout em worktrees. **Diferença crítica:** TDD de frontend =
> **Vitest + React Testing Library** (`*.test.tsx` colocado, mock de `@/lib/api` ou `global.fetch`),
> rodado LOCAL (`npm run test:watch`). O **CI do frontend NÃO roda Vitest** — o gate de merge é
> `eslint . --max-warnings=0` + `tsc --noEmit` + **Playwright e2e** (`e2e/*.spec.ts` contra stack booteda).
> Logo: cada task de UI entrega Vitest (prova local red→green) **e** — nos fluxos críticos — um e2e
> Playwright (o que o CI de fato exige). Gaps de backend seguem TDD pytest igual às waves M2.

## Stack de referência (survey travado)
- Next 15 App Router, React 18, TS strict. Tailwind + design system **`neu-*`** ("Tasy Neumorphic").
- Wrappers obrigatórios: `PageShell` (`variant="operational"` p/ tabelas, `"workbench"` p/ forms),
  `SectionState`, `Button`/`Badge`/`StatusBadge`/`KpiTile` de `components/shared`.
- Data: `apiFetch<T>('/api/v1/...')` de `@/lib/api` (sem react-query); proxy BFF catch-all
  `app/api/[...path]/route.ts`. Aceitar array **ou** `{results,count}` do DRF.
- Tier gating client: `useHasModule`/`useActiveModules` + entrada em `NAV_ITEMS`
  (`components/layout/DashboardShell.tsx`) + `ModuleGate` no `layout.tsx` da rota.
- Strings: literais pt-BR inline (convenção atual). Moeda: `toLocaleString('pt-BR',{style:'currency',currency:'BRL'})`.
- Padrão-ouro a espelhar: `configuracoes/profissionais` (lista limpa via `@/lib/api`) e
  `billing/guides` (form rico com readiness). Preferir `@/lib/api` ao inline-fetch legado do billing.

---

# BLOCO A — Superfícies do M2 Wave 1 (clínico / RH / terminologia)

Ordem por dependência: onde a API já existe, vai direto pra UI; onde falta, um sub-sprint de backend (pytest TDD) precede a tela.

### Sprint A1 — Backend: API de terminologia governada  ·  modelo: **Opus**
Fecha o gap #1. Hoje só `cid10` está registrado no `terminology.py`; CBO/CNES/LOINC/UCUM não têm API.
- **A1-T1** Registrar `cbo`, `cnes`, `loinc`, `ucum` no registry de `apps/core/terminology.py` (search read-only `/api/v1/terminology/<system>/?q=`). *(pytest red→green)*
- **A1-T2** Viewsets de gestão (SaaS-owner) para listar/paginar cada catálogo + status de importação (contagem, última carga). Platform-admin gated (`urls_public.py` platform surface). *(pytest)*
- **A1-T3** Endpoint p/ disparar import de um catálogo (upload CSV ou trigger do management command) — platform-admin only. *(pytest)*
- **A1-T4** Expor `cbo_unmatched`/`cnes_unmatched` no `ProfessionalSerializer` (read-only) p/ a UI mostrar se o código reconciliou. *(pytest)*

### Sprint A2 — Frontend: Profissionais com CBO/CNES  ·  modelo: **Sonnet**
API pronta (Feature 2). Depende de A1 (picker de código) + A1-T4 (badge de reconciliação).
- **A2-T1** `RemoteCombobox` de CBO e CNES no form de `configuracoes/profissionais` (busca via `/api/v1/terminology/cbo|cnes/`). *(Vitest: seleção → PATCH body com `cbo_code`)*
- **A2-T2** Coluna/badge "CBO/CNES governado vs texto legado" na tabela (usa `*_unmatched`). *(Vitest)*

### Sprint A3 — Backend: Delta check laboratorial em produção  ·  modelo: **Opus**
Fecha gap #3. `run_delta_check` hoje só roda em teste; não está ligado.
- **A3-T1** Wire: chamar `run_delta_check` na validação/resultado de `LabOrderItem` (signal ou no fluxo de resultar). *(pytest: resultar exame com variação → alerta criado)*
- **A3-T2** Expor `delta_threshold_pct` no `LabTestSerializer` (read/write). *(pytest)*
- **A3-T3** `LabDeltaAlert` serializer + viewset read-only (`/api/v1/lab-delta-alerts/`) e/ou nested `delta_alert` em `LabOrderItemSerializer`. *(pytest)*

### Sprint A4 — Frontend: Laboratório (LOINC + delta)  ·  modelo: **Sonnet**
Depende de A1 (LOINC picker) e A3 (threshold + alertas).
- **A4-T1** Picker LOINC no cadastro de exame (`lab-tests`) + campo `delta_threshold_pct`. *(Vitest)*
- **A4-T2** Surface do alerta de delta no resultado/lista de laboratório (badge "variação X% > limite"). *(Vitest)*

### Sprint A5 — Backend: Gatilho Lab → guia TISS SP/SADT  ·  modelo: **Opus**
Fecha gap #5. Serviço `generate_sadt_guide_for_lab_order` existe, sem endpoint.
- **A5-T1** `@action` em `LabOrderViewSet` (`POST /api/v1/lab-orders/<id>/faturar/`) chamando o serviço; retorna a guia criada ou erro de pré-condição (order COMPLETED, tem encounter, convênio ativo, TUSS). *(pytest: casos de sucesso + cada pré-condição)*

### Sprint A6 — Frontend: Faturar ordem de lab  ·  modelo: **Sonnet**
Depende de A5.
- **A6-T1** Botão "Faturar (SP/SADT)" em ordens de lab COMPLETED → chama a action → redireciona p/ `billing/guides/[id]`. Estados de erro das pré-condições. *(Vitest + e2e do fluxo)*

### Sprint A7 — Frontend: RH operacional (o maior do Bloco A)  ·  modelo: **Opus** (design) + **Sonnet** (telas)
API 100% pronta (Feature 4, 6 endpoints). Módulo `rh` já no menu.
- **A7-T1** Escalas: `DutyRoster` + `RosterSlot` (calendário/grade de plantões). *(Vitest + e2e)*
- **A7-T2** Lotação: `EmployeeAssignment` (invariante single-active — respeitar RO `active`/`end_date`). *(Vitest)*
- **A7-T3** Férias/afastamento: `LeaveRequest` com fluxo **maker-checker** (`/decide`, self-approval bloqueado). *(Vitest + e2e)*
- **A7-T4** Cargos (`Position`) + Dependentes (`Dependent`) CRUD. *(Vitest)*

### Sprint A8 — Frontend: Governança de terminologia (SaaS-owner)  ·  modelo: **Sonnet**
Depende de A1. Tela platform-admin p/ gerir os catálogos CBO/CNES/LOINC/UCUM (listar/buscar, ver contagem, disparar import).
- **A8-T1** Tela de catálogos + import trigger. *(Vitest)*

---

# BLOCO B — Módulo Concessão / Comodato (tier `diagnostic_concession`)

Módulo backend-only hoje, **sem nenhuma tela**. Tem gaps de API que precisam fechar antes.

### Sprint B0 — Backend: fechar gaps de API da Concessão  ·  modelo: **Opus**
- **B0-T1** `ConcessionService` catálogo CRUD (serializer/view/route). *(pytest)* — drive do match de modalidade no imaging bridge.
- **B0-T2** `AssetService` viewset (asset → exames habilitados; serializer já existe). *(pytest)*
- **B0-T3** `MaterialUnitCost` CRUD (base de custo do P&L; hoje inexistente → custo fica 0). *(pytest)*
- **B0-T4** `ExamConsumption` leitura (ledger) + endpoint de registro manual (exame não-DICOM). *(pytest)*
- **B0-T5** `DispatchDiscrepancy` leitura standalone + transições faltantes (requisition `cancel`, ticket `start`/`complete`). *(pytest)*
- **B0-T6** Normalizar prefixos de URL inconsistentes (`concession-contracts`/`contract-prices`/`service-recipes` bare vs `/concession/...`) OU documentar no api client. *(pytest de rota)*

### Sprint B1 — Frontend: scaffolding do módulo  ·  modelo: **Sonnet**
- **B1-T1** Entrada `NAV_ITEMS` gated em `module: "diagnostic_concession"` + `ModuleGate` no `layout.tsx` + landing/dashboard do módulo. *(Vitest: menu some/aparece por módulo)*
- **B1-T2** Confirmar toggle de ativação do tier por tenant (SaaS-owner) — reusar plans/features admin; senão, tela mínima. *(Vitest)*

### Sprint B2 — Frontend: Ativos / frota  ·  modelo: **Sonnet**
- **B2-T1** Registro de ativos (lista + filtro status/local/ownership) + detalhe/edição. *(Vitest)*
- **B2-T2** Modal Deploy/Retrieve/Transfer/Swap (cria `AssetMovement`) + timeline de movimentos. *(Vitest + e2e)*

### Sprint B3 — Frontend: Manutenção  ·  modelo: **Sonnet**
- **B3-T1** Board de tickets (Kanban por status) + detalhe com start/complete, custo, foto de evidência. *(Vitest)*

### Sprint B4 — Frontend: Contratos & preços  ·  modelo: **Opus** (matriz de preço) + **Sonnet**
- **B4-T1** Lista/detalhe de contrato (cliente, unidades M2M, vigência, valor, status). *(Vitest)*
- **B4-T2** Editor de matriz de preço (serviço × preço × is_billable, com override por unidade). *(Vitest)*
- **B4-T3** Editor de receita (material + qty por exame) + catálogo de serviço (depende B0-T1). *(Vitest)*

### Sprint B5 — Frontend: Logística (o maior de todos — fluxo QR/assinatura/GPS)  ·  modelo: **Opus**
- **B5-T1** Requisição (builder de linhas + submit) + fila do aprovador (`approve`). *(Vitest + e2e)*
- **B5-T2** Separação no armazém (scanner: escanear lote/`source_stock_item` + `picked_qty` por linha → PICKED). *(Vitest)*
- **B5-T3** Despacho (manifest_code/QR, armazém origem/destino, frete) + impressão de manifesto/QR. *(Vitest)*
- **B5-T4** Captura de entrega (signature pad → `signature_ref`, GPS `geo_lat/lng`, `received_by`, discrepâncias missing/damaged/extra). *(Vitest + e2e)*
- **B5-T5** Visualizador de POD / cadeia de custódia (read-only). *(Vitest)*

### Sprint B6 — Frontend: P&L / consumo  ·  modelo: **Opus**
- **B6-T1** Dashboard P&L do contrato (period/unit picker, KPI tiles revenue/cost/result/volume, breakdown consumption/freight/maintenance, tabela por serviço). Usa `/api/v1/concession/contracts/<id>/pnl/`. *(Vitest)*
- **B6-T2** Ledger de consumo de exame (depende B0-T4) + editor de custo unitário de material (depende B0-T3). *(Vitest)*

---

## Ordem recomendada
**Bloco A primeiro** (menos gap de backend, completa o investimento do M2, valor clínico imediato), **depois Bloco B** (módulo tier maior, mais backend). Cada sprint fecha em fanout, integra na base, roda gate local (lint + tsc + Vitest) e — nos fluxos críticos — e2e Playwright, antes de push/deploy staging.

## Documentação de API (evita re-scan — pedido do Romulo 2026-07-25)
Fonte da verdade = **OpenAPI auto-gerado por drf-spectacular** (`/api/schema/` live; snapshot versionado em `docs/api/openapi.yaml`).
- **DoD de todo sprint de backend:** endpoint novo entra no schema. Viewset/serializer padrão o spectacular pega sozinho; **toda `@action`/view custom ganha `@extend_schema`** (request/response). Regenerar `docs/api/openapi.yaml` (`manage.py spectacular --file`) ao fim do sprint.
- **Planejamento futuro lê o schema, não escaneia o código.** (graphify opcional como grafo navegável — extra, não fonte da verdade.)
- Meta rolante: derrubar os ~714 erros de schema atuais conforme cada sprint anota o que toca.

## Gate por sprint (frontend)
`npm run lint` (eslint max-warnings=0) + `npm run type-check` (tsc) + `npm run test` (Vitest, prova local) + `npm run test:e2e` nos fluxos com e2e. Deploy staging = rebuild da imagem `vitali-frontend` + restart do compose (análogo ao backend).
