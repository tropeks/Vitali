<!-- maestro-order v1
id: 030
ts: 2026-09-27T15:40:28-03:00
epoch: 1790534428
head: df89ab17c15bc8f795d18129d9eefd8b891a0ce5
branch: order/030-fhir-leitura-na-trilha
intent_version: 6
intent_hash: f6a0c0bc
author_session: 9c684afb-6ba9-405a-9c4b-a3f6313897c6
-->
# Ordem 030 — Leitura FHIR deixa trilha, e a guarda passa a enxergar view sem queryset

> **Direção:** INTENT v6, **Prioridade 4** (compliance como gate): "Leitura de dado de
> paciente ou de dado pessoal sensível deixa trilha, por rota. View nova que lê esse dado
> entra coberta ou isenta com motivo escrito. A guarda reprova o resto. A cobertura se mede
> pelo roteador do Django." E **§Limites**: "Sinal verde tem que significar verde."
> Pedida pelo Diretor em 27/09, depois do aceite da 029, na frente da exportação fria.

## O que foi pedido, e o que a medição mostrou

A revisão da 029 achou as 22 views FHIR de leitura (`/api/v1/fhir/*`) fora da guarda,
porque são `APIView` pura, sem `queryset`. O Diretor pediu: a leitura FHIR deixa trilha, e
a guarda passa a enumerar `APIView`.

Medido na lab, no tip `df89ab1`, enumerando pelo roteador as rotas GET de toda view sem
`queryset`/`get_queryset`: **103 classes**, não 22. Nenhuma herda `AuditReadMixin`, e não
há middleware de auditoria. Um levantamento view a view (o `get()` de cada uma, com
arquivo:linha) classificou assim:

| | n | onde |
|---|---|---|
| leem dado de paciente | **49** | fhir 20, portal 15, emr 8, imaging 2, telemedicina 2, billing 1, farmácia 1 |
| ... e já gravam trilha no GET, em formato próprio | 3 | `LabOrderORMView`, `MeImagingReportView`, `MeLabReportPDFView` |
| ... e **não gravam nada** | **46** | |
| não leem dado de pessoa | 54 | analytics, config, catálogo, framework |

Entre as 46 estão o **export LGPD do portal** (`/portal/me/export/`: cadastro, agenda,
atendimentos, receitas e alergias, em JSON ou PDF), o **PDF da receita** e o **PDF do
laudo** do staff, os estudos de imagem, as sessões de telemedicina, o painel de alerta de
controlados (paciente ao lado de psicotrópico) e as 20 leituras FHIR de prontuário. Não
eram isentas: eram invisíveis, e ninguém tinha decidido nada.

## O mecanismo, igual ao da 019

**`AuditReadAPIViewMixin`** (`apps/core/mixins.py`), irmão do `AuditReadMixin` e com a
mesma base (`_GravaLeitura`: mesma linha de `AuditLog`, mesmo `_alvo_da_busca`). Grava no
`finalize_response`, o único ponto por onde passa toda resposta de uma `APIView`, e só em
GET 2xx. O modo é **declarativo**, para a guarda ler a cobertura sem executar a view:

- `AUDIT_LOOKUP_KWARG = "patient_id"`: rota de detalhe, grava `view_record` com o id;
- sem ele: busca ou lista, grava `view_record_list` sempre, com os `AUDIT_LIST_PARAMS`
  presentes em `new_data` e o alvo em `resource_id`, o que o `/audit-trail/` expõe.

O alvo sai de onde a leitura realmente mira:
- **FHIR:** `?patient=`/`?subject=`/`?beneficiary=` com a referência limpa (`Patient/<uuid>`
  vira `<uuid>`), ou, sem parâmetro, o paciente do contexto do token SMART confinado;
- **portal:** o paciente do próprio titular.

## O corte

**Recebem trilha (43):** as 20 leituras FHIR de prontuário; no portal, as de staff
(`AccessListCreateView`, `AccessDetailView`) e as do titular (`MeView`, `MeAllergies`,
`MeAppointments`, `MeConsents`, `MeEncounters`, `MeExport`, `MePrescriptions`,
`MeRepresentatives`, `MeImagingStudies`, `MeLabResults`); no emr, `LabReportPDFView`,
`PrescriptionPDFView`, `WaitlistViewSet`, `DeteriorationAlertsView` e `NoShowRiskView`;
imagem (`StudyListCreateView`, `StudyDetailView`); telemedicina (`SessionListCreateView`,
`SessionDetailView`); farmácia (`ControlledAlertsView`).

- **Os painéis sem polling** (deterioração, no-show, controlados, lista de espera): o
  levantamento do `frontend/` não achou `setInterval` neles. Uma linha por abertura de tela
  é o custo que a 019 já aceitou para `list`.
