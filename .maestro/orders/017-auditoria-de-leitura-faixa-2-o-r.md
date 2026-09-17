<!-- maestro-order v1
id: 017
ts: 2026-09-17T10:30:33-03:00
epoch: 1789651833
head: 52bdcad8687722ef3866ec0769696593abc9c478
branch: order/017-auditoria-leitura-hr
intent_version: 5
intent_hash: a6120b3c
author_session: desconhecido
-->
# Ordem 017 — Auditoria de leitura faixa 2: o RH que carrega dado pessoal sensivel deixa trilha

> **Direção:** INTENT v5, **Prioridade 5 — "Compliance como gate, não como sprint
> futura. LGPD, TISS/TUSS (RN 501/2022 ANS), CFM 1.821/2007 e ANVISA são critério de
> aceite, não item de backlog."** Aqui a lei que manda é a **LGPD, art. 5º II** (dado
> pessoal sensível: saúde, vida sexual, dado genético ou biométrico) e o **art. 37**
> (o controlador mantém registro das operações de tratamento). **Não é CFM 1.821:
> nesta faixa não há paciente** — há funcionário, e dependente de funcionário.

## Onde a cobertura está, e por que a faixa 2 não é dedução da faixa 1

A ordem 016 fechou a faixa 1 pelo critério "a view alcança `emr.Patient` no grafo de
models". Medido pelo roteador do Django, nunca por `grep`:

```
154 views registradas    59 com trilha (antes da 016)    95 sem
                         73 com trilha (depois)          81 sem
```

O RH **não aparece nesse critério e não deveria aparecer**: `hr.Employee` liga a
`core.User`, e `core.User` é aresta proibida em `audit_coverage.ARESTAS_PROIBIDAS` —
foi ela que produzia 46 falsos positivos na 016. O critério da faixa 1 está certo e
fica como está. O que falta é **um segundo critério**, porque dado pessoal sensível
existe fora do prontuário: a ficha de saúde ocupacional de um funcionário é dado de
saúde do art. 5º II tanto quanto um laudo, e ninguém nunca vai chegar nela partindo
de `Patient`.

## Quatro views recebem trilha — o motivo é o campo, não o nome do model

| view | o que se lê ali, medido no model |
|---|---|
| `LeaveRequestViewSet` | `leave_type` inclui `sick` = **"Afastamento médico"** e `maternity` = **"Licença-maternidade"** — saúde e gravidez; `reason` é `TextField` livre, onde entra diagnóstico |
| `OccupationalHealthExamViewSet` | `exam_type`, `result` (`fit`/`unfit`), **`restrictions`** (limitação funcional escrita), `certificate_reference` (o ASO). O docstring do model promete "without storing clinical findings" — `restrictions` é exatamente isso |
| `DependentViewSet` | `full_name`, `birth_date` e **`cpf` de terceiro**: filho ou cônjuge que **não é usuário do sistema e nunca consentiu aqui**. Dado pessoal de quem não tem como saber que está no banco |
| `TimeEntryViewSet` | **decisão do Imediato, 17/09**: ler o ponto de alguém é vigilância laboral. Não é art. 5º II — é art. 37, e a trilha custa uma linha. O motivo vai escrito no código, para não virar isenção por hábito ao contrário |

`TimeEntryViewSet` é `ReadOnlyModelViewSet`; os outros três são `ModelViewSet`. Em
todos, **`AuditReadMixin` entra como primeira base** — a lição da 016: ele precisa
interceptar `retrieve`/`list` antes do viewset do DRF, senão o `super()` do mixin
nunca é alcançado e a trilha some sem ninguém notar.

## Seis ficam sem trilha, e o motivo fica no código

`Employee` (o dado pessoal vive no `core.User`; o model tem `hire_date`,
`employment_status`, `contract_type` e as datas — é o vínculo, não a pessoa),
`WorkSchedule`, `Position`, `EmployeeAssignment`, `RosterSlot`, `DutyRoster`:
**organização do trabalho, não pessoa**. Escala de plantão e carga horária semanal
não dizem nada sobre a saúde nem sobre a vida de ninguém.

Isso **não** é "ficou de fora". É isenção declarada, com motivo escrito e testado —
o mesmo contrato que a 016 impôs a `UserDetailView`.

## Como o classificador muda

`apps/core/audit_coverage.py` ganha uma **lista explícita de models portadores de
dado sensível, cada um com o motivo** — e `exigem_trilha()` passa a ser a união dos
dois critérios: *alcança `Patient`* **ou** *está na lista*.

**Por que lista explícita e não heurística de campo.** O crivo por palavra-chave foi
tentado e reprovou: marcou `CostCenter.name` e `Room.name` como dado pessoal. Um
classificador que marca tudo não classifica nada — é a mesma falha dos 47 candidatos
da 016, e o INTENT §Limites já nomeia o defeito: alerta que vive vermelho ensina a
ignorar vermelho.

A lista é `model → motivo`, com teste exigindo motivo escrito, exatamente como
`ISENTAS`. Decidir que um model novo carrega dado sensível passa a exigir escrever
por quê.

## Prova

Mesma forma da 016, e o **recibo vem ANTES do PR** — a 016 ficou `aberta` no ledger
porque isso foi invertido:

```
teste que falha antes    4 falhas, nomeando view e motivo
suíte dos apps tocados   hr + core, 0 falhas
gate local               ruff · format · mypy · lint-imports · makemigrations --check
recibo                   maestro evidence --record --label order-17 -- <suíte>
```

Os três testes que a 016 deixou de pé continuam valendo e **não podem afrouxar**: o
piso de enumeração (acusa colapso da travessia do roteador), o motivo escrito de
toda isenção, e a reprovação de view clínica sem trilha.

## Faixa 3 segue sem trilha, e isso é decisão, não esquecimento

`DrugInteraction`, `AllergenClass`, `ImagingModality`, `CostCenter`, estoque de
farmácia, financeiro sem vínculo a guia. Auditar leitura de catálogo público enche o
`AuditLog` de ruído e ensina a ignorá-lo. O motivo está no `audit_coverage.py`, não
numa decisão perdida em histórico.

## Fora desta ordem

Migration, mudança de model, mudança de permissão e qualquer alteração de
`AuditReadMixin` que afete a faixa 1. Se a entrega precisar de alguma dessas, **pare
e reporte** — vira ordem própria.

## Contrato de execução
- Trabalhe APENAS no branch `order/017-auditoria-leitura-hr`; NUNCA no main/master.
- Prove com o ledger: `maestro evidence --record --label order-17 -- <suíte>` no tip do branch.
- Direção vigente na criação: INTENT v5 (`.maestro/INTENT.md`) — o plano cita a seção da direção que autoriza esta ordem.
- Estourou Ask-First ou orçamento? PARE e reporte ao humano — não improvise.
- O aceite é do diretor: `maestro order --accept 017` (você não fecha a própria ordem).
accepted_at: 2026-09-17T12:34:22-03:00
accepted_session: desconhecido
accepted_tree: 45ab08fc7b7ff4e98d4205d9723862f35f4f6b9c
accepted_intent: 5
