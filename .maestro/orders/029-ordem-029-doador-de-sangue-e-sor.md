<!-- maestro-order v1
id: 029
ts: 2026-09-27T12:55:18-03:00
epoch: 1790524518
head: d650bcda92fa03e27b225098a69efcbf33d316f6
branch: order/029-doador-e-sorologia-na-trilha
intent_version: 6
intent_hash: f6a0c0bc
author_session: 9c684afb-6ba9-405a-9c4b-a3f6313897c6
-->
# Ordem 029 — Doador de sangue e sorologia deixam trilha de leitura por rota, e a guarda passa a perguntar por identificador pessoal fora do grafo de Patient

> **Direção:** INTENT v6, **Prioridade 4** (compliance como gate): "Leitura de dado de
> paciente ou de dado pessoal sensível deixa trilha, por rota. View nova que lê esse dado
> entra coberta ou isenta com motivo escrito. A guarda (`apps/core/audit_coverage.py`)
> reprova o resto." E **§Limites**: "Sinal verde tem que significar verde."

## O que foi pedido, e o que a medição mostrou

O Diretor pediu (27/09): `BloodDonorViewSet` e `BloodBagSerologyViewSet` carregam nome,
CPF e sorologia (HIV, hepatites) de doador, que não é paciente, ficam fora do grafo de
`Patient` e por isso estão invisíveis à trilha de leitura das ordens 016 a 019.

Medido na lab, no tip `d650bcd`, antes de tocar em código:

1. **Os dois viewsets já herdam `AuditReadMixin`** (entrou na Onda 3, `6368592`). O
   `retrieve` grava `view_record`. O buraco não é o mixin ausente.
2. **A `list` sem filtro não grava nada.** O mixin só grava `list` com `?patient=` ou
   `?search=`, ou com `AUDIT_LIST_ALWAYS = True`, e nenhum dos dois tem a flag. O
   `DonorPanel` (`/banco-de-sangue`) chama `GET /api/v1/blood-donors/` cru a cada abertura
   de tela: o cadastro inteiro de doadores sai sem rastro. `GET /blood-bag-serologies/`
   (com ou sem `?bag=`) devolve o painel RDC 34 de todas as bolsas, também sem rastro.
3. **A guarda dá as quatro rotas como cobertas.** `rotas_get_registradas()` responde
   `coberta=True, motivo=''` para `list` e `retrieve` dos dois viewsets. `list` "passa"
   porque a guarda só exige `AUDIT_LIST_ALWAYS` de view sensível, e estas não são
   sensíveis para ela: `BloodDonor` e `BloodBagSerology` não alcançam `emr.Patient` e não
   estão em `MODELS_SENSIVEIS`. É o verde que não significa verde: se alguém tirar o mixin
   amanhã, nada reprova.
4. **Contato:** `BloodDonor` não tem telefone, e-mail nem endereço. Carrega `full_name`,
   `cpf`, `birth_date`, ABO/Rh, `apto` (aptidão a doar) e `notes` livre.

## Por que o buraco apareceu, e por que ele se repete

`MODELS_SENSIVEIS` (ordem 017) é lista explícita, e está certo que seja: o crivo por
palavra-chave, quando CLASSIFICAVA, marcou `CostCenter.name` e `Room.name` como dado
pessoal. Mas lista explícita só cobre o que alguém lembrou de pôr nela, e ninguém é
obrigado a lembrar. Doador entrou no Sprint H2 depois da 017 e ninguém perguntou.

Varrendo toda view registrada cujo model não alcança `Patient` e não está em
`MODELS_SENSIVEIS`, procurando campo que identifica pessoa natural (`cpf`, `rg`, `cns`,
`birth_date`, `full_name`, `mother_name`, `phone`, `telefone`, `email`), aparecem **duas**:

| view | model | campos | decisão |
|---|---|---|---|
| `BloodDonorViewSet` | `emr.BloodDonor` | `cpf`, `full_name`, `birth_date` | **sensível**: exige trilha |
| `ProfessionalViewSet` | `emr.Professional` | `cns` | **não sensível**, com motivo: o `ProfessionalSerializer` não devolve o `cns` (cifrado em repouso, só o BPA/APAC consome); o que a rota devolve é conselho, especialidade, CBO e CNES do profissional no exercício da função, e nome/e-mail vêm de `core.User` (staff). Nenhum dado de saúde |

| `SupplierViewSet` (achado na revisão, pelo sufixo) | `pharmacy.Supplier` | `contact_email`, `contact_phone` | **não sensível**, com motivo: fornecedor é pessoa jurídica; o contato comercial do representante é dado pessoal comum (art. 5º I), não sensível nem de paciente |

A primeira varredura casava só o nome exato e não viu o `Supplier`. A revisão achou o caso,
e a pergunta passou a casar também o sufixo `_<identificador>`.

`BloodBagSerology` não tem identificador direto (liga à bolsa pelo DIN). Por isso a
varredura não a pega, e ela entra por decisão escrita, não por gatilho.

## O corte

**Recebem trilha:**

