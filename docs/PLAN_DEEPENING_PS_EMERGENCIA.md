# PLAN — Deepening: PS / Emergência (Classificação de Risco Manchester)

> Épico M3 (cuidado agudo) — fecha o trio internação + centro cirúrgico + **emergência**. Mapa read-only 2026-07-27:
> **não existe PS/Emergência**. `apps/triage` é um symptom-checker ASSÍNCRONO de WhatsApp/portal (pré-consulta, CFM
> 2.314/2022) — bounded context ERRADO, não reaproveitar como triagem de PS. `Encounter.encounter_type="emergencia"`
> existe mas é enum nu (zero lógica). Metodologia: fanout TDD, melhor modelo por task, red→green, integração file-copy,
> deploy (backend: rebuild + recreate django/celery + `--force-recreate nextjs` da RAIZ do repo + `create_default_roles
> --overwrite` por tenant; frontend: host-build+overlay), verificação headless. Régua: maturidade por camada.

## Reaproveitar (não duplicar)
- **Âncora de visita**: `Encounter.encounter_type="emergencia"` (apps/emr/models.py) + `Encounter.chief_complaint` (encrypted).
- **Insumo de acuidade**: `VitalSigns` (apps/emr/models.py:806 — já NEWS2-completo: PA, FC, temp, SpO2, FR, ACVPU) + motores `services/news2.py` + `services/deterioration.py` (banda NEWS2). Manchester consome vitais como discriminador fisiológico.
- **Catálogo governado**: padrão `core.CID10Code` (SHARED + through cross-schema + `protect_*_deletion`) para o catálogo Manchester e para CID no boletim.
- **Padrões de código**: modelos-domínio em apps/emr (como adt_models/surgery_models), catálogo SHARED em apps/core; serviço atômico (select_for_update) do ADT/CC; append-only (AdmissionEvent/SurgicalTime).
- **NÃO** reaproveitar `apps/triage` (assíncrono/WhatsApp). RBAC novo: namespace `emergency.*` (separado do `triage.read/respond`).

## Ownership (persona × escopo)
- **Enfermeiro classificador** faz a triagem Manchester (`emergency.classify`). **Recepção PS** abre boletim/admite
  (`emergency.manage`). **Médico emergencista** atende (`emergency.read`+clínico). **Coordenação PS** painel/fila. Escopo: PS/box.

## Sprints

### E1 · Catálogo Manchester + acuidade (backend) · **Opus** · ✅ FEITO (commit 84c63f9)
Catálogo governado SHARED (apps/core): `ManchesterFlowchart` (fluxograma, ~52 no MTS — infra + amostra, conteúdo licenciado GBCR) e `ManchesterDiscriminator` (discriminador por fluxograma → nível de acuidade). Níveis de acuidade como enum: **vermelho(0)/laranja(10)/amarelo(60)/verde(120)/azul(240 min)** com tempo-alvo. Importer CLI + registro no search de terminologia + `protect_*_deletion`. RBAC `emergency.read`/`emergency.manage`/`emergency.classify`. CRUD DRF + seed amostra. Migração. pytest TDD + `@extend_schema`.

### E2 · Boletim + classificação de risco (backend) · **Opus** (dep E1)
`EmergencyEncounter`/Boletim (apps/emr: arrival_at, mode_of_arrival [ambulante/maca/ambulância/PM], chief_complaint, FK Encounter[emergencia], FK Patient, status). `RiskClassification` (FK boletim, FK flowchart, FK discriminator, acuity_level, target_time, snapshot de vitais, classified_by, classified_at) — **reclassificação = novo registro** (histórico). Serviço `classify(boletim, flowchart, discriminator, vitals)` → seta acuidade+alvo (atômico). Vincula ao VitalSigns/NEWS2. RBAC `emergency.classify`. pytest TDD.

### E3 · Fila por gravidade + desfecho (backend) · **Opus** (dep E2)
Fila de acuidade: ordena por (nível, tempo de espera/chegada); "próximo a chamar"; **escalonamento por tempo-alvo estourado** (re-triagem sugerida). Desfecho/disposition (alta / **internação → ADT admit** / óbito / evasão / transferência / observação). Endpoint painel PS `/emergency/board/` + fila. RBAC `emergency.manage`. pytest TDD.

### E4 · Painel PS + classificação (frontend) · **Opus** (dep E3)
Rota `/pronto-socorro`: painel da fila por gravidade (cores Manchester + tempo-alvo/estouro), classificar (fluxograma→discriminador→acuidade + vitais), chamar próximo, desfecho. Nav "Pronto-Socorro" gated `emergency.read`. Vitest TDD.

### E5 · Boletim + atendimento no prontuário (frontend) · **Opus** (dep E2/E4)
Fluxo de atendimento de emergência: boletim, histórico de classificações, vitais, desfecho (internar → ADT). Aba/entrada no prontuário `patients/[id]`. Vitest TDD. RBAC `emergency.manage`.

## Ordem
E1 → E2 → E3 → (E4 dep E3, E5 dep E2/E4). Cada sprint: integra, mount-run gate, deploy, verifica headless.

## Régua
Maturidade por camada. Manchester = amostra representativa (conteúdo licenciado GBCR; a infra é o produto). Não quebrar o
`apps/triage` (WhatsApp) nem a agenda/waiting-room ambulatorial. Novo RBAC entra em DEFAULT_ROLES **e** roda
`create_default_roles --overwrite` no deploy. Desfecho "internação" reusa `services/adt.admit` (integração com o épico ADT).
