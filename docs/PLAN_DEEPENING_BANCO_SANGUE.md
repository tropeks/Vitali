# PLAN — Deepening: Banco de Sangue / Agência Transfusional (Hemoterapia)

> Épico enterprise (gap do feature map, vs Tasy). Pilar que consome direto o cuidado agudo já entregue: cirurgia, PS e
> internação são os grandes consumidores de sangue. Regulatório: RDC 34/2014 ANVISA (hemoterapia), hemovigilância/NOTIVISA
> (reação transfusional). Estado: **greenfield** (sem banco de sangue no código). Metodologia: fanout TDD, melhor modelo por
> task, red→green, integração file-copy, deploy (backend rebuild + recreate + `create_default_roles --overwrite`; frontend
> host-build+overlay + `--force-recreate nextjs` da RAIZ). Régua: maturidade por camada.

## Reaproveitar (não duplicar)
- **Âncoras clínicas** (a requisição transfusional acontece num evento): `emr.Encounter`, `adt.Admission`, `surgery.SurgicalCase`, `emergency.EmergencyEncounter`. FK ao encounter/admission.
- **BCMA/eMAR análogo**: `apps/emr/services/bcma.py` (verificação "5 certos" por barcode) + `MedicationAdministration`. A **checagem transfusional beira-leito** é estruturalmente idêntica (paciente certo / bolsa certa / hemocomponente certo / compatibilidade ABO-RhD / validade) — espelhar bcma.py, com dupla checagem de enfermagem.
- **Estoque com lote/validade**: `apps/pharmacy.StockItem`/`StockMovement` (lote/expiry) — a bolsa de sangue É inventário; avaliar reúso vs modelo dedicado (bolsa tem sorologia + tipagem, então provável modelo dedicado `BloodBag` referenciando o padrão de estoque).
- **Catálogo governado**: `core.terminology_base.TerminologyCatalog` (se hemocomponente virar catálogo) ou enum. CID10 pra diagnóstico da indicação.
- **Padrões de código**: modelos-domínio em novo `apps/bloodbank` (ou apps/emr submódulo); serviço atômico (select_for_update) do ADT/CC/PS; append-only (eventos). RBAC `module.action`.

## Ownership (persona × escopo)
- **Médico** indica/prescreve a transfusão (`hemoterapia.request`). **Hemoterapeuta/agência transfusional** faz tipagem, prova
  de compatibilidade, reserva e libera (`hemoterapia.manage`). **Enfermagem** faz a checagem beira-leito + registra reação
  (`hemoterapia.transfuse`). Escopo: agência/leito.

## Sprints

### H1 · Estrutura: tipagem + hemocomponente + estoque de bolsas (backend) · **Opus**
`Patient.blood_type` (ABO A/B/AB/O + RhD +/-, nullable). `BloodComponent` (hemocomponente: concentrado de hemácias/plasma
fresco congelado/plaquetas/crioprecipitado — enum ou catálogo governado). `BloodBag`/BolsaDeSangue (número/identificador
único, componente, ABO/RhD, volume_ml, coleta/validade, status sorológico [liberada/quarentena/descartada], status estoque
[disponível/reservada/transfundida/descartada/vencida], lote). RBAC `bloodbank.read`/`hemoterapia.manage`. CRUD DRF + estoque.
Migração. pytest TDD.

### H2 · Doador + entrada de bolsa + sorologia (backend) · **Opus** (dep H1)
`BloodDonor` (doador). Entrada de bolsa (coleta/recebimento) + triagem sorológica (HIV/HBsAg/anti-HBc/anti-HCV/sífilis/
Chagas/HTLV) → libera de quarentena p/ disponível ou descarta. Aptidão do doador. RBAC `hemoterapia.manage`. pytest TDD.

### H3 · Requisição transfusional + prova de compatibilidade + reserva/liberação (backend) · **Opus** (dep H1)
`TransfusionRequest` (FK encounter/admission/surgical_case/emergency, paciente, componente, quantidade, indicação/CID,
urgência, solicitante). `CrossMatch`/ProvaDeCompatibilidade (bolsa × paciente: ABO/RhD + crossmatch, resultado compatível/
incompatível). Reservar bolsa compatível → liberar. Máquina de estados (solicitada→reservada→liberada→transfundida/cancelada),
atômica (select_for_update na bolsa). RBAC `hemoterapia.manage`. pytest TDD.

### H4 · Checagem beira-leito + reação transfusional/hemovigilância (backend) · **Opus** (dep H3)
Checagem transfusional beira-leito (espelha `bcma.py`: paciente×bolsa×componente×compatibilidade×validade, dupla checagem)
→ registra `TransfusionAdministration`. `TransfusionReaction` (reação: tipo, gravidade, conduta) + gancho hemovigilância/
NOTIVISA. RBAC `hemoterapia.transfuse`. pytest TDD.

### H5 · Painel Agência Transfusional (frontend) · **Opus** (dep H3)
Rota `/banco-de-sangue`: estoque de hemocomponentes (por tipo ABO/RhD + validade), requisições pendentes, prova de
compatibilidade, reservar/liberar. Nav "Banco de Sangue" gated `hemoterapia.read`. Vitest TDD.

### H6 · Requisição + checagem no prontuário (frontend) · **Opus** (dep H4)
Solicitar transfusão no prontuário `patients/[id]` (aba Transfusão), acompanhar reserva/liberação, checagem beira-leito
(scan bolsa/paciente → 5 certos transfusionais), registrar reação. Vitest TDD. RBAC `hemoterapia.transfuse`.

## Ordem
H1 → (H2, H3 podem paralelizar após H1) → H4 (dep H3) → (H5 dep H3, H6 dep H4). Cada sprint: integra, mount-run gate,
deploy, verifica headless. Novo RBAC entra em DEFAULT_ROLES **e** roda `create_default_roles --overwrite` no deploy.

## Régua
Maturidade por camada. Hemocomponentes/sorologia = domínio real RDC 34. NÃO quebrar pharmacy/estoque. A checagem
transfusional reusa o rigor do BCMA. Reação transfusional → hemovigilância é diferencial de compliance.