1. `emr.BloodDonor` e `emr.BloodBagSerology` entram em `MODELS_SENSIVEIS`, cada um com o
   campo e a lei:
   - `BloodDonor`: `full_name`, `cpf` e `birth_date` identificam um terceiro que não é
     paciente; `apto` e `notes` carregam a inaptidão a doar, que é dado de saúde; ABO/Rh
     também. LGPD art. 5º II.
   - `BloodBagSerology`: HIV, HBsAg, anti-HBc, anti-HCV, sífilis, Chagas e HTLV, o painel
     RDC 34. É dado de saúde do doador daquela bolsa. O DIN é identificador de doação que o
     serviço de hemoterapia reassocia ao doador (e a RDC 34 exige convocar o doador
     reagente). É reversível, então não é anonimizado (LGPD art. 12): é pseudonimizado,
     no sentido do art. 13 §4º, e continua dado pessoal.
2. Os dois viewsets ganham `AUDIT_LIST_ALWAYS = True`. Custo medido: nenhum polling no
   `frontend/` bate nessas rotas (`DonorPanel` carrega no `useEffect` de montagem;
   `SerologyModal` só faz `POST`). Uma linha por abertura de tela, como a 019 já aceita.
3. `BloodBagSerologyViewSet` grava o `?bag=` como critério (`AUDIT_LIST_PARAMS`), para a
   trilha dizer QUAL bolsa foi consultada, e não só que alguém listou. `?bag=` malformado
   devolve 400 e não grava, no mesmo padrão do `?employee=` do RH (antes dava 500).
4. **Achado da revisão, corrigido na raiz:** `AuditReadMixin.list()` punha em
   `resource_id` só `?patient=`. O critério próprio da view (`?bag=` aqui, `?employee=` no
   RH desde a 018) ficava só em `new_data`, e o `AuditTrailEntrySerializer` não expõe
   `new_data`, de propósito. Quem lia `/audit-trail/` via "alguém listou" e nunca "listou o
   quê". Agora o primeiro critério que não é `search` vai para `resource_id` (`patient`
   continua vencendo), e o `/audit-trail/` ganha `?resource=`, o mesmo filtro de
   `?patient=` com nome que não mente quando o alvo é bolsa ou funcionário.

**O entregável durável: a guarda passa a perguntar.** Novo teste em
`test_auditoria_leitura_cobertura.py`: toda view registrada cujo model tem campo que
identifica pessoa natural (`IDENTIFICADORES_PESSOAIS`, em `audit_coverage.py`) precisa estar
classificada: alcança `Patient`, OU está em `MODELS_SENSIVEIS`, OU está em
`MODELS_SEM_DADO_SENSIVEL` com motivo. O nome do campo **dispara a pergunta, não a
responde**: a classificação continua explícita e escrita, como a 017 exige. Falso positivo
custa uma declaração com motivo; falso negativo custava o doador.

`MODELS_SEM_DADO_SENSIVEL` deixa de ser só do app `hr` e recebe `emr.Professional`.

**NÃO recebe, e o motivo fica aqui:**

- `BloodBagViewSet` (estoque): mostra `serology_status` (quarentena/liberada/descartada),
  não o marcador, e `descartada` também sai por vencimento e avaria. Não tem campo de
  pessoa. É o quadro de estoque do banco de sangue.

## Provas

- **Vermelho primeiro, publicado sozinho:** a guarda por identificador reprova
  `BloodDonorViewSet` e `ProfessionalViewSet`; a guarda de classificação reprova
  doador/sorologia fora de `exigem_trilha()`; e `GET /blood-donors/` e
  `GET /blood-bag-serologies/?bag=` sem critério de paciente gravam
  `view_record_list` pelo caminho real (APIClient → roteador → viewset), com o `bag` em
  `new_data`.
- Recibo `order-29` na lab, suíte inteira, no tip do branch.

## Fora desta ordem

- **Achado da revisão, conferido, para ordem própria (e é grande):** as 22 views FHIR de
  leitura em `apps/fhir/views.py` (read e search de `Patient`, `Encounter`, `Practitioner`,
  `AllergyIntolerance`, `MedicationRequest`, `Observation`, `Condition`, `ServiceRequest`,
  `DocumentReference`, `DiagnosticReport` e `Coverage`), roteadas em `/api/v1/fhir/`, são
  `APIView` pura, sem `queryset`. Por isso `_classes_do_roteador()` e
  `_rotas_get_do_roteador()` não as enumeram, e não há nenhuma chamada de auditoria no
  módulo. É leitura de prontuário fora da guarda por construção, a mesma classe de buraco
  desta ordem, só que na enumeração. Nenhuma delas toca doador ou sorologia, e o mapper de
  `Practitioner` não expõe `cns`, então o escopo desta ordem não muda.

- Leitura pelo Django admin: nenhum dos dois models está registrado em `admin.py`.
- Destino de exportação fria da retenção de 20 anos: próxima ordem.

Nenhuma migration, nenhuma mudança de model, nenhuma mudança de permissão.


## Contrato de execução
- Trabalhe APENAS no branch `order/029-doador-e-sorologia-na-trilha`; NUNCA no main/master.
- Prove com o ledger: `maestro evidence --record --label order-29 -- <suíte>` no tip do branch.
- Direção vigente na criação: INTENT v6 (`.maestro/INTENT.md`) — o plano cita a seção da direção que autoriza esta ordem.
- Estourou Ask-First ou orçamento? PARE e reporte ao humano — não improvise.
- O aceite é do diretor: `maestro order --accept 029` (você não fecha a própria ordem).