- **Portal lido pelo titular:** ler o próprio prontuário ainda é operação de tratamento a
  registrar (LGPD art. 37), e o export é a cópia mais ampla que sai do sistema. Volume
  limitado pela atenção de uma pessoa.

**Já tinham trilha própria (3):** ficam declaradas em `APIVIEWS_TRILHA_PROPRIA`, com a
action que gravam, e a guarda confere no fonte do `get()` que a action continua lá:
`LabOrderORMView` (`lis_orm_export`), `MeImagingReportView`
(`portal_imaging_report_viewed`) e `MeLabReportPDFView` (`portal_lab_report_downloaded`).

**Isentas com motivo, em `APIVIEWS_ISENTAS`:**
- `PractitionerReadView`/`PractitionerSearchView`: cadastro do profissional, a mesma
  decisão de `emr.Professional` na 029;
- `WaitingRoomView` (polling 30 s), `PrescriptionItemSafetyCheckView` (polling 2 s) e
  `ScribeStatusView` (polling 2 s): o precedente da 019 (`AppointmentViewSet.today`,
  `board`). Uma linha por repintura diz que a tela estava aberta, não quem foi procurar o
  quê. O conteúdo que devolvem (a agenda do dia, o veredito de um item de receita, o SOAP em
  geração) é lido com trilha pela rota própria;
- `MeImagingViewerAuthorizationView`: portão `auth_request` do nginx, chamado a cada
  request DICOMweb, sem corpo na resposta. A abertura do estudo é trilhada pela listagem e
  pelo laudo;
- `PIXChargeView` e `MeReceivablesView`: financeiro sem guia, a faixa 3 que o
  `SECURITY.md` §3.6.1 já declara sem trilha de leitura (o PIX ainda faz polling de 5 s);
- as 54 que não leem dado de pessoa, cada uma com o motivo.

## O entregável durável: a guarda enxerga view sem queryset

Em `apps/core/audit_coverage_routes.py`, `rotas_get_sem_queryset()` enumera pelo mesmo
roteador, sem filtro de queryset, por `(módulo, classe, action)`. Como uma `APIView` não
diz o que lê, o padrão é o inverso do grafo de models: **toda rota GET sem queryset exige
decisão**, coberta, trilha própria ou isenta com motivo. Testes novos em
`test_auditoria_leitura_cobertura.py`:
- toda rota classificada;
- as 20 leituras FHIR de prontuário cobertas, nomeadas;
- piso de enumeração (> 67, a folga de ~35% dos outros pisos);
- motivo escrito em toda isenção;
- nenhuma isenção órfã, sem rota ou de view que já grava;
- o mixin antes de `APIView` na MRO (senão o `finalize_response` do DRF vence e a trilha
  morre calada);
- **`AUDIT_LOOKUP_KWARG` casa um kwarg real da rota**, e toda rota de detalhe coberta
  declara um (estático: lê a URL e o atributo).

## Provas

- **Vermelho primeiro, publicado sozinho:** a guarda reprova as rotas sem classificação e
  as FHIR sem trilha. Pelo caminho real, reprovam: leitura e busca FHIR (inclusive com token
  SMART confinado), PDF da receita, export do portal.
- Recibo `order-30` na lab, suíte inteira, no tip do branch.

## Fora desta ordem (achados do levantamento, registrados)

- `AccessListCreateView`/`AccessDetailView` devolvem o `invite_token` no GET: segredo em
  listagem de staff.
- `WaitlistViewSet.get`, no ramo não-staff, filtra `Patient` por `user`, campo que
  `emr.Patient` não tem. O ramo deve dar 500.
- `ObservationReadView` separa o id por `_`; a docstring e o `CapabilityStatement` falam em
  `-`.
- `imaging/viewer-auth/` devolve 204 sem checar nada; o nginx não usa essa rota.
- `_classes_do_roteador()` deduplica por nome de classe. `core.MeView` e
  `patient_portal.MeView` colidem ali; a enumeração nova usa módulo + classe.

Nenhuma migration, nenhuma mudança de model, nenhuma mudança de permissão.

## Contrato de execução
- Trabalhe APENAS no branch `order/030-fhir-leitura-na-trilha`; NUNCA no main/master.
- Prove com o ledger: `maestro evidence --record --label order-30 -- <suíte>` no tip do branch.
- Direção vigente na criação: INTENT v6 (`.maestro/INTENT.md`) — o plano cita a seção da direção que autoriza esta ordem.
- Estourou Ask-First ou orçamento? PARE e reporte ao humano — não improvise.
- O aceite é do diretor: `maestro order --accept 030` (você não fecha a própria ordem).
