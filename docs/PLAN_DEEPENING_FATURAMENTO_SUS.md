# PLAN — Deepening: Faturamento SUS (SIGTAP / BPA / APAC)

> Épico do backlog P0 (ponte clínico→financeiro) — o caminho **SUS**, paralelo ao TISS/convênio que já existe. Mapa
> read-only 2026-07-28: SUS é **100% greenfield** (grep `sus|bpa|apac|aih|sigtap` = 0 hits em .py). O que existe é o
> caminho privado: TISS 4.01 (guias/glosas/lotes/XML+XSD, `apps/billing`), pacotes CBHPM, e back-office financeiro. SUS é
> produção-baseada (por estabelecimento/competência), NÃO por-guia-por-operadora. Metodologia: fanout TDD, melhor modelo
> por task, red→green, integração file-copy, deploy (backend rebuild + recreate + `create_default_roles --overwrite`;
> frontend host-build+overlay + `--force-recreate nextjs` da RAIZ). Régua: maturidade por camada.

## Reaproveitar (não duplicar)
- **Identidade de produção**: `core.CNESEstablishment` (estabelecimento + `Professional.cnes`), `core.CBOCode`
  (`Professional.cbo`), `Patient.cns` (cartão SUS, já encrypted). **FALTA `Professional.cns`** (executor BPA-I/APAC) → S1 adiciona.
- **Catálogo governado**: padrão `core.TUSSCode`/`CBHPMItem` (SHARED + importer + search) para o **SIGTAP**.
- **Eventos clínicos** que viram produção: `emr.EncounterProcedure` (ambulatorial → BPA), `surgery.SurgicalProcedure`,
  `adt.Admission` (→ AIH, deferido), `emergency.EmergencyEncounter`. Hoje só existe a ponte **lab→TISS**
  (`billing/services/lab_order_billing.py`); nada disso alimenta faturamento.
- **Remessa**: molde do `billing/services/xml_engine.py` + batch `export`/`download` (mas SUS é **arquivo texto
  posicional** BPA-Magnético/APAC pro DATASUS, não XML).
- **Competência**: hoje só string `AAAA-MM` em TISSGuide/Settlement — SUS precisa de competência como objeto com ciclo
  (aberta→fechada→exportada).

## Ownership (persona × escopo)
- **Faturista SUS** gera/fecha/exporta produção (`sus.read`/`sus.write`/`sus.export`). Recepção/clínico alimentam os
  eventos (EncounterProcedure etc.). Escopo: estabelecimento/competência.

## Sprints

### S1 · Catálogo SIGTAP + identidade SUS (backend) · **Opus** · ✅ FEITO (commit d90ce2b)
`SIGTAPProcedure` (catálogo governado SHARED: código, nome, competência/vigência, `valor_sa`/`valor_sh`/`valor_sp`,
instrumento de registro, complexidade, financiamento, compat CBO/CID/sexo/faixa etária). Importer `import_sigtap` + amostra
(SIGTAP é domínio público DATASUS — infra + amostra representativa). Registro no search. `Professional.cns` (novo campo,
migração). RBAC `sus.read`/`sus.write`. CRUD DRF. Migrações (core SIGTAP + emr Professional.cns). pytest TDD.

### S2 · Produção ambulatorial BPA + competência (backend) · **Opus** (dep S1) · ✅ FEITO (commit c1ee7ff)
`SusCompetencia` (por CNES + `AAAA-MM`, status aberta→fechada→exportada). **BPA-C** (consolidado: procedimento SIGTAP + CBO +
idade + quantidade, sem paciente) e **BPA-I** (individualizado: paciente CNS + CID + procedimento + CBO + quantidade +
serviço/classificação). Serviço-ponte `gerar_producao_ambulatorial(competencia)` a partir de `EncounterProcedure`
(ambulatorial) → linhas BPA (valoradas via SIGTAP `valor_sa`+`valor_sp`). Idempotente por competência. RBAC `sus.write`.
Endpoints. pytest TDD.

### S3 · APAC + remessa DATASUS (backend) · **Opus** (dep S2) · ✅ FEITO (commit 733da75)
`ApacAutorizacao` (número APAC, validade, procedimento principal + secundários, CID, paciente CNS, valor). **Remessa
posicional**: exportador BPA-Magnético (`.txt` fixed-width, header/linhas por competência) + layout APAC — molde do
`xml_engine`/batch export, mas texto posicional DATASUS. Fechar competência → gerar remessa. RBAC `sus.export` (consequente).
pytest TDD (valida o layout posicional com fixtures).

### S4 · Painel Faturamento SUS (frontend) · **Opus** (dep S2/S3)
Rota `/billing/sus` (na área billing): produção por competência (BPA-C/BPA-I/APAC), gerar produção a partir dos eventos
clínicos, fechar competência, baixar remessa. KPIs de produção/valor. Nav/entrada na área de faturamento, gated `sus.read`.
Vitest TDD.

## Deferido
- **AIH (internação SUS / SISAIH)** — camada inteira própria (laudo, procedimento principal, diárias, SP); grande, fica
  para um épico seguinte. A ponte `Admission → AIH` fica anotada.

## Ordem
S1 → S2 → S3 → S4. Cada sprint: integra, mount-run gate, deploy, verifica headless. Novo RBAC entra em DEFAULT_ROLES **e**
roda `create_default_roles --overwrite` no deploy.

## Régua
Maturidade por camada. SIGTAP = amostra representativa (domínio público; a infra é o produto). NÃO quebrar o caminho
TISS/convênio nem o back-office financeiro. SUS é caminho PARALELO. Remessa = layout posicional DATASUS validável por teste.
