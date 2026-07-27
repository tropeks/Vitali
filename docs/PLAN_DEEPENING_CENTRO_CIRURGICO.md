# PLAN — Deepening: Centro Cirúrgico (Bloco Cirúrgico)

> Épico enterprise da camada **M3** (inpatient/emergência/**centro cirúrgico**), sequência natural do ADT/Internação
> (paciente cirúrgico interna → sala → recuperação → leito). Mapa read-only 2026-07-27: **não existe módulo cirúrgico**
> (sem cirurgia/sala/checklist/OPME/anestesia/tempos/equipe). Metodologia: fanout TDD, melhor modelo por task, red→green,
> integração file-copy, deploy host-build+overlay (`--force-recreate nextjs`), verificação headless. Régua: maturidade por
> camada (modelo/API/UI/RBAC/e2e).

## Reaproveitar (não duplicar)
- **Âncora inpatient**: `Encounter.encounter_type=internacao` + `apps/emr/adt_models.Admission` (o caso cirúrgico faz FK a Encounter e, quando internado, a Admission).
- **Catálogo de procedimento + valoração**: `core.TUSSCode` + `core.cbhpm_models.CBHPMItem` (já carrega `porte`, `porte_anestesico`, `numero_auxiliares`, `valor_ch`, FK `tuss`). NÃO criar catálogo novo. `apps/emr/models.EncounterProcedure` é o padrão de captura (FK cross-schema DO_NOTHING + pre_delete).
- **Booking primitive**: `apps/emr/scheduling_models.Resource(kind=room)` + `AppointmentResource` já têm anti-double-booking (`clean()` → RESOURCE_UNAVAILABLE em overlap), mas são **órfãos** (sem serializer/viewset/serviço). Decisão: modelar **OperatingRoom dedicado** (semântica cirúrgica) + guarda de overlap própria no serviço de agendamento (mesmo shape do ADT: modelos dedicados + serviço atômico), referenciando o padrão do AppointmentResource. Não bendar o Resource genérico.
- **Consumo**: `apps/pharmacy.StockMovement` (hoje `reference` é texto livre sem FK) — C6/OPME adiciona o vínculo estruturado ao caso cirúrgico.
- **Governança**: `core.terminology_base.TerminologyCatalog`/`CatalogImporter`.

## Ownership (persona × escopo)
- **Cirurgião** agenda/executa a cirurgia (`surgery.schedule`/`surgery.manage`). **Anestesista** avaliação pré + registro anestésico. **Enfermagem CC** (circulante/instrumentador) checklist + tempos + OPME (`surgery.manage`/`beds.read`). **Coordenação CC** mapa cirúrgico + salas. Escopo: sala/centro cirúrgico.

## Sprints

### C1 · Estrutura + caso cirúrgico (backend) · **Opus** · ✅ FEITO (commit e1ff1d8)
`OperatingRoom` (sala: FK Facility, code/name/active, tipo). `SurgicalCase` (cirurgia: FK patient, FK encounter opcional,
FK admission opcional [âncora inpatient], FK surgeon [Professional], FK operating_room opcional, `scheduled_start/end`,
`priority` [eletiva/urgencia/emergencia], `status` [agendada/confirmada/em_sala/em_andamento/finalizada/cancelada], default agendada).
`SurgicalProcedure` (procedimentos planejados do caso: FK case, FK tuss_code cross-schema, quantity, lateralidade, porte via CBHPM).
RBAC `surgery.read`/`surgery.manage`. CRUD DRF (`/api/v1/{operating-rooms,surgical-cases,surgical-procedures}/`). Migração. pytest TDD + `@extend_schema`.

### C2 · Agendamento + mapa cirúrgico (backend) · **Opus** (dep C1)
Serviço de agendamento: reservar sala p/ janela (guarda de **overlap por sala** → 409, atômico), reagendar, confirmar,
cancelar (transições de status). Endpoint **mapa cirúrgico** `/surgical-cases/board/?date=&room=` (salas × dia/turno com os
casos e status). RBAC `surgery.schedule`. pytest TDD.

### C3 · Checklist cirurgia segura + tempos + equipe (backend) · **Opus** (dep C1/C2)
Checklist OMS (sign-in / time-out / sign-out) **append-only** por caso. `SurgicalTime` (entrada em sala, início/fim anestesia,
incisão, fechamento, saída) — status machine do caso dirigida pelos tempos. `SurgicalTeamMember` (papel: cirurgião/1º auxiliar/
anestesista/instrumentador/circulante + Professional). RBAC `surgery.manage`. pytest TDD.

### C4 · Mapa cirúrgico (frontend) · **Opus** (dep C2)
Rota `/centro-cirurgico`: mapa cirúrgico (salas × dia, casos coloridos por status/prioridade), agendar/reagendar/cancelar,
filtro por sala/dia. Nav "Centro Cirúrgico" gated `surgery.read`. Vitest TDD.

### C5 · Checklist/tempos + prontuário cirúrgico (frontend) · **Opus** (dep C3/C4)
Tela de sala: checklist OMS (3 fases), registro de tempos, equipe; aba "Cirurgia" no prontuário `patients/[id]` (casos do
paciente + status + procedimentos + tempos). Vitest TDD. RBAC `surgery.manage`.

### C6 · OPME / consumo de sala (backend+frontend) · **Opus** (dep C1, deferível)
OPME/materiais especiais por caso + vínculo estruturado `StockMovement`→SurgicalCase (nova FK) p/ rastreabilidade de consumo.
RBAC. Deferível se a prioridade for o fluxo cirúrgico core primeiro.

## Ordem
C1 → C2 → C3 → (C4 dep C2, C5 dep C3/C4) → C6 (deferível). Cada sprint: integra na base canônica, mount-run gate, deploy
staging (backend: rebuild + recreate django/celery + `--force-recreate nextjs` + `create_default_roles --overwrite` por
tenant; frontend: host-build+overlay), verifica headless.

## Régua
Maturidade por camada. Toda feature declara persona×escopo. Procedimentos = TUSS/CBHPM governados (infra é o produto). Não
quebrar agenda ambulatorial nem ADT. Novo RBAC entra em DEFAULT_ROLES **e** roda `create_default_roles --overwrite` no deploy.
